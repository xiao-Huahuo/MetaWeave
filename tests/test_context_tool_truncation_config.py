"""上下文与工具结果硬截断必须由全局 AgentConfig 统一控制。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_service.core.agent_config import AgentConfig
from agent_service.services.knowledge_graph import LLMKnowledgeGraphExtractor
from agent_service.services.memory.rag.frontmatter_document import (
    StructuredKnowledgeDocument,
    StructuredKnowledgeSection,
)
from agent_service.tools.builtin.memory import delete_long_term_memory
from agent_service.tools.builtin.utility import list_available_tools
from agent_service.tools.runtime_context import clear_tool_runtime, set_tool_runtime


def _config(tmp_path: Path, **limits: int) -> AgentConfig:
    """构造只覆盖待验收截断字段的最小配置。"""

    return AgentConfig.load_config(
        {
            "limits": limits,
            "storage": {
                "project_root": str(tmp_path),
                "base_data_dir": str(tmp_path / "runtime"),
            },
        },
        load_env=False,
        load_dotenv=False,
        ensure_directories=False,
        ensure_models=False,
    )


def test_tool_catalog_description_limit_comes_from_agent_config(tmp_path: Path, monkeypatch) -> None:
    """工具清单交给 Agent 的描述长度不得继续写死为 100。"""

    config = _config(tmp_path, tool_registry_description_chars=4)
    definition = SimpleNamespace(
        name="demo_tool",
        display_name="Demo",
        description="abcdefghij",
    )
    registry = SimpleNamespace(definitions={definition.name: definition})
    monkeypatch.setattr(
        "agent_service.tools.tool_registry.ToolRegistry.with_builtin_tools",
        lambda **_kwargs: registry,
    )
    set_tool_runtime(config=config, user_id="u1", session_id="s1")
    try:
        result = list_available_tools()
    finally:
        clear_tool_runtime()

    assert "abcd…" in result
    assert "abcde" not in result


def test_memory_tool_deletion_uses_exact_service_lookup_without_result_truncation(tmp_path: Path) -> None:
    """长期记忆删除回执交给 Agent 的正文预览长度必须可配置。"""

    config = _config(tmp_path)
    memory = SimpleNamespace(memory_id="m1", content="abcdefghij")
    memory_service = SimpleNamespace(
        find_user_memory_by_content=lambda **_kwargs: memory,
        delete_memory=lambda **_kwargs: True,
    )
    set_tool_runtime(
        config=config,
        user_id="u1",
        session_id="s1",
        memory_service=memory_service,
    )
    try:
        result = delete_long_term_memory("abcdefghij")
    finally:
        clear_tool_runtime()

    assert result == "已删除长期记忆: abcdefghij"


def test_graph_single_section_context_is_not_cut_by_fixed_character_limit(tmp_path: Path) -> None:
    """单章节图谱抽取发送给模型的正文长度必须读取全局配置。"""

    config = _config(tmp_path)
    response = MagicMock(content='{"entities": [], "relations": []}')
    scheduler = MagicMock()
    scheduler.invoke_chat.return_value = response
    extractor = LLMKnowledgeGraphExtractor(config=config, task_scheduler=scheduler)
    section = StructuredKnowledgeSection(
        section_id="s1",
        heading="S1",
        title_path=["S1"],
        content="abcdefghij",
        start_char=0,
        end_char=10,
    )
    document = StructuredKnowledgeDocument(
        document_id="d1",
        source_type="text",
        source_path=str(tmp_path / "doc.txt"),
        source_uri=str(tmp_path / "doc.txt"),
        source_hash="hash",
        title="doc",
        summary="",
        tags=[],
        authority=0.7,
        valid_from=None,
        valid_until=None,
        metadata={},
        sections=[section],
    )

    extractor.extract(document=document, section=section)

    request = scheduler.invoke_chat.call_args.kwargs["messages"][1].content
    assert "abcdefg" in request
    assert "abcdefghij" in request


def test_attachment_candidate_preview_uses_registered_config_field() -> None:
    """附件工具的四个候选列表不得绕过已存在的全局配置字段。"""

    source = (
        Path(__file__).resolve().parents[1]
        / "agent_service"
        / "tools"
        / "builtin"
        / "knowledge.py"
    ).read_text(encoding="utf-8")

    assert source.count("runtime.config.limits.tool_attachment_match_preview_count") == 4
    assert "[:8]" not in source
