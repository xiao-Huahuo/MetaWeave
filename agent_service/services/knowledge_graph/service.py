"""
知识库图谱抽取与查询服务。

功能说明:
本文件把结构化 frontmatter 文档转换为 SQLite 中的知识图谱点边数据。它只消费
`StructuredKnowledgeDocument.sections` 中的文字内容,不处理图片、OCR 或视觉描述。

使用说明:
知识库入库完成后调用 `extract_frontmatter_file()` 或 `extract_frontmatter_dir()`。
前端调用 `get_graph()` 获取可视化所需的 nodes/links 数据。
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
import tiktoken
from sklearn.cluster import DBSCAN
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.core.context_budget import ContextBudget, ModelCapacity
from agent_service.core.db.engine import get_database_engine
from agent_service.models.knowledge_graph import (
    KnowledgeGraphDocumentStatus,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphSectionCache,
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

logger = logging.getLogger(__name__)

ENTITY_TYPES = {
    "person",
    "organization",
    "project",
    "module",
    "class",
    "function",
    "file",
    "concept",
    "config",
    "data",
    "other",
}
RELATION_TYPES = {
    "defines",
    "contains",
    "depends_on",
    "produces",
    "consumes",
    "calls",
    "configures",
    "mentions",
    "related_to",
    "likes",
    "knows",
    "uses",
    "creates",
    "modifies",
}
WEAK_RELATION_TYPES = {"mentions", "related_to"}


class KnowledgeGraphExtractor(Protocol):
    """实体关系候选抽取器协议,测试可注入假实现。"""

    def extract(self, *, document: StructuredKnowledgeDocument, section: StructuredKnowledgeSection) -> dict[str, Any]:
        """从一个 section 中抽取候选实体和关系。"""


@dataclass(slots=True)
class GraphExtractionResult:
    """知识图谱抽取统计结果。"""

    files_seen: int = 0
    files_extracted: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    entities_written: int = 0
    relations_written: int = 0
    document_ids_seen: set[str] = field(default_factory=set)


@dataclass(slots=True)
class EntityCandidate:
    """清洗后的实体候选。"""

    name: str
    entity_type: str
    aliases: list[str]
    description: str
    confidence: float


@dataclass(slots=True)
class RelationCandidate:
    """清洗后的关系候选。"""

    source: str
    target: str
    relation_type: str
    evidence: str
    confidence: float


class LLMKnowledgeGraphExtractor:
    """联网小模型适配器，负责全文实体关系抽取及语义去重。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        task_scheduler: LLMTaskScheduler | None = None,
        llm_config: dict[str, Any] | None = None,
        user_id: str | None = None,
        library_id: str | None = None,
    ) -> None:
        """保存模型调度依赖和用户模型覆盖配置。"""

        self.config = config
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(config)
        self.llm_config = llm_config or {}
        self.user_id = user_id
        self.library_id = library_id
        self.token_usage_service = TokenUsageService(config=config)

    def extract(self, *, document: StructuredKnowledgeDocument, section: StructuredKnowledgeSection) -> dict[str, Any]:
        """调用 small tier 模型,要求只返回 JSON 对象。"""

        content = section.content.strip()
        if not content:
            return {"entities": [], "relations": []}
        response = self.task_scheduler.invoke_chat(
            task_type=BACKGROUND_FACT_RESOLUTION_TASK,
            model_tier=SMALL_MODEL_TIER,
            messages=[
                SystemMessage(content=self._system_prompt()),
                HumanMessage(content=self._human_prompt(
                    document=document,
                    section=section,
                    content=content,
                )),
            ],
            model_name=self._value("model_name"),
            api_key=self._value("api_key"),
            base_url=self._value("base_url"),
            small_model_name=self._value("small_model_name"),
            small_api_key=self._value("small_api_key"),
            small_base_url=self._value("small_base_url"),
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        self._record_token_usage(response=response, document=document, section=section)
        return self._parse_json_object(str(response.content or ""))

    def extract_batch(
        self,
        *,
        document: StructuredKnowledgeDocument,
        sections: list[StructuredKnowledgeSection],
    ) -> dict[str, dict[str, Any]]:
        """一次请求抽取多个短章节，并按 section_id 返回各自结果。"""

        results = {
            section.section_id: {"entities": [], "relations": []}
            for section in sections
        }
        non_empty_sections = [section for section in sections if section.content.strip()]
        if not non_empty_sections:
            return results
        if len(non_empty_sections) == 1:
            section = non_empty_sections[0]
            results[section.section_id] = self.extract(document=document, section=section)
            return results

        response = self.task_scheduler.invoke_chat(
            task_type=BACKGROUND_FACT_RESOLUTION_TASK,
            model_tier=SMALL_MODEL_TIER,
            messages=[
                SystemMessage(content=self._batch_system_prompt()),
                HumanMessage(content=self._batch_human_prompt(document=document, sections=non_empty_sections)),
            ],
            model_name=self._value("model_name"),
            api_key=self._value("api_key"),
            base_url=self._value("base_url"),
            small_model_name=self._value("small_model_name"),
            small_api_key=self._value("small_api_key"),
            small_base_url=self._value("small_base_url"),
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        self._record_token_usage(response=response, document=document, section=non_empty_sections[0])
        payload = self._parse_json_object(str(response.content or ""))
        valid_ids = set(results)
        for item in payload.get("sections", []):
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id", ""))
            if section_id not in valid_ids:
                continue
            results[section_id] = {
                "entities": item.get("entities", []),
                "relations": item.get("relations", []),
            }
        return results

    def adjudicate_candidates(
        self,
        *,
        document: StructuredKnowledgeDocument,
        section: StructuredKnowledgeSection,
        candidates: dict[str, Any],
        evidence_context: str,
    ) -> dict[str, Any]:
        """仅把灰区候选和最短证据交给联网小模型确认。"""

        response = self.task_scheduler.invoke_chat(
            task_type=BACKGROUND_FACT_RESOLUTION_TASK,
            model_tier=SMALL_MODEL_TIER,
            messages=[
                SystemMessage(content=self.config.prompts.knowledge_graph_adjudication_system_prompt),
                HumanMessage(content=(
                    f"文档标题: {document.title}\n"
                    f"section_id: {section.section_id}\n"
                    f"灰区候选:\n{json.dumps(candidates, ensure_ascii=False)}\n"
                    f"最短原文证据:\n{evidence_context}"
                )),
            ],
            model_name=self._value("model_name"),
            api_key=self._value("api_key"),
            base_url=self._value("base_url"),
            small_model_name=self._value("small_model_name"),
            small_api_key=self._value("small_api_key"),
            small_base_url=self._value("small_base_url"),
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        self._record_token_usage(response=response, document=document, section=section, event="gray_adjudicated")
        return self._parse_json_object(str(response.content or ""))

    def _record_token_usage(
        self,
        *,
        response: Any,
        document: StructuredKnowledgeDocument,
        section: StructuredKnowledgeSection,
        event: str = "section_extracted",
    ) -> None:
        """Persist graph extraction model usage as a non-session background call."""

        if not self.user_id:
            return
        suffix = "" if event == "section_extracted" else f"_{event}"
        source_id = f"knowledge_graph_{self.library_id or 'default'}_{document.document_id}_{section.section_id}{suffix}"
        self.token_usage_service.record_llm_response_token_usage(
            user_id=self.user_id,
            session_id=None,
            response=response,
            node="knowledge_graph",
            event=event,
            model_tier=SMALL_MODEL_TIER,
            source_id=source_id,
        )

    def _system_prompt(self) -> str:
        """返回实体关系抽取系统提示词。"""

        return self.config.prompts.knowledge_graph_extraction_system_prompt

    def _batch_system_prompt(self) -> str:
        """返回保留章节归属的批量实体关系抽取提示词。"""

        return self.config.prompts.knowledge_graph_batch_system_prompt

    @staticmethod
    def _batch_human_prompt(
        *,
        document: StructuredKnowledgeDocument,
        sections: list[StructuredKnowledgeSection],
    ) -> str:
        """构造多个短章节共用的一次模型输入。"""

        blocks = []
        for section in sections:
            blocks.append(
                f"section_id: {section.section_id}\n"
                f"标题路径: {' / '.join(section.title_path)}\n"
                f"正文:\n{section.content.strip()}"
            )
        return f"文档标题: {document.title}\n\n" + "\n\n--- 章节分隔 ---\n\n".join(blocks)

    @staticmethod
    def _human_prompt(
        *,
        document: StructuredKnowledgeDocument,
        section: StructuredKnowledgeSection,
        content: str,
    ) -> str:
        """构造单 section 抽取输入。"""

        return (
            f"文档标题: {document.title}\n"
            f"标题路径: {' / '.join(section.title_path)}\n"
            f"section_id: {section.section_id}\n"
            "正文:\n"
            f"{content}"
        )

    def _value(self, key: str) -> str | None:
        """读取用户模型覆盖配置。"""

        value = self.llm_config.get(key)
        return str(value).strip() if value else None

    def _capacity_value(self, key: str) -> int | None:
        """读取用户为图谱小模型保存的正整数能力覆盖。"""

        try:
            value = int(self.llm_config.get(key) or 0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def context_budget(self) -> ContextBudget:
        """返回当前图谱小模型用于章节切块的动态预算。"""

        model_name = (
            self._value("small_model_name")
            or self._value("model_name")
            or self.config.model.small_model_name
            or self.config.model.model_name
            or ""
        )
        capacity = ModelCapacity.resolve(
            config=self.config,
            model_name=model_name,
            model_tier=SMALL_MODEL_TIER,
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        return ContextBudget.from_config(config=self.config, capacity=capacity)

    def deduplicate_entities(
        self,
        entities: list[EntityCandidate],
        document: StructuredKnowledgeDocument,
    ) -> dict[str, Any]:
        """对文档级实体做语义去重,返回合并后的实体列表和名称映射表。"""

        if len(entities) <= 1:
            return {"entities": list(entities), "name_mapping": {e.name: e.name for e in entities}}
        response = self.task_scheduler.invoke_chat(
            task_type=BACKGROUND_FACT_RESOLUTION_TASK,
            model_tier=SMALL_MODEL_TIER,
            messages=[
                SystemMessage(content=self._dedup_system_prompt()),
                HumanMessage(content=self._dedup_human_prompt(document=document, entities=entities)),
            ],
            model_name=self._value("model_name"),
            api_key=self._value("api_key"),
            base_url=self._value("base_url"),
            small_model_name=self._value("small_model_name"),
            small_api_key=self._value("small_api_key"),
            small_base_url=self._value("small_base_url"),
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        self._record_dedup_token_usage(response=response, document=document)
        payload = self._parse_json_object(str(response.content or ""))
        groups = payload.get("groups", []) if isinstance(payload, dict) else []
        if not groups:
            return {"entities": list(entities), "name_mapping": {e.name: e.name for e in entities}}

        consumed: set[int] = set()
        merged: list[EntityCandidate] = []
        name_mapping: dict[str, str] = {}

        for group in groups:
            if not isinstance(group, dict):
                continue
            canonical_name = str(group.get("canonical_name", "")).strip()
            if not self._is_valid_entity_name(canonical_name):
                continue
            entity_type = str(group.get("canonical_type") or "other").strip().lower()
            if entity_type not in ENTITY_TYPES:
                entity_type = "other"
            indices = [
                i for i in group.get("entity_indices", [])
                if isinstance(i, int) and 0 <= i < len(entities)
            ]
            if not indices:
                continue
            consumed.update(indices)
            for idx in indices:
                orig_name = entities[idx].name
                if orig_name != canonical_name:
                    name_mapping[orig_name] = canonical_name

            merged.append(
                EntityCandidate(
                    name=canonical_name,
                    entity_type=entity_type,
                    aliases=group.get("aliases", [])[:5],
                    description="",
                    confidence=max(entities[i].confidence for i in indices),
                )
            )

        for i, entity in enumerate(entities):
            if i not in consumed:
                merged.append(entity)
                name_mapping[entity.name] = entity.name

        for entity in entities:
            if entity.name not in name_mapping:
                name_mapping[entity.name] = entity.name

        return {"entities": merged, "name_mapping": name_mapping}

    def _dedup_system_prompt(self) -> str:
        """返回实体语义去重系统提示词。"""

        return self.config.prompts.knowledge_graph_dedup_system_prompt

    @staticmethod
    def _dedup_human_prompt(
        *,
        document: StructuredKnowledgeDocument,
        entities: list[EntityCandidate],
    ) -> str:
        """构造语义去重输入。"""

        lines = []
        for i, entity in enumerate(entities):
            lines.append(
                f"  [{i}] name={entity.name}  type={entity.entity_type}  "
                f"aliases={entity.aliases}  desc={entity.description[:80]}"
            )
        return (
            f"文档标题: {document.title}\n"
            "候选实体列表(每行格式: [index] name=... type=... aliases=... desc=...):\n"
            + "\n".join(lines)
            + "\n\n请返回 JSON 数组 groups，每个 group 包含:\n"
            '  - canonical_name: 规范名称\n'
            '  - canonical_type: 实体类型\n'
            '  - entity_indices: 属于该组的输入实体索引列表\n'
            '  - aliases: 该实体的别名列表\n'
            '输出: {"groups": [...]}'
        )

    def deduplicate_entities_incremental(
        self,
        entities: list[EntityCandidate],
        candidates: dict[str, list[tuple[str, float]]],
        document: StructuredKnowledgeDocument,
    ) -> dict[str, str]:
        """对入库新实体做库级去重: 小模型判断新实体是否与已有实体同义。

        candidates: {new_entity_name: [(existing_name, similarity), ...]}

        返回 name_mapping: {new_entity_name: canonical_existing_name, ...}
        """

        if not candidates:
            return {}
        response = self.task_scheduler.invoke_chat(
            task_type=BACKGROUND_FACT_RESOLUTION_TASK,
            model_tier=SMALL_MODEL_TIER,
            messages=[
                SystemMessage(content=self._dedup_incremental_system_prompt()),
                HumanMessage(content=self._dedup_incremental_human_prompt(
                    document=document, entities=entities, candidates=candidates,
                )),
            ],
            model_name=self._value("model_name"),
            api_key=self._value("api_key"),
            base_url=self._value("base_url"),
            small_model_name=self._value("small_model_name"),
            small_api_key=self._value("small_api_key"),
            small_base_url=self._value("small_base_url"),
            context_window_tokens=self._capacity_value("small_model_context_window_tokens"),
            max_output_tokens=self._capacity_value("small_model_max_output_tokens"),
        )
        self._record_dedup_token_usage(response=response, document=document)
        payload = self._parse_json_object(str(response.content or ""))
        merges = payload.get("merges", []) if isinstance(payload, dict) else []
        name_mapping: dict[str, str] = {}
        for merge in merges:
            if not isinstance(merge, dict):
                continue
            from_name = str(merge.get("from", "")).strip()
            to_name = str(merge.get("to", "")).strip()
            if from_name and to_name and from_name != to_name:
                name_mapping[from_name] = to_name
        return name_mapping

    def _dedup_incremental_system_prompt(self) -> str:
        """返回增量去重系统提示词。"""

        return self.config.prompts.knowledge_graph_incremental_dedup_system_prompt

    @staticmethod
    def _dedup_incremental_human_prompt(
        *,
        document: StructuredKnowledgeDocument,
        entities: list[EntityCandidate],
        candidates: dict[str, list[tuple[str, float]]],
    ) -> str:
        """构造增量去重输入。"""

        lines = [f"文档标题: {document.title}", "新实体及候选:"]
        for entity in entities:
            name = entity.name
            entry = f"  [{name}] type={entity.entity_type}"
            cands = candidates.get(name, [])
            if cands:
                cand_str = ", ".join(f"{c}({s:.2f})" for c, s in cands[:5])
                entry += f" → 候选: {cand_str}"
            lines.append(entry)
        return (
            "\n".join(lines)
            + '\n\n请输出: {"merges": [{"from": "新实体名", "to": "库中已有实体名"}, ...]}'
            + "\n只输出确定同义的映射。"
        )

    def _record_dedup_token_usage(
        self,
        *,
        response: Any,
        document: StructuredKnowledgeDocument,
    ) -> None:
        """记录语义去重步骤的模型用量。"""

        if not self.user_id or not self.library_id:
            return
        source_id = f"knowledge_graph_{self.library_id}_dedup_{document.document_id}"
        self.token_usage_service.record_llm_response_token_usage(
            user_id=self.user_id,
            session_id=None,
            response=response,
            node="knowledge_graph",
            event="entity_dedup",
            model_tier=SMALL_MODEL_TIER,
            source_id=source_id,
        )

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        """解析模型返回的 JSON 对象,兼容包裹在代码块中的输出。"""

        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                return {"entities": [], "relations": []}
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"entities": [], "relations": []}
        return payload if isinstance(payload, dict) else {"entities": [], "relations": []}

    @staticmethod
    def _is_valid_entity_name(value: str) -> bool:
        """过滤明显无效或过泛的实体名。"""

        if not value or len(value) > 80:
            return False
        if re.fullmatch(r"[\W_]+", value, flags=re.UNICODE):
            return False
        return value not in {"系统", "用户", "文件", "文档", "内容", "数据", "信息"}


from agent_service.services.knowledge_graph.rebuild import KnowledgeGraphRebuildMixin
from agent_service.services.knowledge_graph.extraction import KnowledgeGraphExtractionMixin
from agent_service.services.knowledge_graph.repository import KnowledgeGraphRepositoryMixin
from agent_service.services.knowledge_graph.deduplication import KnowledgeGraphDeduplicationMixin
from agent_service.services.knowledge_graph.query import KnowledgeGraphQueryMixin

class KnowledgeGraphService(KnowledgeGraphRebuildMixin, KnowledgeGraphExtractionMixin, KnowledgeGraphRepositoryMixin, KnowledgeGraphDeduplicationMixin, KnowledgeGraphQueryMixin):
    """知识库图谱抽取、清理和查询服务。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        engine: Engine | None = None,
        extractor: KnowledgeGraphExtractor | None = None,
        create_tables: bool = True,
    ) -> None:
        """初始化 SQLite 引擎并按需创建图谱表。"""

        self.config = config
        self.engine = engine or get_database_engine(config)
        self.extractor = extractor







































# ---------------------------------------------------------------------------
# 后台图谱抽取进度追踪
# ---------------------------------------------------------------------------

_graph_extraction_progress: dict[tuple[str, str], dict[str, Any]] = {}
_graph_progress_lock = threading.Lock()


class GraphExtractionCancelled(RuntimeError):
    """表示用户在章节批次安全检查点取消了图谱抽取。"""


def _batch_graph_sections(
    sections: list[StructuredKnowledgeSection],
    *,
    max_chars: int = DEFAULT_BUSINESS_LIMITS.graph_batch_max_chars,
    max_sections: int = DEFAULT_BUSINESS_LIMITS.graph_batch_max_sections,
) -> list[list[StructuredKnowledgeSection]]:
    """按字符数和章节数合并相邻短章节，长章节保持独立。"""

    batches: list[list[StructuredKnowledgeSection]] = []
    current: list[StructuredKnowledgeSection] = []
    current_chars = 0
    for section in sections:
        section_chars = len(section.content.strip())
        exceeds_limit = current and (
            len(current) >= max_sections or current_chars + section_chars > max_chars
        )
        if exceeds_limit:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += section_chars
    if current:
        batches.append(current)
    return batches


def _extract_graph_section_payloads(
    *,
    extractor: KnowledgeGraphExtractor,
    document: StructuredKnowledgeDocument,
    max_workers: int,
    cancel_event: threading.Event | None,
    on_progress: Callable[[int, int, int, int], None],
) -> dict[str, dict[str, Any]]:
    """并发抽取章节批次，并以单调完成计数报告前端进度。"""

    limits = getattr(getattr(extractor, "config", None), "limits", DEFAULT_BUSINESS_LIMITS)
    if hasattr(extractor, "context_budget"):
        section_token_limit = extractor.context_budget().max_single_block_tokens
        section_model_name = extractor._value("small_model_name") or extractor._value("model_name")
    else:
        section_token_limit = limits.graph_batch_max_chars
        section_model_name = None
    expanded_sections: list[StructuredKnowledgeSection] = []
    original_section_by_chunk: dict[str, str] = {}
    for section in document.sections:
        chunks = _split_graph_section_by_tokens(
            section,
            token_limit=section_token_limit,
            model_name=section_model_name,
        )
        expanded_sections.extend(chunks)
        original_section_by_chunk.update({chunk.section_id: section.section_id for chunk in chunks})
    batches = _batch_graph_sections(
        expanded_sections,
        max_chars=limits.graph_batch_max_chars,
        max_sections=limits.graph_batch_max_sections,
    )
    if not batches:
        return {}
    payloads: dict[str, dict[str, Any]] = {}
    completed_sections = 0
    completed_batches = 0
    worker_count = max(1, min(max_workers, len(batches)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="graph-extract") as executor:
        futures = {
            executor.submit(extractor.extract_batch, document=document, sections=batch): batch
            for batch in batches
        }
        for future in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                for pending in futures:
                    pending.cancel()
                raise GraphExtractionCancelled("图谱抽取已取消")
            batch = futures[future]
            for chunk_id, chunk_payload in future.result().items():
                original_id = original_section_by_chunk.get(chunk_id, chunk_id)
                aggregate = payloads.setdefault(original_id, {"entities": [], "relations": []})
                aggregate["entities"].extend(chunk_payload.get("entities", []))
                aggregate["relations"].extend(chunk_payload.get("relations", []))
                chunk_pending = chunk_payload.get("_pending_candidates", {})
                if chunk_pending.get("entities") or chunk_pending.get("relations"):
                    pending = aggregate.setdefault("_pending_candidates", {"entities": [], "relations": []})
                    pending["entities"].extend(chunk_pending.get("entities", []))
                    pending["relations"].extend(chunk_pending.get("relations", []))
                    evidence = str(chunk_pending.get("evidence_context") or "").strip()
                    if evidence:
                        prior = str(pending.get("evidence_context") or "").strip()
                        pending["evidence_context"] = "\n".join(item for item in (prior, evidence) if item)
            completed_sections += len(batch)
            completed_batches += 1
            on_progress(completed_sections, len(expanded_sections), completed_batches, len(batches))
    return payloads


def _split_graph_section_by_tokens(
    section: StructuredKnowledgeSection,
    *,
    token_limit: int,
    model_name: str | None,
) -> list[StructuredKnowledgeSection]:
    """按小模型预算完整切分长章节，不静默丢弃任意 token。"""

    try:
        encoding = tiktoken.encoding_for_model(model_name) if model_name else tiktoken.get_encoding("o200k_base")
    except KeyError:
        encoding = tiktoken.get_encoding("o200k_base")
    tokens = encoding.encode(section.content)
    safe_limit = max(int(token_limit), 1)
    if len(tokens) <= safe_limit:
        return [section]
    chunks: list[StructuredKnowledgeSection] = []
    char_offset = section.start_char
    for index, start in enumerate(range(0, len(tokens), safe_limit)):
        content = encoding.decode(tokens[start:start + safe_limit])
        chunk_start = char_offset
        char_offset += len(content)
        chunks.append(StructuredKnowledgeSection(
            section_id=f"{section.section_id}::chunk:{index}",
            heading=section.heading,
            title_path=list(section.title_path),
            content=content,
            start_char=chunk_start,
            end_char=char_offset,
        ))
    return chunks


def get_graph_extraction_progress(user_id: str, library_id: str) -> dict[str, Any]:
    """返回给定用户/知识库的图谱抽取进度。"""
    with _graph_progress_lock:
        state = _graph_extraction_progress.get((user_id, library_id))
        if state is None:
            return {"status": "idle", "total": 0, "current": 0, "message": ""}
        return dict(state)


def _update_graph_progress(
    user_id: str,
    library_id: str,
    *,
    status: str,
    total: int = 0,
    current: int = 0,
    message: str = "",
    result_json: str = "",
    docs: list[dict] | None = None,
) -> None:
    """线程安全地更新进度状态。"""
    with _graph_progress_lock:
        entry: dict[str, Any] = {
            "status": status,
            "total": total,
            "current": current,
            "message": message,
            "result": result_json,
        }
        if docs is not None:
            entry["docs"] = docs
        _graph_extraction_progress[(user_id, library_id)] = entry


# ---------------------------------------------------------------------------
# 全库去重进度追踪
# ---------------------------------------------------------------------------

_dedup_progress: dict[tuple[str, str], dict[str, Any]] = {}
_dedup_progress_lock = threading.Lock()


def get_dedup_progress(user_id: str, library_id: str) -> dict[str, Any]:
    """返回给定用户/知识库的全库去重进度。"""
    with _dedup_progress_lock:
        state = _dedup_progress.get((user_id, library_id))
        if state is None:
            return {"status": "idle", "total": 0, "current": 0, "message": ""}
        return dict(state)


def _set_dedup_progress(
    user_id: str,
    library_id: str,
    status: str,
    total: int = 0,
    current: int = 0,
    message: str = "",
    merged_count: int = 0,
) -> None:
    """更新全库去重进度。"""
    with _dedup_progress_lock:
        _dedup_progress[(user_id, library_id)] = {
            "status": status,
            "total": total,
            "current": current,
            "message": message,
            "merged_count": merged_count,
        }


def _build_llm_config(
    config: AgentConfig,
    user_llm_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 config 构造抽取器可用的 llm_config 字典。

    优先级: user_llm_config（用户设置页）> AgentConfig（env/默认值）。
    当小模型未配置时，整体降级使用主模型配置（model_name + key + base_url 一起切换），
    避免将主模型的 key 发送到小模型默认端点，或缺少 small_model_name 导致调度器无法构造模型。
    """
    has_user_config = bool(user_llm_config)
    source = user_llm_config or {}
    base = {
        "model_name": None,
        "api_key": None,
        "base_url": None,
        "small_model_name": None,
        "small_api_key": None,
        "small_base_url": None,
        "small_model_context_window_tokens": 0,
        "small_model_max_output_tokens": 0,
        "model_context_window_tokens": 0,
        "model_max_output_tokens": 0,
    }
    if has_user_config:
        for key in base:
            val = source.get(key)
            if key.endswith("_tokens"):
                base[key] = int(val or 0)
            elif val and isinstance(val, str) and val.strip():
                base[key] = val.strip()
    else:
        base = {
            "model_name": config.model.model_name.strip() or None,
            "api_key": config.model.api_key.strip() or None,
            "base_url": config.model.base_url.strip() or None,
            "small_model_name": config.model.small_model_name.strip() or None,
            "small_api_key": config.model.small_model_api_key.strip() or None,
            "small_base_url": config.model.small_model_base_url.strip() or None,
            "small_model_context_window_tokens": config.model.small_model_context_window_tokens,
            "small_model_max_output_tokens": config.model.small_model_max_output_tokens,
            "model_context_window_tokens": config.model.model_context_window_tokens,
            "model_max_output_tokens": config.model.model_max_output_tokens,
        }

    small_model_name = base.get("small_model_name")
    if not small_model_name:
        small_model_name = base.get("model_name")
        small_key = base.get("api_key")
        small_url = base.get("base_url")
    else:
        configured_small_url = base.get("small_base_url")
        primary_url = base.get("base_url")
        small_url = configured_small_url or primary_url
        small_key = base.get("small_api_key")
        if not small_key and small_url == primary_url:
            small_key = base.get("api_key")
    return {
        "model_name": base.get("model_name"),
        "api_key": base.get("api_key"),
        "base_url": base.get("base_url"),
        "small_model_name": small_model_name,
        "small_api_key": small_key,
        "small_base_url": small_url,
        "small_model_context_window_tokens": (
            base.get("small_model_context_window_tokens", 0)
            or base.get("model_context_window_tokens", 0)
        ),
        "small_model_max_output_tokens": (
            base.get("small_model_max_output_tokens", 0)
            or base.get("model_max_output_tokens", 0)
        ),
    }


def _run_graph_extraction(
    *,
    config: AgentConfig,
    user_id: str,
    library_id: str,
    frontmatter_dir: Path,
    user_llm_config: dict[str, Any] | None = None,
    target_source_path: Path | None = None,
    target_is_dir: bool = False,
    force: bool = False,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> None:
    """在后台线程中执行图谱抽取；可把逐文件进度交给外层队列聚合。"""

    def emit_progress(**payload: Any) -> None:
        """向队列聚合器报告进度；独立调用时保留原全局进度行为。"""

        if progress_callback is not None:
            progress_callback(**payload)
            return
        _update_graph_progress(user_id, library_id, **payload)

    try:
        llm_config = _build_llm_config(config, user_llm_config=user_llm_config)
        svc = KnowledgeGraphService(config=config)
        paths = sorted(path for path in frontmatter_dir.rglob("*.json") if path.is_file()) if frontmatter_dir.exists() else []
        if target_source_path is not None:
            paths = [
                path
                for path in paths
                if _frontmatter_path_matches_target(
                    path=path,
                    target_source_path=target_source_path,
                    target_is_dir=target_is_dir,
                )
            ]
        total = len(paths)
        print(f"\n{'='*60}")
        print(f"  知识图谱抽取开始 | 共 {total} 个文档")
        print(f"  frontmatter_dir={frontmatter_dir}")
        if target_source_path is not None:
            print(f"  target_source_path={target_source_path}")
        print(f"{'='*60}\n")

        docs: list[dict] = []
        pending_paths: list[Path] = []
        document_ids_seen: set[str] = set()
        need_extract = 0
        skipped_count = 0
        for path in paths:
            if cancel_event is not None and cancel_event.is_set():
                emit_progress(status="cancelled", message="图谱抽取已取消")
                return
            doc_data = KnowledgeGraphService._load_document(path)
            document_ids_seen.add(doc_data.document_id)
            total_sections = len(doc_data.sections) if doc_data.sections else 0
            is_current = svc._is_document_current(
                user_id=user_id,
                library_id=library_id,
                document_id=doc_data.document_id,
                source_hash=doc_data.ingestion_hash,
            )
            if is_current and not force:
                skipped_count += 1
                print(f"  SKIP {doc_data.title or path.name} [hash not changed]")
            else:
                docs.append(_graph_progress_doc_entry(
                    document=doc_data,
                    frontmatter_path=path,
                    frontmatter_dir=frontmatter_dir,
                    status="pending",
                    progress=0,
                    total_sections=total_sections,
                ))
                pending_paths.append(path)
                need_extract += 1

        emit_progress(
            status="running",
            total=need_extract,
            current=0,
            message=f"需抽取 {need_extract}/{total} 个文档",
            docs=docs,
        )

        svc.sync_document_nodes_frontmatter_dir(
            user_id=user_id,
            library_id=library_id,
            frontmatter_dir=frontmatter_dir,
        )
        print(f"  [同步] 文档节点同步完成, 开始远程小模型抽取\n")

        remote_extractor = (
            LLMKnowledgeGraphExtractor(
                config=config,
                llm_config=llm_config,
                user_id=user_id,
                library_id=library_id,
            )
            if llm_config.get("small_model_name") and llm_config.get("small_api_key")
            else None
        )
        from agent_service.services.knowledge_graph.local_extractor import RemoteKnowledgeGraphExtractor

        extractor = RemoteKnowledgeGraphExtractor(
            config=config,
            remote_extractor=remote_extractor,
        )
        circuit_breaker_hit = False
        completed_count = 0
        failed_count = 0
        total_entities = 0
        total_relations = 0
        doc_index = 0

        for di, doc_entry in enumerate(docs):
            if cancel_event is not None and cancel_event.is_set():
                emit_progress(status="cancelled", message="图谱抽取已取消", docs=docs)
                return
            if circuit_breaker_hit:
                print(f"\n  [BREAKER] circuit breaker hit, stopping")
                break
            path = pending_paths[di]
            document = KnowledgeGraphService._load_document(path)

            _set_graph_doc_progress(
                docs[di],
                status="processing",
                progress=2,
                stage="preparing",
                stage_label="正在准备文档",
            )
            emit_progress(
                status="running",
                total=need_extract,
                current=doc_index,
                message=f"处理文档 {doc_index + 1}/{need_extract}: {document.title}",
                docs=docs,
            )

            title_display = document.title or path.name
            print(f"  [{di+1:3d}/{total}] --> {title_display[:60]:60s} "
                  f"(sections: {len(document.sections)})")

            try:
                entities_by_key: dict[tuple[str, str], EntityCandidate] = {}
                relations: list[tuple[RelationCandidate, StructuredKnowledgeSection]] = []
                section_total = len(document.sections)
                section_payloads: dict[str, dict[str, Any]] = {}
                section_caches: list[KnowledgeGraphSectionCache] = []
                has_pending = False
                if section_total:
                    _set_graph_doc_progress(
                        docs[di],
                        status="processing",
                        progress=5,
                        stage="extract_sections",
                        stage_label="远程候选抽取",
                        stage_current=0,
                        stage_total=section_total,
                    )
                    emit_progress(
                        status="running",
                        total=need_extract,
                        current=doc_index,
                        message=f"准备并发抽取文档 {doc_index + 1}/{need_extract} 的 {section_total} 个章节",
                        docs=docs,
                    )

                def report_section_progress(
                    completed_sections: int,
                    total_sections: int,
                    completed_batches: int,
                    total_batches: int,
                ) -> None:
                    """把乱序完成的并发批次汇总为单调章节进度。"""

                    _set_graph_doc_progress(
                        docs[di],
                        status="processing",
                        progress=5 + int(completed_sections / total_sections * 70),
                        stage="extract_sections",
                        stage_label="远程候选抽取",
                        stage_current=completed_sections,
                        stage_total=total_sections,
                        message=f"已完成 {completed_batches}/{total_batches} 批请求",
                    )
                    emit_progress(
                        status="running",
                        total=need_extract,
                        current=doc_index,
                        message=(
                            f"文档 {doc_index + 1}/{need_extract} 已抽取 "
                            f"{completed_sections}/{total_sections} 个章节，"
                            f"完成 {completed_batches}/{total_batches} 批请求"
                        ),
                        docs=docs,
                    )

                try:
                    from agent_service.services.knowledge_graph.cache import extract_cached_graph_section_payloads

                    section_payloads, section_caches, has_pending = extract_cached_graph_section_payloads(
                        service=svc,
                        extractor=extractor,
                        user_id=user_id,
                        library_id=library_id,
                        document=document,
                        max_workers=config.task_schedule.background_fact_worker_count,
                        cancel_event=cancel_event,
                        on_progress=report_section_progress,
                        force=force,
                    )
                except GraphExtractionCancelled:
                    emit_progress(
                        status="cancelled",
                        message="图谱抽取已取消",
                        docs=docs,
                    )
                    return

                for si, section in enumerate(document.sections):
                    section_title = section.title_path[-1] if section.title_path else f"section_{si}"
                    print(f"    |-- section {si+1}/{section_total}: {section_title[:50]}", end="")
                    payload = section_payloads.get(section.section_id, {"entities": [], "relations": []})
                    section_entities = svc._sanitize_entities(payload.get("entities"))
                    for entity in section_entities:
                        entities_by_key[(svc._normalize_label(entity.name), entity.entity_type)] = entity
                    section_entity_names = {entity.name for entity in section_entities}
                    section_relations = svc._sanitize_relations(
                        payload.get("relations"),
                        section_text=section.content,
                        allowed_entity_names=section_entity_names,
                    )
                    section_relations = svc._augment_explicit_text_relations(
                        section_text=section.content,
                        section_entities=section_entities,
                        section_relations=section_relations,
                    )
                    relations.extend(
                        (relation, section)
                        for relation in section_relations
                    )
                    print(f" entities={len(section_entities)} relations={len(section_relations)}")

                # 本地规范名称和显式别名去重，不把整份实体列表发送到联网模型。
                if entities_by_key:
                    _set_graph_doc_progress(
                        docs[di],
                        status="processing",
                        progress=80,
                        stage="deduplicate_document",
                        stage_label="文档内实体去重",
                    )
                    emit_progress(
                        status="running",
                        total=need_extract,
                        current=doc_index,
                        message=f"正在进行文档内实体去重: {document.title}",
                        docs=docs,
                    )
                    entity_list = list(entities_by_key.values())
                    merged_entities, name_mapping, document_dedup_pending = svc._deduplicate_document_entities_layered(
                        user_id=user_id,
                        library_id=library_id,
                        entities=entity_list,
                        extractor=extractor,
                        document=document,
                    )
                    has_pending = has_pending or document_dedup_pending
                    if name_mapping:
                        entities_by_key = {
                            (svc._normalize_label(e.name), e.entity_type): e
                            for e in merged_entities
                        }
                        remapped: list[tuple[RelationCandidate, StructuredKnowledgeSection]] = []
                        for relation, section in relations:
                            new_source = name_mapping.get(relation.source, relation.source)
                            new_target = name_mapping.get(relation.target, relation.target)
                            if new_source == new_target:
                                continue
                            relation.source = new_source
                            relation.target = new_target
                            remapped.append((relation, section))
                        relations = remapped

                # 库级增量去重: 本地 Embedding 明确分流，仅灰区联网裁决。
                if entities_by_key:
                    _set_graph_doc_progress(
                        docs[di],
                        status="processing",
                        progress=88,
                        stage="deduplicate_library",
                        stage_label="知识库实体去重",
                    )
                    emit_progress(
                        status="running",
                        total=need_extract,
                        current=doc_index,
                        message=f"正在进行知识库实体去重: {document.title}",
                        docs=docs,
                    )
                    entity_list = list(entities_by_key.values())
                    cross_mapping, dedup_pending = svc._deduplicate_entities_incremental(
                        user_id=user_id, library_id=library_id,
                        new_entities=entity_list, extractor=extractor, document=document,
                        return_pending_status=True,
                    )
                    has_pending = has_pending or dedup_pending
                    if cross_mapping:
                        new_keyed: dict[tuple[str, str], EntityCandidate] = {}
                        for entity in entity_list:
                            new_name = cross_mapping.get(entity.name, entity.name)
                            if svc._normalize_label(new_name) != svc._normalize_label(entity.name):
                                entity.name = new_name
                            key = (svc._normalize_label(entity.name), entity.entity_type)
                            if key not in new_keyed or entity.confidence > new_keyed[key].confidence:
                                new_keyed[key] = entity
                        entities_by_key = new_keyed
                        remapped2: list[tuple[RelationCandidate, StructuredKnowledgeSection]] = []
                        for relation, section in relations:
                            new_src = cross_mapping.get(relation.source, relation.source)
                            new_tgt = cross_mapping.get(relation.target, relation.target)
                            if new_src == new_tgt:
                                continue
                            relation.source = new_src
                            relation.target = new_tgt
                            remapped2.append((relation, section))
                        relations = remapped2

                _set_graph_doc_progress(
                    docs[di],
                    status="processing",
                    progress=96,
                    stage="write_graph",
                    stage_label="正在写入知识图谱",
                )
                emit_progress(
                    status="running",
                    total=need_extract,
                    current=doc_index,
                    message=f"正在写入知识图谱: {document.title}",
                    docs=docs,
                )
                persistence_status = "partial" if has_pending else ("completed" if entities_by_key or relations else "skipped")
                persistence_message = "gray candidates pending retry" if has_pending else ("" if entities_by_key or relations else "no valid graph candidates")
                written_entities, written_relations = svc.replace_document_graph_atomic(
                    user_id=user_id,
                    library_id=library_id,
                    document=document,
                    entities=list(entities_by_key.values()),
                    relations=relations,
                    section_caches=section_caches,
                    status=persistence_status,
                    message=persistence_message,
                )
                if written_entities or written_relations:
                    completed_count += 1
                    total_entities += written_entities
                    total_relations += written_relations
                    _set_graph_doc_progress(
                        docs[di], status="done", progress=100,
                        stage="completed", stage_label="抽取完成",
                    )
                    print(f"    ++ DONE: {written_entities} entities, {written_relations} relations")
                else:
                    skipped_count += 1
                    _set_graph_doc_progress(
                        docs[di], status="skipped", progress=100,
                        stage="skipped", stage_label="没有可写入的图谱内容",
                    )
                    print(f"    -- SKIP: no valid entities/relations")

            except Exception as exc:
                exc_msg = str(exc)
                failed_count += 1
                _set_graph_doc_progress(
                    docs[di], status="failed", progress=100,
                    stage="failed", stage_label="图谱抽取失败",
                    message=exc_msg[:1000],
                )
                logger.warning("知识图谱抽取失败 | document=%s error=%s", document.document_id, exc_msg)
                svc._write_status(
                    user_id=user_id,
                    library_id=library_id,
                    document=document,
                    status="failed",
                    message=exc_msg[:1000],
                    entity_count=0,
                    relation_count=0,
                )
                print(f"    !! FAIL: {exc_msg[:120]}")
                if "熔断" in exc_msg or "circuit breaker" in exc_msg.lower() or "MISSING API KEY" in exc_msg or "insufficient balance" in exc_msg.lower() or "exceeded_current_quota" in exc_msg or "suspended" in exc_msg.lower():
                    circuit_breaker_hit = True

            doc_index += 1
            emit_progress(
                status="running",
                total=need_extract,
                current=doc_index,
                message=f"处理完成 {doc_index}/{need_extract}: {document.title}",
                docs=docs,
            )

        if target_source_path is None:
            svc.delete_graph_except_documents(
                user_id=user_id,
                library_id=library_id,
                keep_document_ids=document_ids_seen,
            )

        print(f"\n{'='*60}")
        print(f"  图谱抽取完成!")
        print(f"  |-- total docs: {total}")
        print(f"  |-- completed:  {completed_count}")
        print(f"  |-- failed:     {failed_count}")
        print(f"  |-- skipped:    {skipped_count}")
        print(f"  |-- entities:   {total_entities}")
        print(f"  |-- relations:  {total_relations}")
        if circuit_breaker_hit:
            print(f"  !! some docs skipped due to circuit breaker")
        print(f"{'='*60}\n")

        if failed_count > 0 and completed_count == 0:
            emit_progress(
                status="failed",
                total=need_extract,
                current=doc_index,
                message=f"图谱抽取失败：{failed_count} 个文档抽取失败，请检查模型配置或 API Key。",
                docs=docs,
            )
        elif circuit_breaker_hit:
            emit_progress(
                status="completed",
                total=need_extract,
                current=need_extract,
                message="图谱抽取完成（部分文档因模型调用限流或熔断已跳过）",
                docs=docs,
            )
        else:
            emit_progress(
                status="completed",
                total=need_extract,
                current=need_extract,
                message="图谱抽取完成",
                docs=docs,
            )
    except Exception as exc:
        logger.exception("图谱抽取整体失败")
        print(f"\n  !! Graph extraction failed: {exc}\n")
        emit_progress(
            status="failed",
            message=f"抽取失败: {exc}",
        )


def _frontmatter_path_matches_target(*, path: Path, target_source_path: Path, target_is_dir: bool) -> bool:
    """判断 frontmatter 文档的原始源文件是否落在右键指定的文件/文件夹范围内。"""

    try:
        document = KnowledgeGraphService._load_document(path)
    except Exception:
        return False
    raw_source_path = document.source_path or document.source_uri
    if not raw_source_path:
        return False
    try:
        source_path = Path(raw_source_path).resolve(strict=False)
    except (OSError, ValueError):
        return False
    target = target_source_path.resolve(strict=False)
    source_key = _normalize_graph_scope_path(source_path)
    target_key = _normalize_graph_scope_path(target)
    if not target_is_dir:
        return source_key == target_key
    return source_key == target_key or source_key.startswith(f"{target_key}\\")


def _graph_progress_doc_entry(
    *,
    document: StructuredKnowledgeDocument,
    frontmatter_path: Path,
    frontmatter_dir: Path,
    status: str,
    progress: int,
    total_sections: int,
) -> dict[str, Any]:
    """Build one graph progress doc row using the source-file relative path."""

    return {
        "path": _graph_progress_relative_path(
            document=document,
            frontmatter_path=frontmatter_path,
            frontmatter_dir=frontmatter_dir,
        ),
        "name": document.title or Path(document.source_path or frontmatter_path.stem).stem,
        "status": status,
        "progress": progress,
        "total_sections": total_sections,
        "stage": "waiting",
        "stage_label": "等待图谱抽取",
        "stage_current": 0,
        "stage_total": total_sections,
        "message": "",
    }


def _set_graph_doc_progress(
    entry: dict[str, Any],
    *,
    status: str,
    progress: int,
    stage: str,
    stage_label: str,
    stage_current: int = 0,
    stage_total: int = 0,
    message: str = "",
) -> None:
    """Update one graph document row with its real pipeline stage and counters."""

    entry.update({
        "status": status,
        "progress": max(0, min(100, progress)),
        "stage": stage,
        "stage_label": stage_label,
        "stage_current": stage_current,
        "stage_total": stage_total,
        "message": message,
    })


def _graph_progress_relative_path(
    *,
    document: StructuredKnowledgeDocument,
    frontmatter_path: Path,
    frontmatter_dir: Path,
) -> str:
    """Return the knowledge-tree path for one frontmatter document."""

    relative_path = str(document.metadata.get("relative_path") or "").replace("\\", "/").strip("/")
    if relative_path:
        return relative_path
    try:
        return frontmatter_path.relative_to(frontmatter_dir).as_posix()
    except ValueError:
        return frontmatter_path.name


def _normalize_graph_scope_path(path: Path) -> str:
    """归一化 Windows 路径用于图谱右键抽取范围比较。"""

    return str(path).replace("/", "\\").rstrip("\\").lower()
