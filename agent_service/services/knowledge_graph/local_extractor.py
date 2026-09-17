"""远程小模型与确定性规则组合的知识图谱候选抽取器。

完整章节交给用户配置的远程小模型抽取；显式中英文谓词规则始终补充结果，并在
远程模型未配置或调用失败时作为确定性兜底。模块保留原文件路径以避免扩大迁移面。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "remote-small-model-v1"
RULE_VERSION = "explicit-relations-v1"
RESULT_VERSION = "graph-payload-v2"

_RELATION_LABELS = {
    "depends on": "depends_on",
    "uses": "uses",
    "calls": "calls",
    "creates": "creates",
    "contains": "contains",
    "defines": "defines",
    "produces": "produces",
    "consumes": "consumes",
    "configures": "configures",
    "依赖于": "depends_on",
    "依赖": "depends_on",
    "使用": "uses",
    "调用": "calls",
    "创建": "creates",
    "包含": "contains",
    "定义": "defines",
    "生成": "produces",
    "消费": "consumes",
    "配置": "configures",
}


class RemoteKnowledgeGraphExtractor:
    """用远程小模型扫描全文，并用显式关系规则提供无网络兜底。"""

    extractor_version = EXTRACTOR_VERSION
    rule_version = RULE_VERSION
    result_version = RESULT_VERSION

    def __init__(self, *, config: Any, remote_extractor: Any | None = None) -> None:
        """保存远程抽取器；同一实例也供现有分层去重流程做远程灰区裁决。"""

        self.config = config
        self.remote_extractor = remote_extractor
        self.remote_adjudicator = remote_extractor

    def extract(self, *, document: Any, section: Any) -> dict[str, Any]:
        """抽取单章节；远程失败时返回显式规则结果而不破坏旧图谱。"""

        remote_payload = self._empty_payload()
        if self.remote_extractor is not None and str(section.content or "").strip():
            try:
                remote_payload = self.remote_extractor.extract(document=document, section=section)
            except Exception as exc:  # noqa: BLE001 - deterministic rules remain available
                logger.warning(
                    "远程图谱抽取失败，降级为确定性规则 | document=%s section=%s error=%s",
                    getattr(document, "document_id", ""),
                    getattr(section, "section_id", ""),
                    exc,
                )
        return self._finalize_payload(remote_payload, str(section.content or ""))

    def extract_batch(self, *, document: Any, sections: list[Any]) -> dict[str, dict[str, Any]]:
        """批量抽取短章节；一次远程批次失败时逐章节返回确定性规则结果。"""

        remote_payloads: dict[str, dict[str, Any]] = {}
        if self.remote_extractor is not None and sections:
            try:
                remote_payloads = self.remote_extractor.extract_batch(
                    document=document,
                    sections=sections,
                )
            except Exception as exc:  # noqa: BLE001 - one failed batch must not lose rule results
                logger.warning(
                    "远程图谱批量抽取失败，降级为确定性规则 | document=%s error=%s",
                    getattr(document, "document_id", ""),
                    exc,
                )
        return {
            section.section_id: self._finalize_payload(
                remote_payloads.get(section.section_id, self._empty_payload()),
                str(section.content or ""),
            )
            for section in sections
        }

    @classmethod
    def _finalize_payload(cls, remote_payload: dict[str, Any], content: str) -> dict[str, Any]:
        """合并远程候选与高置信显式规则，并声明本版本没有待重试候选。"""

        result = cls._merge_payloads(remote_payload, cls._extract_explicit_relations(content))
        result["_pending_candidates"] = cls._empty_payload()
        return result

    @classmethod
    def _extract_explicit_relations(cls, content: str) -> dict[str, Any]:
        """从明确的中英文谓词句中补充无需模型裁决的高置信候选。"""

        payload = cls._empty_payload()
        entity_names: set[str] = set()
        english_predicates = "|".join(
            re.escape(item) for item in _RELATION_LABELS if item.isascii()
        )
        english_pattern = re.compile(
            rf"(?P<source>[A-Za-z_][\w.:-]{{0,79}})\s+(?P<predicate>{english_predicates})\s+"
            rf"(?P<target>[A-Za-z_][\w.:-]{{0,79}})",
            flags=re.IGNORECASE,
        )
        chinese_predicates = "|".join(
            re.escape(item)
            for item in sorted(
                (item for item in _RELATION_LABELS if not item.isascii()),
                key=len,
                reverse=True,
            )
        )
        chinese_pattern = re.compile(
            rf"(?P<source>[A-Za-z0-9_\u4e00-\u9fff.:-]{{1,40}}?)\s*"
            rf"(?P<predicate>{chinese_predicates})\s*"
            rf"(?P<target>[A-Za-z0-9_\u4e00-\u9fff.:-]{{1,40}})(?=$|[，。；、!?！？\s])"
        )
        for pattern in (english_pattern, chinese_pattern):
            for match in pattern.finditer(content):
                source = match.group("source").strip(" \t.,;:，。；：!?！？")
                target = match.group("target").strip(" \t.,;:，。；：!?！？")
                predicate = match.group("predicate").lower()
                if source == target:
                    continue
                entity_names.update((source, target))
                payload["relations"].append({
                    "source": source,
                    "target": target,
                    "type": _RELATION_LABELS[predicate],
                    "evidence": match.group(0).strip(),
                    "confidence": 0.95,
                })
        payload["entities"] = [
            {
                "name": name,
                "type": cls._infer_entity_type(name),
                "aliases": [],
                "confidence": 0.95,
            }
            for name in sorted(entity_names)
        ]
        return payload

    @staticmethod
    def _infer_entity_type(name: str) -> str:
        """根据稳定的代码标识符后缀提供保守实体类型，其他名称归为 concept。"""

        lowered = name.lower()
        if lowered.endswith("service"):
            return "class"
        if lowered.endswith((".py", ".ts", ".vue", ".md")):
            return "file"
        if "." in name and not lowered.endswith("."):
            return "module"
        return "concept"

    @classmethod
    def _merge_payloads(cls, *payloads: dict[str, Any]) -> dict[str, Any]:
        """按实体标识和关系证据合并多个候选来源。"""

        merged = cls._empty_payload()
        seen_entities: set[tuple[str, str]] = set()
        seen_relations: set[tuple[str, str, str, str]] = set()
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for item in payload.get("entities", []):
                if not isinstance(item, dict):
                    continue
                key = (
                    str(item.get("name") or "").strip().casefold(),
                    str(item.get("type") or "other"),
                )
                if not key[0] or key in seen_entities:
                    continue
                seen_entities.add(key)
                merged["entities"].append(item)
            for item in payload.get("relations", []):
                if not isinstance(item, dict):
                    continue
                key = tuple(
                    str(item.get(field) or "").strip().casefold()
                    for field in ("source", "target", "type", "evidence")
                )
                if not key[0] or not key[1] or key in seen_relations:
                    continue
                seen_relations.add(key)
                merged["relations"].append(item)
        return merged

    @staticmethod
    def _empty_payload() -> dict[str, list[Any]]:
        """返回互不共享列表的空候选结构。"""

        return {"entities": [], "relations": []}
