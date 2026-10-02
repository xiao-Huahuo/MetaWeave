"""
工具运行时上下文模块。

功能说明:
本文件负责在 Agent 一轮执行期间为 builtin 工具暴露当前 `config`、`user_id`、
`session_id`、统一检索服务、记忆写入服务和 Embedding 服务。这样工具在执行时
可以访问当前会话上下文,而不需要把这些内部参数显式暴露给模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
from threading import local
from typing import TYPE_CHECKING, Any
from collections.abc import Callable, Iterator

from agent_service.core.agent_config import AgentConfig
from agent_service.services.memory.retrieval_service import MemoryRetrievalService

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
    from agent_service.services.memory.rag.embedding import EmbeddingService
    from agent_service.services.skill.service import SkillService
    from agent_service.services.settings.service import SettingsService
    from agent_service.services.task_list.service import TaskListService
    from agent_service.services.agent_change.service import AgentChangeService
    from agent_service.services.unified_search import UnifiedSearchService

AGENT_ACCESS_READONLY = "readonly"
AGENT_ACCESS_SANDBOX = "sandbox"
AGENT_ACCESS_FULL = "full_access"
AGENT_ACCESS_MODES = {AGENT_ACCESS_READONLY, AGENT_ACCESS_SANDBOX, AGENT_ACCESS_FULL}


@dataclass(slots=True)
class ToolRuntimeState:
    """
    工具运行时状态。

    config: 当前 Agent 配置对象。
    user_id: 当前用户 ID。
    session_id: 当前会话 ID。
    retrieval_service: 可复用的统一检索服务。
    unified_search_service: 与前端统一搜索框共用的四库联合搜索服务。
    memory_service: 可复用的长期记忆写入服务。
    embedding_service: 可复用的 Embedding 向量生成服务。
    """

    config: AgentConfig
    user_id: str
    session_id: str
    run_id: str
    retrieval_service: MemoryRetrievalService
    unified_search_service: UnifiedSearchService | None = None
    memory_service: LongTermMemoryService | None = None
    embedding_service: EmbeddingService | None = None
    task_list_service: TaskListService | None = None
    change_service: AgentChangeService | None = None
    skill_service: SkillService | None = None
    settings_service: SettingsService | None = None
    tool_services: dict[str, Any] = field(default_factory=dict)
    message_service: Any = None
    # Stable catalogue owned by this Agent turn, shared with scheduler model binding.
    tool_registry: Any = None
    cancellation_event: Any = None
    database_engine: Engine | None = None
    agent_access_mode: str = AGENT_ACCESS_SANDBOX
    long_term_memory_enabled: bool = True
    citation_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_citation_counter: int = 0
    network_citation_counter: int = 0
    child_agent_spawner: Callable[..., str] | None = None
    child_agent_waiter: Callable[..., str] | None = None
    child_agent_continuation: Callable[..., str] | None = None
    latest_file_patch: dict[str, str | bool] | None = None


_TOOL_RUNTIME = local()
_CHILD_TOOL_SCOPE: ContextVar[frozenset[str] | None] = ContextVar("child_tool_scope", default=None)


@contextmanager
def child_tool_scope(names: frozenset[str]) -> Iterator[None]:
    """Carry a native child's explicit grants to graph setup without changing shared Agent state."""
    token = _CHILD_TOOL_SCOPE.set(names)
    try:
        yield
    finally:
        _CHILD_TOOL_SCOPE.reset(token)


def get_child_tool_scope() -> frozenset[str] | None:
    """Return the inherited tool scope during child graph preparation."""
    return _CHILD_TOOL_SCOPE.get()


def set_tool_runtime(
    *,
    config: AgentConfig,
    user_id: str,
    session_id: str,
    run_id: str | None = None,
    retrieval_service: MemoryRetrievalService | None = None,
    unified_search_service: UnifiedSearchService | None = None,
    memory_service: LongTermMemoryService | None = None,
    embedding_service: EmbeddingService | None = None,
    task_list_service: TaskListService | None = None,
    change_service: AgentChangeService | None = None,
    skill_service: Any = None,
    settings_service: Any = None,
    tool_services: dict[str, Any] | None = None,
    message_service: Any = None,
    tool_registry: Any = None,
    cancellation_event: Any = None,
    database_engine: Any = None,
    citation_map: dict[str, dict[str, Any]] | None = None,
    agent_access_mode: str = AGENT_ACCESS_SANDBOX,
    long_term_memory_enabled: bool = True,
    child_agent_spawner: Callable[..., str] | None = None,
    child_agent_waiter: Callable[..., str] | None = None,
    child_agent_continuation: Callable[..., str] | None = None,
) -> None:
    """
    设置当前线程的工具运行时状态。

    config: 当前 Agent 配置。
    user_id: 当前用户 ID。
    session_id: 当前会话 ID。
    retrieval_service: 可选统一检索服务,用于测试或复用外部实例。
    unified_search_service: 可选四库联合搜索服务,供 Agent 搜索工具复用前端检索链路。
    memory_service: 可选长期记忆写入服务。
    embedding_service: 可选 Embedding 向量生成服务。
    """

    from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
    from agent_service.services.memory.rag.embedding import EmbeddingService

    resolved_memory_service = memory_service or LongTermMemoryService(config=config)
    _TOOL_RUNTIME.state = ToolRuntimeState(
        config=config,
        user_id=user_id,
        session_id=session_id,
        run_id=run_id or session_id,
        retrieval_service=retrieval_service or MemoryRetrievalService(config=config),
        unified_search_service=unified_search_service,
        memory_service=resolved_memory_service,
        embedding_service=embedding_service or EmbeddingService(config=config),
        task_list_service=task_list_service,
        change_service=change_service,
        skill_service=skill_service,
        settings_service=settings_service,
        tool_services=dict(tool_services or {}),
        message_service=message_service,
        tool_registry=tool_registry,
        cancellation_event=cancellation_event,
        database_engine=database_engine or getattr(resolved_memory_service, "engine", None),
        agent_access_mode=normalize_agent_access_mode(agent_access_mode),
        long_term_memory_enabled=bool(long_term_memory_enabled),
        citation_map=citation_map if citation_map is not None else {},
        child_agent_spawner=child_agent_spawner,
        child_agent_waiter=child_agent_waiter,
        child_agent_continuation=child_agent_continuation,
    )


def clear_tool_runtime() -> None:
    """清理当前线程的工具运行时状态。"""

    if hasattr(_TOOL_RUNTIME, "state"):
        delattr(_TOOL_RUNTIME, "state")


# ------------------------------------------------------------------
# 流式 Token 回调 (用于 ModelDecisionNode → AgentCore 实时推送)
# ------------------------------------------------------------------

_AGENT_TOKEN_CALLBACK: local = local()


def set_agent_token_callback(callback: Callable[[str], None]) -> None:
    """
    设置当前线程的 Agent token 回调,供 ModelDecisionNode 在流式生成时逐 token 调用。

    callback: 接收累积文本内容的回调函数。
    """

    _AGENT_TOKEN_CALLBACK.callback = callback


def get_agent_token_callback() -> Callable[[str], None] | None:
    """
    获取当前线程的 Agent token 回调。

    返回值: 已设置的回调函数,未设置时返回 None。
    """

    return getattr(_AGENT_TOKEN_CALLBACK, "callback", None)


def clear_agent_token_callback() -> None:
    """清理当前线程的 Agent token 回调。"""

    if hasattr(_AGENT_TOKEN_CALLBACK, "callback"):
        delattr(_AGENT_TOKEN_CALLBACK, "callback")


# ------------------------------------------------------------------
# 流式思考文本回调 (用于 ModelDecisionNode → AgentCore 实时推送 DeepSeek reasoning_content)
# ------------------------------------------------------------------

_AGENT_THINKING_CALLBACK: local = local()


def set_agent_thinking_callback(callback: Callable[[str], None]) -> None:
    """
    设置当前线程的 Agent 思考文本回调,供 ModelDecisionNode 在流式生成时
    把模型 reasoning_content 的累积文本逐次推送给上层(用于前端 Think 条实时展示)。

    callback: 接收累积思考文本内容的回调函数。
    """

    _AGENT_THINKING_CALLBACK.callback = callback


def get_agent_thinking_callback() -> Callable[[str], None] | None:
    """
    获取当前线程的 Agent 思考文本回调。

    返回值: 已设置的回调函数,未设置时返回 None。
    """

    return getattr(_AGENT_THINKING_CALLBACK, "callback", None)


def clear_agent_thinking_callback() -> None:
    """清理当前线程的 Agent 思考文本回调。"""

    if hasattr(_AGENT_THINKING_CALLBACK, "callback"):
        delattr(_AGENT_THINKING_CALLBACK, "callback")


# ------------------------------------------------------------------
# 工具调用 Trace 回调 (用于 ToolCallNode → AgentCore 实时推送)
# ------------------------------------------------------------------

_TOOL_TRACE_CALLBACK: local = local()


def set_tool_trace_callback(callback: Callable[[dict[str, Any]], None]) -> None:
    """
    设置当前线程的工具 trace 回调,供 ToolCallNode 在每步工具调用前后调用。

    callback: 接收 trace dict 的回调函数。
    """

    _TOOL_TRACE_CALLBACK.callback = callback


def get_tool_trace_callback() -> Callable[[dict[str, Any]], None] | None:
    """
    获取当前线程的工具 trace 回调。

    返回值: 已设置的回调函数,未设置时返回 None。
    """

    return getattr(_TOOL_TRACE_CALLBACK, "callback", None)


def clear_tool_trace_callback() -> None:
    """清理当前线程的工具 trace 回调。"""

    if hasattr(_TOOL_TRACE_CALLBACK, "callback"):
        delattr(_TOOL_TRACE_CALLBACK, "callback")


# ------------------------------------------------------------------
# Planner 内容回调 (用于 PlannerNode → AgentCore 流式推送)
# ------------------------------------------------------------------

_PLANNER_CONTENT_CALLBACK: local = local()


def set_planner_content_callback(callback: Callable[[str], None]) -> None:
    """设置当前线程的 planner 内容回调,供 PlannerNode 在流式生成时逐 token 调用。"""
    _PLANNER_CONTENT_CALLBACK.callback = callback


def get_planner_content_callback() -> Callable[[str], None] | None:
    """获取当前线程的 planner 内容回调。"""
    return getattr(_PLANNER_CONTENT_CALLBACK, "callback", None)


def clear_planner_content_callback() -> None:
    """清理当前线程的 planner 内容回调。"""
    if hasattr(_PLANNER_CONTENT_CALLBACK, "callback"):
        delattr(_PLANNER_CONTENT_CALLBACK, "callback")


# ------------------------------------------------------------------
# Observation 内容回调 (用于 ObservationNode → AgentCore 流式推送)
# ------------------------------------------------------------------

_OBSERVATION_CONTENT_CALLBACK: local = local()


def set_observation_content_callback(callback: Callable[[str], None]) -> None:
    """设置当前线程的 observation 内容回调,供 ObservationNode 在流式生成时逐 token 调用。"""
    _OBSERVATION_CONTENT_CALLBACK.callback = callback


def get_observation_content_callback() -> Callable[[str], None] | None:
    """获取当前线程的 observation 内容回调。"""
    return getattr(_OBSERVATION_CONTENT_CALLBACK, "callback", None)


def clear_observation_content_callback() -> None:
    """清理当前线程的 observation 内容回调。"""
    if hasattr(_OBSERVATION_CONTENT_CALLBACK, "callback"):
        delattr(_OBSERVATION_CONTENT_CALLBACK, "callback")


# ------------------------------------------------------------------
# 上下文镜像回调 (用于 ModelDecisionNode → AgentCore 发送模型所见完整消息列表)
# ------------------------------------------------------------------

_CONTEXT_MIRROR_CALLBACK: local = local()


def set_context_mirror_callback(callback: Callable[[dict[str, Any]], None]) -> None:
    """
    设置当前线程的上下文镜像回调, 供 ModelDecisionNode 在调用 LLM 前
    将完整消息列表镜像给 AgentCore, 再由 SSE 下发给前端 Obs 面板。

    callback: 接收最终模型请求快照的回调函数。快照包含消息、工具定义和实际模型参数。
    """
    _CONTEXT_MIRROR_CALLBACK.callback = callback


def get_context_mirror_callback() -> Callable[[dict[str, Any]], None] | None:
    """获取当前线程的上下文镜像回调。"""
    return getattr(_CONTEXT_MIRROR_CALLBACK, "callback", None)


def clear_context_mirror_callback() -> None:
    """清理当前线程的上下文镜像回调。"""
    if hasattr(_CONTEXT_MIRROR_CALLBACK, "callback"):
        delattr(_CONTEXT_MIRROR_CALLBACK, "callback")


# ------------------------------------------------------------------
# 上下文压缩生命周期回调 (用于 CompressNode → AgentCore 实时推送)
# ------------------------------------------------------------------

_CONTEXT_COMPRESSION_CALLBACK: local = local()


def set_context_compression_callback(callback: Callable[[dict[str, Any]], None]) -> None:
    """设置当前线程的压缩生命周期回调。"""

    _CONTEXT_COMPRESSION_CALLBACK.callback = callback


def get_context_compression_callback() -> Callable[[dict[str, Any]], None] | None:
    """返回当前线程的压缩生命周期回调。"""

    return getattr(_CONTEXT_COMPRESSION_CALLBACK, "callback", None)


def clear_context_compression_callback() -> None:
    """清理当前线程的压缩生命周期回调。"""

    if hasattr(_CONTEXT_COMPRESSION_CALLBACK, "callback"):
        delattr(_CONTEXT_COMPRESSION_CALLBACK, "callback")


# ------------------------------------------------------------------
# Task list update callback
# ------------------------------------------------------------------

_TASK_LIST_CALLBACK: local = local()


def set_task_list_callback(callback: Callable[[dict[str, Any] | None], None]) -> None:
    """Set the current thread task list update callback."""

    _TASK_LIST_CALLBACK.callback = callback


def get_task_list_callback() -> Callable[[dict[str, Any] | None], None] | None:
    """Return the current thread task list update callback."""

    return getattr(_TASK_LIST_CALLBACK, "callback", None)


def clear_task_list_callback() -> None:
    """Clear the current thread task list update callback."""

    if hasattr(_TASK_LIST_CALLBACK, "callback"):
        delattr(_TASK_LIST_CALLBACK, "callback")


# ------------------------------------------------------------------
# Markdown HTML visualization callback
# ------------------------------------------------------------------

_MARKDOWN_HTML_VISUALIZATION_CALLBACK: local = local()


def set_markdown_html_visualization_callback(callback: Callable[[dict[str, Any]], None]) -> None:
    """Set the current thread Markdown-to-HTML visualization callback."""

    _MARKDOWN_HTML_VISUALIZATION_CALLBACK.callback = callback


def get_markdown_html_visualization_callback() -> Callable[[dict[str, Any]], None] | None:
    """Return the current thread Markdown-to-HTML visualization callback."""

    return getattr(_MARKDOWN_HTML_VISUALIZATION_CALLBACK, "callback", None)


def clear_markdown_html_visualization_callback() -> None:
    """Clear the current thread Markdown-to-HTML visualization callback."""

    if hasattr(_MARKDOWN_HTML_VISUALIZATION_CALLBACK, "callback"):
        delattr(_MARKDOWN_HTML_VISUALIZATION_CALLBACK, "callback")


def get_tool_runtime() -> ToolRuntimeState:
    """
    获取当前线程的工具运行时状态。

    如果工具在 AgentCore 之外被直接调用,会抛出错误。
    """

    state = getattr(_TOOL_RUNTIME, "state", None)
    if state is None:
        raise RuntimeError("当前工具调用缺少 Agent 运行时上下文。")
    return state


def get_tool_service(name: str) -> Any:
    """返回应用生命周期显式注入的工具业务服务，不依赖 REST 请求上下文。"""

    service = get_tool_runtime().tool_services.get(name)
    if service is None:
        raise RuntimeError(f"工具业务服务未初始化: {name}")
    return service


def normalize_agent_access_mode(value: str | None) -> str:
    """规范化 Agent 权限模式,未知值回退到沙盒模式。"""

    normalized = (value or AGENT_ACCESS_SANDBOX).strip().lower()
    if normalized in {"read_only", "read-only", "只读"}:
        return AGENT_ACCESS_READONLY
    if normalized in {"full", "full-access", "完全访问"}:
        return AGENT_ACCESS_FULL
    if normalized not in AGENT_ACCESS_MODES:
        return AGENT_ACCESS_SANDBOX
    return normalized


def register_tool_citation(
    *,
    source_uri: str,
    content: str,
    adopted_by_default: bool = False,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Register one knowledge/tool citation plus optional render metadata."""

    state = get_tool_runtime()
    state.tool_citation_counter += 1
    citation_id = f"K{state.tool_citation_counter}"
    state.citation_map[citation_id] = {
        **(metadata or {}),
        "source_uri": source_uri,
        "content": content,
        "source": "tool",
        "adopted_by_default": adopted_by_default,
    }
    return citation_id


def register_network_citation(
    *,
    source_uri: str,
    content: str,
    title: str = "",
    adopted_by_default: bool = False,
) -> str:
    """Register one network search citation for the current tool runtime."""

    state = get_tool_runtime()
    state.network_citation_counter += 1
    citation_id = f"N{state.network_citation_counter}"
    state.citation_map[citation_id] = {
        "source_uri": source_uri,
        "content": content,
        "source": "network",
        "title": title,
        "adopted_by_default": adopted_by_default,
    }
    return citation_id


def get_tool_citation_map() -> dict[str, dict[str, Any]]:
    """Return citations registered by tools in the current runtime."""

    try:
        return dict(get_tool_runtime().citation_map)
    except RuntimeError:
        return {}


# ------------------------------------------------------------------
# Agent 内部探索状态 (保留给运行时内部链路使用,不再暴露为内置工具)
# ------------------------------------------------------------------

_PLAN_STATE: local = local()


def set_plan_state(plan: dict[str, Any] | None) -> None:
    """设置当前线程的探索状态,供工具读取和修改。"""
    import copy
    _PLAN_STATE.state = copy.deepcopy(plan) if plan is not None else None


def get_plan_state() -> dict[str, Any] | None:
    """获取当前线程的探索状态。"""
    return getattr(_PLAN_STATE, "state", None)


def clear_plan_state() -> None:
    """清理当前线程的探索状态。"""
    if hasattr(_PLAN_STATE, "state"):
        delattr(_PLAN_STATE, "state")
