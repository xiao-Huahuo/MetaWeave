"""
Agent 图节点基础类型。

功能说明:
本文件只定义 LangGraph 图运行时共享的状态结构,不实现任何具体节点。
所有具体节点文件都应只实现一个节点类,并通过 `AgentState` 读写消息、用户、
会话和观测轨迹数据。

使用说明:
`graph.py` 使用 `AgentState` 创建 `StateGraph`;节点返回的 `messages` 会通过
LangGraph 的 `add_messages` 自动追加,`trace` 会通过列表累加保存节点运行轨迹。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    Agent 图运行状态。

    messages: 当前会话消息列表,由 LangGraph 自动追加节点返回的新消息。
    user_id: 业务侧用户 ID,后续用于会话隔离和长期记忆归属。
    session_id: 会话 ID,后续用于短期记忆和 checkpoint 恢复。
    trace: 节点运行轨迹,用于观测面板展示每个节点发生了什么。
    plan: 策略顾问节点生成的探索状态,格式: {"covered": [...], "suggested": [...], "sufficient": bool, "hint": str}。
    observation_decision: 反思节点决策结果,"continue" 继续调工具 / "answer" 直接回答。
    skill_index: 本轮用户输入命中的少量 Skill 候选摘要,不是全量 Skill 注册表。
    active_skills: 本轮路由命中的 Skill 正文,只在当前图运行中生效。
    bound_tool_names: 最近一次模型请求实际绑定的工具名,供 Action 节点做最终授权校验。

    llm_config: 可选,预读取的用户 LLM 配置,避免图重入时重复读取 SettingsService。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    trace: Annotated[list[dict[str, Any]], add]
    plan: dict[str, Any] | None
    task_list: dict[str, Any] | None
    skill_index: list[dict[str, Any]] | None
    active_skills: list[dict[str, Any]] | None
    observation_decision: str
    llm_config: dict[str, Any] | None
    long_term_memory_enabled: bool
    compression_state: dict[str, Any] | None
    cancel_event: Any
    context_overhead_tokens: int
    context_tool_tokens: int
    bound_tool_names: NotRequired[list[str]]
