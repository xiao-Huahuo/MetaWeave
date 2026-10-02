"""
子 Agent 运行时共享类型。

功能说明:
本文件定义子 Agent 的任务合同、状态记录、完成结果和运行时控制上下文。
这些类型不依赖 LangGraph 或具体模型,便于独立测试和后续接入不同执行器。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event, Lock
from typing import Any, Protocol


class ChildAgentStatus(StrEnum):
    """子 Agent 生命周期状态。"""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ChildAgentUpdate(StrEnum):
    """父 Agent 可以发送给子 Agent 的控制消息类型。"""

    STOP = "stop"
    UPDATE_CONTEXT = "update_context"


@dataclass(frozen=True, slots=True)
class ChildAgentContract:
    """
    父 Agent 发送给子 Agent 的子任务合同。

    goal: 子 Agent 必须完成的目标。
    parent_run_id: 父 Agent 运行实例 ID。
    mode: `foreground` 会阻塞调用方,`background` 立即返回。
    allowed_tools: 父 Agent 分配给子 Agent 的工具名;为 None 时继承父工具集。
    access_mode: 子 Agent 的沙盒权限,不能高于父 Agent。
    input_refs: 子 Agent 需要读取的外部输入引用,避免复制完整父上下文。
    output_contract: 对子 Agent 最终产出的格式要求。
    """

    goal: str
    parent_run_id: str
    user_id: str = ""
    session_id: str = ""
    agent_mode: str = "react"
    mode: str = "background"
    allowed_tools: frozenset[str] | None = None
    access_mode: str = "sandbox"
    input_refs: tuple[str, ...] = ()
    output_contract: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    category: str = ""
    name: str = ""
    provider: str = "native"
    workspace_root: str = ""


@dataclass(slots=True)
class ChildAgentResult:
    """子 Agent 投递给父 Agent 的最终结果。"""

    run_id: str
    parent_run_id: str
    status: ChildAgentStatus
    summary: str = ""
    result: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChildAgentEvent:
    """子 Agent 生命周期事件,供父 Agent 流式界面和后台面板消费。"""

    event_name: str
    run_id: str
    session_id: str
    parent_run_id: str
    goal: str
    mode: str
    status: ChildAgentStatus
    access_mode: str
    allowed_tools: tuple[str, ...]
    created_at: float
    category: str = ""
    name: str = ""
    provider: str = "native"
    summary: str = ""
    result: Any = None
    error: str | None = None


@dataclass(slots=True)
class ChildAgentExecutionContext:
    """
    子 Agent 独立执行上下文。

    cancellation: 协作式停止信号,执行器应在安全检查点调用 `raise_if_stopped`。
    updates: 父 Agent 发来的上下文更新由管理器写入,执行器可调用 `drain_updates` 读取。
    tool_catalog_callback: 外部 Runtime 握手后由管理器发布真实工具名和能力事件。
    """

    run_id: str
    parent_run_id: str
    goal: str
    user_id: str
    session_id: str
    agent_mode: str
    allowed_tools: frozenset[str]
    access_mode: str
    input_refs: tuple[str, ...]
    output_contract: Mapping[str, Any]
    cancellation: Event
    category: str = ""
    name: str = ""
    provider: str = "native"
    workspace_root: str = ""
    tool_catalog_callback: Callable[[frozenset[str]], None] | None = field(default=None, repr=False)
    _updates: list[Mapping[str, Any]] = field(default_factory=list)
    _updates_lock: Lock = field(default_factory=Lock)

    def raise_if_stopped(self) -> None:
        """若父 Agent 已要求停止,立即抛出 `ChildAgentStopped`。"""

        if self.cancellation.is_set():
            raise ChildAgentStopped("子 Agent 已收到停止信号。")

    def publish_tools(self, tools: frozenset[str]) -> None:
        """发布外部 Runtime 握手返回的真实目录；管理器负责原子更新与事件。"""

        if self.tool_catalog_callback is not None:
            self.tool_catalog_callback(tools)
        else:
            self.allowed_tools = tools

    def drain_updates(self) -> list[Mapping[str, Any]]:
        """读取并清空父 Agent 发来的上下文更新。"""

        with self._updates_lock:
            updates = list(self._updates)
            self._updates.clear()
        return updates

    def _append_update(self, update: Mapping[str, Any]) -> None:
        """由 `ChildAgentManager` 写入一条上下文更新。"""

        with self._updates_lock:
            self._updates.append(dict(update))


class ChildAgentStopped(RuntimeError):
    """执行器响应停止信号时使用的内部异常。"""


class ChildAgentExecutor(Protocol):
    """具体子 Agent 执行器协议。"""

    def __call__(self, context: ChildAgentExecutionContext) -> Any:
        """执行子任务并返回任意可序列化结果。"""


@dataclass(slots=True)
class ChildAgentRecord:
    """子 Agent 运行实例的内存记录。"""

    run_id: str
    contract: ChildAgentContract
    status: ChildAgentStatus = ChildAgentStatus.CREATED
    effective_tools: frozenset[str] = frozenset()
    effective_access_mode: str = "sandbox"
    result: ChildAgentResult | None = None
    context: ChildAgentExecutionContext | None = None
