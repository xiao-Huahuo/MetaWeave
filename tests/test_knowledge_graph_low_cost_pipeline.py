"""知识图谱远程抽取与确定性规则兜底回归测试。

本文件验证文档与章节增量、远程全文抽取、规则兜底、失败保留和正式缓存模型。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from tests.db_test_utils import create_test_engine

from agent_service.core.agent_config import AgentConfig
from agent_service.models.knowledge_graph import KnowledgeGraphNode, KnowledgeGraphSectionCache
from agent_service.services.knowledge_graph import EntityCandidate, KnowledgeGraphService, _run_graph_extraction
from agent_service.services.knowledge_graph.local_extractor import RemoteKnowledgeGraphExtractor
from agent_service.services.memory.rag.frontmatter_document import (
    StructuredKnowledgeDocument,
    StructuredKnowledgeSection,
)


def _config(tmp_path: Path) -> AgentConfig:
    """构造不会下载真实模型的测试配置。"""

    return AgentConfig.load_config(
        {
            "model": {"model_name": "remote-model", "api_key": "remote-key"},
            "storage": {
                "project_root": str(tmp_path),
                "base_data_dir": str(tmp_path / "runtime"),
            },
        },
        load_env=False,
        load_dotenv=False,
        ensure_models=False,
    )


def _section(section_id: str, content: str) -> StructuredKnowledgeSection:
    """构造具有稳定 ID 的章节。"""

    return StructuredKnowledgeSection(
        section_id=section_id,
        heading=section_id,
        title_path=[section_id],
        content=content,
        start_char=0,
        end_char=len(content),
    )


def _document(*, projection_hash: str, sections: list[StructuredKnowledgeSection]) -> StructuredKnowledgeDocument:
    """构造 source_hash 与 ingestion_hash 不同的新版文档。"""

    return StructuredKnowledgeDocument(
        document_id="doc-low-cost",
        source_type="markdown",
        source_path="D:/Knowledge/low-cost.md",
        source_uri="D:/Knowledge/low-cost.md",
        source_hash="raw-source-hash",
        projection_hash=projection_hash,
        title="low cost",
        summary="",
        tags=[],
        authority=0.7,
        valid_from=None,
        valid_until=None,
        metadata={"relative_path": "low-cost.md"},
        sections=sections,
    )


class CountingExtractor:
    """记录真正执行抽取的章节，返回可直接接受的本地候选。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(self, *, document: StructuredKnowledgeDocument, section: StructuredKnowledgeSection) -> dict[str, Any]:
        """为每个章节返回一个稳定实体。"""

        del document
        self.calls.append(section.section_id)
        return {
            "entities": [{"name": f"Entity-{section.section_id}", "type": "concept", "confidence": 0.95}],
            "relations": [],
        }


class FailingExtractor:
    """模拟抽取失败。"""

    def extract(self, *, document: StructuredKnowledgeDocument, section: StructuredKnowledgeSection) -> dict[str, Any]:
        """始终抛出异常以验证旧图保护。"""

        del document, section
        raise RuntimeError("extraction failed")


class RecordingRemoteExtractor:
    """记录远程模型收到的完整章节，并返回稳定的结构化候选。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    def extract(self, *, document: Any, section: Any) -> dict[str, Any]:
        """模拟一次远程全文抽取。"""

        del document
        self.prompts.append(str(section.content))
        if self.fail:
            raise RuntimeError("remote unavailable")
        return {
            "entities": [
                {"name": "Alpha", "type": "concept", "confidence": 0.95},
                {"name": "Beta", "type": "concept", "confidence": 0.95},
            ],
            "relations": [{
                "source": "Alpha",
                "target": "Beta",
                "type": "related_to",
                "evidence": "Alpha resembles Beta",
                "confidence": 0.65,
            }],
        }

    def deduplicate_entities(self, entities: list[Any], **_: Any) -> dict[str, Any]:
        """模拟文档内实体保持独立。"""

        if self.fail:
            raise RuntimeError("remote unavailable")
        return {"entities": entities, "name_mapping": {entity.name: entity.name for entity in entities}}


class RecordingDedupAdjudicator:
    """记录增量去重灰区调用并返回指定规范实体。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, list[tuple[str, float]]]] = []
        self.fail = fail

    def deduplicate_entities_incremental(self, **kwargs: Any) -> dict[str, str]:
        """只合并测试中的灰区实体。"""

        candidates = dict(kwargs["candidates"])
        self.calls.append(candidates)
        if self.fail:
            raise RuntimeError("dedup remote unavailable")
        return {"BetaGray": "Beta Existing"}


def test_background_rebuild_compares_the_same_ingestion_hash_it_persists(tmp_path: Path, monkeypatch: Any) -> None:
    """后台重建必须用 projection-aware ingestion_hash 判断文档是否已抽取。"""

    frontmatter_dir = tmp_path / "frontmatter"
    frontmatter_dir.mkdir()
    document = _document(projection_hash="projection-v1", sections=[])
    (frontmatter_dir / "doc.json").write_text(json.dumps(document.to_dict()), encoding="utf-8")
    captured: list[str] = []

    monkeypatch.setattr(
        KnowledgeGraphService,
        "_is_document_current",
        lambda self, **kwargs: captured.append(str(kwargs["source_hash"])) or True,
    )
    monkeypatch.setattr(KnowledgeGraphService, "sync_document_nodes_frontmatter_dir", lambda self, **kwargs: 1)

    _run_graph_extraction(
        config=_config(tmp_path),
        user_id="user",
        library_id="library",
        frontmatter_dir=frontmatter_dir,
    )

    assert captured == ["projection-v1"]


def test_only_changed_sections_are_extracted_and_cached(tmp_path: Path) -> None:
    """文档变化后必须复用未变化章节，只抽取变化章节。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    extractor = CountingExtractor()
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine, extractor=extractor)
    first = _document(
        projection_hash="projection-v1",
        sections=[_section("section-a", "Alpha"), _section("section-b", "Beta")],
    )
    changed = _document(
        projection_hash="projection-v2",
        sections=[_section("section-a", "Alpha"), _section("section-b", "Beta changed")],
    )

    service.extract_document(user_id="user", library_id="library", document=first)
    service.extract_document(user_id="user", library_id="library", document=changed)

    assert extractor.calls == ["section-a", "section-b", "section-b"]
    assert service.list_section_caches(
        user_id="user", library_id="library", document_id=first.document_id,
    ).keys() == {"section-a", "section-b"}


def test_failed_reextract_keeps_previous_graph(tmp_path: Path) -> None:
    """新抽取失败时不得先删除上一次成功图谱。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    first = _document(projection_hash="projection-v1", sections=[_section("section-a", "Alpha")])
    changed = _document(projection_hash="projection-v2", sections=[_section("section-a", "Alpha changed")])
    KnowledgeGraphService(config=_config(tmp_path), engine=engine, extractor=CountingExtractor()).extract_document(
        user_id="user", library_id="library", document=first,
    )

    result = KnowledgeGraphService(config=_config(tmp_path), engine=engine, extractor=FailingExtractor()).extract_document(
        user_id="user", library_id="library", document=changed,
    )
    graph = KnowledgeGraphService(config=_config(tmp_path), engine=engine).get_graph(
        user_id="user", library_id="library",
    )

    assert result.files_failed == 1
    assert any(node["label"] == "Entity-section-a" for node in graph["nodes"])


def test_atomic_replace_rolls_back_old_graph_when_write_fails(tmp_path: Path, monkeypatch: Any) -> None:
    """删除旧图后若新图写入失败，同一事务必须恢复旧图。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine, extractor=CountingExtractor())
    first = _document(projection_hash="projection-v1", sections=[_section("section-a", "Alpha")])
    service.extract_document(user_id="user", library_id="library", document=first)

    def fail_write(**_: Any) -> tuple[int, int]:
        """模拟事务已经删除旧行后发生写入异常。"""

        raise RuntimeError("database write failed")

    monkeypatch.setattr(service, "_write_graph_rows", fail_write)
    try:
        service.replace_document_graph_atomic(
            user_id="user",
            library_id="library",
            document=_document(projection_hash="projection-v2", sections=[]),
            entities=[],
            relations=[],
            section_caches=[],
            status="skipped",
            message="",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("replace_document_graph_atomic must propagate write failures")

    graph = KnowledgeGraphService(config=_config(tmp_path), engine=engine).get_graph(
        user_id="user", library_id="library",
    )
    assert any(node["label"] == "Entity-section-a" for node in graph["nodes"])


def test_remote_extractor_receives_full_section_and_merges_results(tmp_path: Path) -> None:
    """远程小模型必须收到完整章节，返回候选应直接进入清洗流水线。"""

    remote = RecordingRemoteExtractor()
    extractor = RemoteKnowledgeGraphExtractor(
        config=_config(tmp_path),
        remote_extractor=remote,
    )
    section = _section("section-a", "SECRET_PREFIX. Alpha resembles Beta. SECRET_SUFFIX.")

    payload = extractor.extract(document=_document(projection_hash="v1", sections=[section]), section=section)

    assert remote.prompts == [section.content]
    assert len(payload["entities"]) == 2
    assert len(payload["relations"]) == 1
    assert payload["_pending_candidates"] == {"entities": [], "relations": []}


def test_explicit_relation_rules_work_without_remote_model(tmp_path: Path) -> None:
    """远程模型未配置时，明确谓词关系仍应由确定性规则抽取。"""

    extractor = RemoteKnowledgeGraphExtractor(
        config=_config(tmp_path),
        remote_extractor=None,
    )
    section = _section("section-a", "Alpha uses Beta.")

    payload = extractor.extract(document=_document(projection_hash="v1", sections=[section]), section=section)

    assert {entity["name"] for entity in payload["entities"]} == {"Alpha", "Beta"}
    assert payload["relations"] == [{
        "source": "Alpha",
        "target": "Beta",
        "type": "uses",
        "evidence": "Alpha uses Beta.",
        "confidence": 0.95,
    }]


def test_remote_failure_falls_back_to_explicit_rules(tmp_path: Path) -> None:
    """远程全文抽取失败时必须保留确定性规则结果，且不产生旧灰区缓存。"""

    extractor = RemoteKnowledgeGraphExtractor(
        config=_config(tmp_path),
        remote_extractor=RecordingRemoteExtractor(fail=True),
    )
    section = _section("section-a", "Alpha uses Beta.")

    payload = extractor.extract(document=_document(projection_hash="v1", sections=[section]), section=section)

    assert len(payload["entities"]) == 2
    assert payload["relations"][0]["type"] == "uses"
    assert payload["_pending_candidates"] == {"entities": [], "relations": []}


def test_remote_extractor_versions_invalidate_legacy_section_cache() -> None:
    """远程全文抽取切换必须使用新的抽取与结果版本，使旧章节缓存失效。"""

    assert RemoteKnowledgeGraphExtractor.extractor_version == "remote-small-model-v1"
    assert RemoteKnowledgeGraphExtractor.result_version == "graph-payload-v2"


def test_incremental_dedup_uses_local_thresholds_and_caches_gray_decisions(tmp_path: Path, monkeypatch: Any) -> None:
    """高相似实体本地合并，灰区只联网一次并复用持久化判定。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine)
    adjudicator = RecordingDedupAdjudicator()
    extractor = SimpleNamespace(remote_adjudicator=adjudicator)
    entities = [
        SimpleNamespace(name="AlphaHigh", entity_type="concept"),
        SimpleNamespace(name="BetaGray", entity_type="concept"),
    ]
    monkeypatch.setattr(service, "_search_similar_entities", lambda **_: {
        "AlphaHigh": [("Alpha Existing", 0.96, "concept")],
        "BetaGray": [("Beta Existing", 0.80, "concept")],
    })
    document = _document(projection_hash="projection-v1", sections=[])

    first = service._deduplicate_entities_incremental(
        user_id="user", library_id="library", new_entities=entities, extractor=extractor, document=document,
    )
    second = service._deduplicate_entities_incremental(
        user_id="user", library_id="library", new_entities=entities, extractor=extractor, document=document,
    )

    assert first == {"AlphaHigh": "Alpha Existing", "BetaGray": "Beta Existing"}
    assert second == first
    assert adjudicator.calls == [{"BetaGray": [("Beta Existing", 0.80)]}]


def test_document_level_embedding_merges_clear_cross_section_aliases_locally(tmp_path: Path, monkeypatch: Any) -> None:
    """同文档跨章节的高相似同类型实体必须在本地合并，不调用联网裁决。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine)

    class FakeEmbeddingService:
        """为两个测试实体返回近乎一致的向量。"""

        def __init__(self, **_: Any) -> None:
            pass

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, index * 0.001] for index, _text in enumerate(texts)]

    monkeypatch.setattr("agent_service.services.knowledge_graph.deduplication.EmbeddingService", FakeEmbeddingService)
    entities = [
        EntityCandidate(name="Alpha", entity_type="concept", aliases=[], description="", confidence=0.95),
        EntityCandidate(name="Alpha Expanded", entity_type="concept", aliases=[], description="", confidence=0.90),
    ]

    merged, mapping, pending = service._deduplicate_document_entities_layered(
        user_id="user",
        library_id="library",
        entities=entities,
        extractor=SimpleNamespace(remote_adjudicator=None),
        document=_document(projection_hash="projection-v1", sections=[]),
    )

    assert len(merged) == 2
    assert mapping["Alpha Expanded"] == "Alpha"
    assert pending is False


def test_incremental_dedup_failure_stays_pending_and_retries_only_gray_pair(tmp_path: Path, monkeypatch: Any) -> None:
    """去重联网失败必须保存 pending，恢复后只重试原灰区实体对。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine)
    adjudicator = RecordingDedupAdjudicator(fail=True)
    extractor = SimpleNamespace(remote_adjudicator=adjudicator)
    entities = [SimpleNamespace(name="BetaGray", entity_type="concept")]
    monkeypatch.setattr(service, "_search_similar_entities", lambda **_: {
        "BetaGray": [("Beta Existing", 0.80, "concept")],
    })
    document = _document(projection_hash="projection-v1", sections=[])

    first = service._deduplicate_entities_incremental(
        user_id="user", library_id="library", new_entities=entities, extractor=extractor,
        document=document, return_pending_status=True,
    )
    adjudicator.fail = False
    second = service._deduplicate_entities_incremental(
        user_id="user", library_id="library", new_entities=entities, extractor=extractor,
        document=document, return_pending_status=True,
    )

    assert first == ({}, True)
    assert second == ({"BetaGray": "Beta Existing"}, False)
    assert adjudicator.calls == [
        {"BetaGray": [("Beta Existing", 0.80)]},
        {"BetaGray": [("Beta Existing", 0.80)]},
    ]


def test_full_dedup_sends_only_uncached_gray_pairs_online(tmp_path: Path, monkeypatch: Any) -> None:
    """手动全库去重必须本地合并高相似对，并缓存灰区的不合并判定。"""

    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    service = KnowledgeGraphService(config=_config(tmp_path), engine=engine)
    with Session(engine) as db:
        for label in ("Alpha", "AlphaAlias", "Gamma", "Delta"):
            db.add(KnowledgeGraphNode(
                node_id=f"node-{label}",
                user_id="user",
                library_id="library",
                node_type="entity",
                label=label,
                normalized_label=label.casefold(),
                entity_type="concept",
                source_uri="",
                metadata_json={"confidence": 0.9},
            ))
        db.commit()

    vectors = {
        "Alpha": [1.0, 0.0],
        "AlphaAlias": [0.999, 0.01],
        "Gamma": [0.0, 1.0],
        "Delta": [0.6, 0.8],
    }

    class FakeEmbeddingService:
        """按实体名返回可控相似度向量。"""

        def __init__(self, **_: Any) -> None:
            pass

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [vectors[text] for text in texts]

    remote_calls: list[list[str]] = []

    class FakeRemoteDeduplicator:
        """记录灰区批次并判定其中实体保持独立。"""

        def __init__(self, **_: Any) -> None:
            pass

        def deduplicate_entities(self, entities: list[Any], **_: Any) -> dict[str, Any]:
            remote_calls.append([entity.name for entity in entities])
            return {"entities": entities, "name_mapping": {entity.name: entity.name for entity in entities}}

    monkeypatch.setattr("agent_service.services.knowledge_graph.deduplication.EmbeddingService", FakeEmbeddingService)
    monkeypatch.setattr("agent_service.services.knowledge_graph.deduplication.LLMKnowledgeGraphExtractor", FakeRemoteDeduplicator)

    first = service.full_dedup_library(user_id="user", library_id="library", llm_config={
        "model_name": "remote-model", "api_key": "remote-key",
    })
    second = service.full_dedup_library(user_id="user", library_id="library", llm_config={
        "model_name": "remote-model", "api_key": "remote-key",
    })

    assert first == 1
    assert second == 0
    assert remote_calls == [["Gamma", "Delta"]]


def test_section_cache_model_records_all_invalidation_versions() -> None:
    """正式缓存模型必须包含正文和三个实现版本。"""

    columns = KnowledgeGraphSectionCache.__table__.columns
    assert {"section_hash", "extractor_version", "rule_version", "result_version"} <= set(columns.keys())
