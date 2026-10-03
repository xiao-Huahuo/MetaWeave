"""
长期记忆开关的上下文构建回归测试。

验证关闭长期记忆时不会触发 embedding、向量召回、ReRank 或摘要查询，
同时仍然保留普通会话历史和当前用户输入。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from agent_service.core.agent_config import AgentConfig
from agent_service.services.memory.context_builder import ContextBuilder


class _MessageServiceStub:
    def list_session_messages(self, **_kwargs):
        return []


class _RetrievalServiceMustNotBeCalled:
    def serialize_debug_snapshot(self, _snapshot):
        return {"pre_rerank": [], "post_rerank": []}

    def retrieve_long_term_memory_with_debug(self, **_kwargs):
        raise AssertionError("long-term retrieval must be skipped when disabled")

    def get_latest_session_summary(self, **_kwargs):
        raise AssertionError("session summary lookup must be skipped when disabled")

    def get_latest_important_fact_summary(self, **_kwargs):
        raise AssertionError("important summary lookup must be skipped when disabled")


def test_context_builder_skips_all_fixed_memory_recall_when_disabled() -> None:
    config = AgentConfig.load_config({}, load_env=False, ensure_directories=False, ensure_models=False)
    builder = ContextBuilder(
        config=config,
        message_service=_MessageServiceStub(),  # type: ignore[arg-type]
        retrieval_service=_RetrievalServiceMustNotBeCalled(),  # type: ignore[arg-type]
    )

    messages = builder.build_messages(
        user_id="u1",
        session_id="s1",
        current_prompt="hello",
        long_term_memory_enabled=False,
    )

    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "hello"


def test_context_builder_explains_explicit_knowledge_mounts_and_all_citations() -> None:
    """真实上下文注入包含四库 URL 挂载规则，避免仍只告诉模型 K/N 与文件 URL。"""

    config = AgentConfig.load_config({}, load_env=False, ensure_directories=False, ensure_models=False)
    builder = ContextBuilder(
        config=config,
        message_service=_MessageServiceStub(),  # type: ignore[arg-type]
        retrieval_service=_RetrievalServiceMustNotBeCalled(),  # type: ignore[arg-type]
    )
    messages = builder.build_messages(
        user_id="u1",
        session_id="s1",
        current_prompt="挂载一个图书条目",
        long_term_memory_enabled=False,
    )
    context = "\n".join(str(message.content) for message in messages[:-1])
    assert "get_knowledge_url" in context and "citation_id" in context
    assert "library、components、literature" in context
    assert "搜索或 K 引用本身不会挂载知识块" in context
    assert "文件块保持现有样式" in context
    assert "get_knowledge_file_url" not in context
    assert "[标题](URL)" in context and "![描述](图片URL)" in context
    assert "四库知识来源" in context
    assert "[A1]" in context and "[1]" in context
    assert "URL 工具只用于展示与打开" in context
