"""
ContextBuilder 工具消息顺序过滤测试。

功能说明:
验证历史上下文进入模型前会清理不完整的 AIMessage/tool_calls 与 ToolMessage
组合,避免 OpenAI 返回 insufficient tool messages following tool_calls。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_service.services.memory.context_builder import ContextBuilder


def _ai_with_tool_calls(*tool_call_ids: str) -> AIMessage:
    """构造带指定 tool_call_id 的测试 AIMessage。"""

    return AIMessage(
        content="",
        tool_calls=[
            {"id": tool_call_id, "name": "read_file", "args": {}}
            for tool_call_id in tool_call_ids
        ],
    )


def test_filter_drops_incomplete_tool_call_block() -> None:
    """缺少任一 ToolMessage 时,整组 assistant tool_calls 应被过滤。"""

    messages = [
        HumanMessage(content="查文件"),
        _ai_with_tool_calls("call_1", "call_2"),
        ToolMessage(content="结果 1", tool_call_id="call_1"),
        HumanMessage(content="下一轮"),
    ]

    filtered = ContextBuilder._filter_orphaned_tool_messages(messages)

    assert [message.type for message in filtered] == ["human", "human"]


def test_filter_keeps_complete_contiguous_tool_call_block() -> None:
    """tool_calls 后紧跟完整 ToolMessage 块时应完整保留。"""

    messages = [
        HumanMessage(content="查文件"),
        _ai_with_tool_calls("call_1", "call_2"),
        ToolMessage(content="结果 1", tool_call_id="call_1"),
        ToolMessage(content="结果 2", tool_call_id="call_2"),
        HumanMessage(content="下一轮"),
    ]

    filtered = ContextBuilder._filter_orphaned_tool_messages(messages)

    assert [message.type for message in filtered] == ["human", "ai", "tool", "tool", "human"]


def test_filter_drops_orphan_tool_message() -> None:
    """没有前置 AIMessage 的 ToolMessage 不能进入模型上下文。"""

    messages = [
        HumanMessage(content="查文件"),
        ToolMessage(content="孤立结果", tool_call_id="call_1"),
    ]

    filtered = ContextBuilder._filter_orphaned_tool_messages(messages)

    assert [message.type for message in filtered] == ["human"]
