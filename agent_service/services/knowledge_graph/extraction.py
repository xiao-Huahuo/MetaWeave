"""KnowledgeGraphService 的 extraction 职责。

方法体由原服务机械迁移，业务行为不变。
"""

from __future__ import annotations
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from langchain_core.messages import HumanMessage, SystemMessage
import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.engine import Engine
from sqlmodel import Session, select
from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.core.db.engine import get_database_engine
from agent_service.models.knowledge_graph import (
    KnowledgeGraphDocumentStatus,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from agent_service.models.session import utc_now
from agent_service.services.memory.rag.frontmatter_document import (
    StructuredKnowledgeDocument,
    StructuredKnowledgeSection,
)
from agent_service.services.memory.rag.embedding import EmbeddingService
from agent_service.services.scheduler import (
    BACKGROUND_FACT_RESOLUTION_TASK,
    LLMTaskScheduler,
    SMALL_MODEL_TIER,
    get_llm_task_scheduler,
)
from agent_service.services.token_usage.service import TokenUsageService
from agent_service.services.knowledge_graph.service import (
    ENTITY_TYPES, EntityCandidate, GraphExtractionResult, KnowledgeGraphExtractor,
    LLMKnowledgeGraphExtractor,
    RelationCandidate, StructuredKnowledgeDocument, StructuredKnowledgeSection,
)
from agent_service.services.knowledge_graph.local_extractor import RemoteKnowledgeGraphExtractor
from agent_service.services.knowledge_graph.cache import extract_cached_graph_section_payloads

logger = logging.getLogger(__name__)

class KnowledgeGraphExtractionMixin:
    def extract_document(
        self,
        *,
        user_id: str,
        library_id: str,
        document: StructuredKnowledgeDocument,
        llm_config: dict[str, Any] | None = None,
    ) -> GraphExtractionResult:
        """抽取单个结构化文档并写入图谱表。"""

        result = GraphExtractionResult(files_seen=1, document_ids_seen={document.document_id})
        if self._is_document_current(
            user_id=user_id,
            library_id=library_id,
            document_id=document.document_id,
            source_hash=document.ingestion_hash,
        ):
            result.files_skipped = 1
            return result
        if self.extractor is not None:
            extractor = self.extractor
        else:
            from agent_service.services.knowledge_graph.service import _build_llm_config

            resolved_llm_config = _build_llm_config(self.config, user_llm_config=llm_config)
            remote_extractor = (
                LLMKnowledgeGraphExtractor(
                    config=self.config,
                    llm_config=resolved_llm_config,
                    user_id=user_id,
                    library_id=library_id,
                )
                if resolved_llm_config.get("small_model_name") and resolved_llm_config.get("small_api_key")
                else None
            )
            extractor = RemoteKnowledgeGraphExtractor(
                config=self.config,
                remote_extractor=remote_extractor,
            )
        try:
            section_payloads, section_caches, has_pending = extract_cached_graph_section_payloads(
                service=self,
                extractor=extractor,
                user_id=user_id,
                library_id=library_id,
                document=document,
                max_workers=1,
            )
            entities_by_key: dict[tuple[str, str], EntityCandidate] = {}
            relations: list[tuple[RelationCandidate, StructuredKnowledgeSection]] = []
            for section in document.sections:
                payload = section_payloads.get(section.section_id, {"entities": [], "relations": []})
                section_entities = self._sanitize_entities(payload.get("entities"))
                for entity in section_entities:
                    entities_by_key[(self._normalize_label(entity.name), entity.entity_type)] = entity
                section_entity_names = {entity.name for entity in section_entities}
                section_relations = self._sanitize_relations(
                    payload.get("relations"),
                    section_text=section.content,
                    allowed_entity_names=section_entity_names,
                )
                section_relations = self._augment_explicit_text_relations(
                    section_text=section.content,
                    section_entities=section_entities,
                    section_relations=section_relations,
                )
                relations.extend((relation, section) for relation in section_relations)

            entity_list, name_mapping, document_dedup_pending = self._deduplicate_document_entities_layered(
                user_id=user_id,
                library_id=library_id,
                entities=list(entities_by_key.values()),
                extractor=extractor,
                document=document,
            )
            has_pending = has_pending or document_dedup_pending
            entities_by_key, relations = self._remap_graph_candidates(
                entities=entity_list,
                relations=relations,
                name_mapping=name_mapping,
            )

            if entities_by_key:
                entity_list = list(entities_by_key.values())
                cross_mapping, dedup_pending = self._deduplicate_entities_incremental(
                    user_id=user_id, library_id=library_id,
                    new_entities=entity_list, extractor=extractor, document=document,
                    return_pending_status=True,
                )
                has_pending = has_pending or dedup_pending
                if cross_mapping:
                    entities_by_key, relations = self._remap_graph_candidates(
                        entities=entity_list,
                        relations=relations,
                        name_mapping=cross_mapping,
                    )

            status = "partial" if has_pending else ("completed" if entities_by_key or relations else "skipped")
            message = "gray candidates pending retry" if has_pending else ("" if entities_by_key or relations else "no valid graph candidates")
            written_entities, written_relations = self.replace_document_graph_atomic(
                user_id=user_id,
                library_id=library_id,
                document=document,
                entities=list(entities_by_key.values()),
                relations=relations,
                section_caches=section_caches,
                status=status,
                message=message,
            )
            result.files_extracted = 1 if written_entities or written_relations or has_pending else 0
            result.files_skipped = 0 if result.files_extracted else 1
            result.entities_written = written_entities
            result.relations_written = written_relations
            return result
        except Exception as exc:
            logger.warning("知识图谱抽取失败 | document=%s error=%s", document.document_id, exc)
            self._write_document_node(user_id=user_id, library_id=library_id, document=document)
            self._write_status(
                user_id=user_id,
                library_id=library_id,
                document=document,
                status="failed",
                message=str(exc)[:1000],
                entity_count=0,
                relation_count=0,
            )
            result.files_failed = 1
            return result

    def _remap_graph_candidates(
        self,
        *,
        entities: list[EntityCandidate],
        relations: list[tuple[RelationCandidate, StructuredKnowledgeSection]],
        name_mapping: dict[str, str],
    ) -> tuple[dict[tuple[str, str], EntityCandidate], list[tuple[RelationCandidate, StructuredKnowledgeSection]]]:
        """应用规范实体名并同步重映射关系端点，清除产生的自环。"""

        keyed: dict[tuple[str, str], EntityCandidate] = {}
        for entity in entities:
            entity.name = name_mapping.get(entity.name, entity.name)
            key = (self._normalize_label(entity.name), entity.entity_type)
            if key not in keyed or entity.confidence > keyed[key].confidence:
                keyed[key] = entity
        remapped: list[tuple[RelationCandidate, StructuredKnowledgeSection]] = []
        for relation, section in relations:
            relation.source = name_mapping.get(relation.source, relation.source)
            relation.target = name_mapping.get(relation.target, relation.target)
            if self._normalize_label(relation.source) != self._normalize_label(relation.target):
                remapped.append((relation, section))
        return keyed, remapped
    def _sanitize_entities(self, raw_entities: Any) -> list[EntityCandidate]:
        """清洗模型返回实体候选。"""

        if not isinstance(raw_entities, list):
            return []
        entities: list[EntityCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            name = self._clean_label(item.get("name"))
            entity_type = str(item.get("type") or item.get("entity_type") or "other").strip().lower()
            if entity_type not in ENTITY_TYPES:
                entity_type = "other"
            if not self._is_valid_entity_name(name):
                continue
            key = (self._normalize_label(name), entity_type)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                EntityCandidate(
                    name=name,
                    entity_type=entity_type,
                    aliases=[
                        self._clean_label(alias)
                        for alias in item.get("aliases", [])
                        if self._is_valid_entity_name(self._clean_label(alias))
                    ][:5],
                    description=str(item.get("description") or "")[:240],
                    confidence=self._clamp_float(item.get("confidence"), default=0.7),
                )
            )
        return entities[:80]
    def _sanitize_relations(
        self,
        raw_relations: Any,
        *,
        section_text: str,
        allowed_entity_names: set[str],
    ) -> list[RelationCandidate]:
        """清洗模型返回关系候选。"""

        if not isinstance(raw_relations, list):
            return []
        allowed_by_norm = {self._normalize_label(name): name for name in allowed_entity_names}
        relations: list[RelationCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in raw_relations:
            if not isinstance(item, dict):
                continue
            source = allowed_by_norm.get(self._normalize_label(str(item.get("source") or "")))
            target = allowed_by_norm.get(self._normalize_label(str(item.get("target") or "")))
            relation_type = str(item.get("type") or item.get("relation_type") or "").strip().lower()
            evidence = str(item.get("evidence") or "").strip()
            confidence = self._clamp_float(item.get("confidence"), default=0.7)
            if not source or not target or source == target:
                continue
            if confidence < 0.55:
                continue
            if not evidence or evidence not in section_text:
                norm_ev = self._normalize_label(evidence)
                norm_section = self._normalize_label(section_text)
                if norm_ev and norm_ev in norm_section:
                    pass
                else:
                    # 移除所有标点和空白后再次尝试（处理 LLM 加空格的中文场景）
                    compact_pat = re.compile(r"[^\w一-鿿]")
                    compact_ev = compact_pat.sub("", norm_ev)
                    compact_section = compact_pat.sub("", norm_section)
                    if not compact_ev or compact_ev not in compact_section:
                        continue
            key = (source, target, relation_type, evidence)
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                RelationCandidate(
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    evidence=evidence[:500],
                    confidence=confidence,
                )
            )
        return relations[:120]
    def _augment_explicit_text_relations(
        self,
        *,
        section_text: str,
        section_entities: list[EntityCandidate],
        section_relations: list[RelationCandidate],
    ) -> list[RelationCandidate]:
        """补充模型漏掉的、由原文直接表达的实体间关系。

        只处理同一 section 内已经由模型抽出的实体,并且只补明确写出的相似关系
        （例如 `A像B`、`A类似B`、`A相似B`）。这避免把普通共现误判为语义边。
        """

        if len(section_entities) < 2 or not section_text.strip():
            return section_relations
        augmented = list(section_relations)
        seen_pairs = {
            (self._normalize_label(relation.source), self._normalize_label(relation.target))
            for relation in augmented
        }
        for relation in self._infer_similarity_relations(section_text=section_text, section_entities=section_entities):
            key = (self._normalize_label(relation.source), self._normalize_label(relation.target))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            augmented.append(relation)
        return augmented[:120]
    def _infer_similarity_relations(
        self,
        *,
        section_text: str,
        section_entities: list[EntityCandidate],
    ) -> list[RelationCandidate]:
        """从 `A像B` 这类明示文本中推断相似关系候选。"""

        entities = sorted(section_entities, key=lambda entity: len(entity.name), reverse=True)
        predicates = ("类似于", "相似于", "像是", "类似", "相似", "像")
        predicate_pattern = "|".join(re.escape(predicate) for predicate in predicates)
        relations: list[RelationCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        for source in entities:
            for target in entities:
                if self._normalize_label(source.name) == self._normalize_label(target.name):
                    continue
                pattern = re.compile(
                    rf"{re.escape(source.name)}\s*(?:{predicate_pattern})\s*{re.escape(target.name)}"
                )
                match = pattern.search(section_text)
                if not match:
                    continue
                evidence = match.group(0).strip()
                key = (source.name, target.name, evidence)
                if key in seen:
                    continue
                seen.add(key)
                relations.append(
                    RelationCandidate(
                        source=source.name,
                        target=target.name,
                        relation_type="related_to",
                        evidence=evidence[:500],
                        confidence=0.68,
                    )
                )
        return relations
    @staticmethod
    def _load_document(frontmatter_path: Path) -> StructuredKnowledgeDocument:
        """从 frontmatter JSON 加载结构化文档。"""

        payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
        return StructuredKnowledgeDocument.from_dict(payload)
    @staticmethod
    def _clean_label(value: Any) -> str:
        """清理实体标签。"""

        return re.sub(r"\s+", " ", str(value or "").strip()).strip("`\"'“”‘’")
    @staticmethod
    def _is_valid_entity_name(value: str) -> bool:
        """过滤明显无效或过泛的实体名。"""

        if not value or len(value) > 80:
            return False
        if re.fullmatch(r"[\W_]+", value, flags=re.UNICODE):
            return False
        return value not in {"系统", "用户", "文件", "文档", "内容", "数据", "信息"}
    @staticmethod
    def _normalize_label(value: str) -> str:
        """实体规范名归一。"""

        return re.sub(r"\s+", " ", value.strip().lower())
    @staticmethod
    def _clamp_float(value: Any, *, default: float) -> float:
        """解析并裁剪 0-1 浮点数。"""

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(0.0, min(1.0, parsed))
