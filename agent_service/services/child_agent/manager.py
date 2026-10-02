"""
父子 Agent 管理器。

功能说明:
本文件实现子 Agent 的创建、前后台执行、状态查询、结果投递、停止和上下文更新。
它只负责运行时编排,不绑定具体 LLM 或 LangGraph,具体执行逻辑通过执行器注入。

使用说明:
调用方应为每个子任务提供一个 `ChildAgentExecutor`。第一版的结果队列按
`parent_run_id` 隔离,未来可以在不改变调用协议的情况下替换为 Redis Stream。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from queue import Empty, Queue
from threading import Event, Lock
import time
from typing import Any
from uuid import uuid4

from agent_service.core.agent_config import AgentConfig
from agent_service.tools.runtime_context import (
    AGENT_ACCESS_FULL,
    AGENT_ACCESS_READONLY,
    AGENT_ACCESS_SANDBOX,
    normalize_agent_access_mode,
)
from agent_service.services.child_agent.types import (
    ChildAgentContract,
    ChildAgentExecutionContext,
    ChildAgentEvent,
    ChildAgentExecutor,
    ChildAgentRecord,
    ChildAgentResult,
    ChildAgentStatus,
    ChildAgentStopped,
    ChildAgentUpdate,
)


class ChildAgentManager:
    """
    管理一个进程内的父子 Agent 运行实例。

    max_workers: 同时执行的子 Agent 最大线程数。
    event_callback: 每次状态变化时接收 `(event_name, record)` 的回调。
    """

    _ACCESS_RANK = {
        AGENT_ACCESS_READONLY: 0,
        AGENT_ACCESS_SANDBOX: 1,
        AGENT_ACCESS_FULL: 2,
    }

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        config: AgentConfig | None = None,
        event_callback: Callable[[str, ChildAgentRecord], None] | None = None,
    ) -> None:
        """初始化线程池、运行记录表和按父级隔离的结果队列。"""

        limits = (config or AgentConfig()).limits
        self._executor = ThreadPoolExecutor(
            max_workers=max(limits.child_agent_max_workers if max_workers is None else max_workers, 1),
            thread_name_prefix="child-agent",
        )
        self._records: dict[str, ChildAgentRecord] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._executors: dict[str, ChildAgentExecutor] = {}
        self._turn_numbers: dict[str, int] = {}
        self._claimed_wakeup_turns: dict[str, int] = {}
        self._result_queues: defaultdict[str, Queue[ChildAgentResult]] = defaultdict(Queue)
        self._event_queues_by_session: defaultdict[str, Queue[ChildAgentEvent]] = defaultdict(Queue)
        self._lock = Lock()
        self._event_callback = event_callback
        self._closed = False

    def spawn(
        self,
        *,
        contract: ChildAgentContract,
        executor: ChildAgentExecutor,
        parent_tools: frozenset[str] | None = None,
        parent_access_mode: str = AGENT_ACCESS_SANDBOX,
        caller_is_child: bool = False,
    ) -> ChildAgentRecord:
        """创建并启动一个子 Agent,前台模式会等待完成后再返回。"""

        if self._closed:
            raise RuntimeError("ChildAgentManager 已关闭。")
        if caller_is_child:
            raise PermissionError("子 Agent 不能召唤其他子 Agent。")
        if not contract.goal.strip():
            raise ValueError("子 Agent 目标不能为空。")
        if contract.mode not in {"foreground", "background"}:
            raise ValueError("子 Agent mode 必须是 foreground 或 background。")
        if contract.provider not in {"native", "dsh"}:
            raise ValueError("子 Agent provider 必须是 native 或 dsh。")

        effective_parent_access = normalize_agent_access_mode(parent_access_mode)
        effective_child_access = normalize_agent_access_mode(contract.access_mode)
        if self._ACCESS_RANK[effective_child_access] > self._ACCESS_RANK[effective_parent_access]:
            raise PermissionError("子 Agent 权限不能高于父 Agent 权限。")

        if contract.provider == "dsh":
            # DSH 工具由独立 Runtime 注册，握手前不能借用父工具或猜测 aliases。
            effective_tools = frozenset()
        elif contract.allowed_tools is None:
            effective_tools = parent_tools or frozenset()
        elif parent_tools is None:
            effective_tools = frozenset(contract.allowed_tools)
        else:
            effective_tools = frozenset(contract.allowed_tools) & parent_tools
        run_id = f"child_run_{uuid4().hex}"
        cancellation = Event()
        context = ChildAgentExecutionContext(
            run_id=run_id,
            parent_run_id=contract.parent_run_id,
            goal=contract.goal,
            user_id=contract.user_id,
            session_id=contract.session_id,
            agent_mode=contract.agent_mode,
            allowed_tools=effective_tools,
            access_mode=effective_child_access,
            input_refs=contract.input_refs,
            output_contract=contract.output_contract,
            cancellation=cancellation,
            category=contract.category,
            name=contract.name,
            provider=contract.provider,
            workspace_root=contract.workspace_root,
            tool_catalog_callback=(lambda tools: self._publish_tools(run_id, tools)) if contract.provider == "dsh" else None,
        )
        record = ChildAgentRecord(
            run_id=run_id,
            contract=contract,
            effective_tools=effective_tools,
            effective_access_mode=effective_child_access,
            context=context,
        )
        with self._lock:
            self._records[run_id] = record
            self._executors[run_id] = executor
            self._turn_numbers[run_id] = 0
            self._result_queues[contract.parent_run_id]
        self._emit("child_agent.created", record)

        future = self._submit(record, executor)
        if contract.mode == "foreground":
            future.result()
        return record

    def continue_child(
        self,
        *,
        run_id: str,
        prompt: str,
        mode: str = "background",
        parent_run_id: str | None = None,
    ) -> ChildAgentRecord:
        """原子预留同一 DSH 的下一 Turn；新父 run 仅在预留成功时绑定。"""

        record = self._require_record(run_id)
        if not prompt.strip():
            raise ValueError("DSH 子 Agent追问不能为空")
        if mode not in {"foreground", "background"}:
            raise ValueError("子 Agent mode 必须是 foreground 或 background。")
        # 状态检查和预留必须同属一个短临界区，避免重复提交同一 Conversation。
        with self._lock:
            if self._closed:
                raise RuntimeError("ChildAgentManager 已关闭。")
            if record.contract.provider != "dsh":
                raise ValueError("只有 DSH 子 Agent支持持续追问")
            if record.status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING}:
                raise RuntimeError("DSH 子 Agent当前仍在运行")
            assert record.context is not None
            previous_parent_run_id = record.contract.parent_run_id
            if parent_run_id is not None:
                record.contract = replace(record.contract, parent_run_id=parent_run_id)
                record.context.parent_run_id = parent_run_id
            record.context.goal = prompt.strip()
            record.context.cancellation = Event()
            record.result = None
            record.status = ChildAgentStatus.CREATED
            self._turn_numbers[run_id] = self._turn_numbers.get(run_id, 0) + 1
            executor = self._executors[run_id]
            created_record = replace(record)
        self._discard_queued_results(previous_parent_run_id, run_id)
        self._emit("child_agent.turn_created", created_record)
        future = self._submit(record, executor)
        if mode == "foreground":
            future.result()
        return record

    def get(self, run_id: str) -> ChildAgentRecord | None:
        """按运行 ID 查询子 Agent 当前记录。"""

        with self._lock:
            return self._records.get(run_id)

    def _publish_tools(self, run_id: str, tools: frozenset[str]) -> None:
        """原子更新 DSH 握手目录，锁外发布可持久化与流式消费的能力事件。"""

        with self._lock:
            record = self._records[run_id]
            assert record.context is not None
            if record.context.cancellation.is_set():
                raise ChildAgentStopped("DSH 子 Agent 已停止，不能发布工具目录")
            record.context.allowed_tools = tools
            if record.effective_tools == tools:
                return
            record.effective_tools = tools
            snapshot = replace(record)
        self._emit("child_agent.capabilities", snapshot)

    def restore(
        self,
        *,
        run_id: str,
        contract: ChildAgentContract,
        executor: ChildAgentExecutor,
        status: ChildAgentStatus = ChildAgentStatus.COMPLETED,
    ) -> ChildAgentRecord:
        """把数据库/Session快照中的终态 DSH Child Agent恢复为可追问记录。"""

        if status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING}:
            raise ValueError("不能从快照恢复活动中的子 Agent")
        restored_tools = contract.allowed_tools or frozenset()
        if contract.provider == "dsh" and any(tool.startswith("dsh.") for tool in restored_tools):
            # 旧版目录是 MW 猜测的 aliases；等待新 Runtime 握手，不能改名假装真实。
            restored_tools = frozenset()
        context = ChildAgentExecutionContext(
            run_id=run_id,
            parent_run_id=contract.parent_run_id,
            goal=contract.goal,
            user_id=contract.user_id,
            session_id=contract.session_id,
            agent_mode=contract.agent_mode,
            allowed_tools=restored_tools,
            access_mode=contract.access_mode,
            input_refs=contract.input_refs,
            output_contract=contract.output_contract,
            cancellation=Event(),
            category=contract.category,
            name=contract.name,
            provider=contract.provider,
            workspace_root=contract.workspace_root,
            tool_catalog_callback=(lambda tools: self._publish_tools(run_id, tools)) if contract.provider == "dsh" else None,
        )
        record = ChildAgentRecord(
            run_id=run_id,
            contract=contract,
            status=status,
            effective_tools=restored_tools,
            effective_access_mode=contract.access_mode,
            context=context,
        )
        with self._lock:
            existing = self._records.get(run_id)
            if existing is not None:
                return existing
            self._records[run_id] = record
            self._executors[run_id] = executor
            self._turn_numbers[run_id] = 0
            self._result_queues[contract.parent_run_id]
        return record

    def claim_completion_wakeup(self, run_id: str) -> bool:
        """原子领取当前子 Agent Turn 的终态唤醒；同一 Turn 只允许成功一次。"""

        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                raise KeyError(f"子 Agent {run_id} 不存在。")
            if record.status not in {
                ChildAgentStatus.COMPLETED,
                ChildAgentStatus.FAILED,
                ChildAgentStatus.STOPPED,
            }:
                return False
            turn_number = self._turn_numbers.get(run_id, 0)
            if self._claimed_wakeup_turns.get(run_id) == turn_number:
                return False
            self._claimed_wakeup_turns[run_id] = turn_number
            return True

    def list_children(self, parent_run_id: str) -> list[ChildAgentRecord]:
        """列出指定父 Agent 创建的全部子 Agent。"""

        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.contract.parent_run_id == parent_run_id
            ]

    def list_children_for_session(self, session_id: str) -> list[ChildAgentRecord]:
        """列出指定主会话创建的子 Agent。"""

        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.contract.session_id == session_id
            ]

    def drain_results(self, parent_run_id: str) -> list[ChildAgentResult]:
        """读取并清空指定父 Agent 的结果队列。"""

        result_queue = self._result_queues[parent_run_id]
        results: list[ChildAgentResult] = []
        while True:
            try:
                results.append(result_queue.get_nowait())
            except Empty:
                return results

    def drain_results_for_session(self, session_id: str) -> list[ChildAgentResult]:
        """读取并清空指定主会话下全部父 Agent 的结果队列。"""

        parent_run_ids = {
            record.contract.parent_run_id
            for record in self.list_children_for_session(session_id)
        }
        results: list[ChildAgentResult] = []
        for parent_run_id in parent_run_ids:
            results.extend(self.drain_results(parent_run_id))
        return results

    def drain_events_for_session(self, session_id: str) -> list[ChildAgentEvent]:
        """读取并清空指定主会话下的子 Agent 生命周期事件。"""

        event_queue = self._event_queues_by_session[session_id]
        events: list[ChildAgentEvent] = []
        while True:
            try:
                events.append(event_queue.get_nowait())
            except Empty:
                return events

    def wait_for_children(
        self,
        *,
        parent_run_id: str,
        run_ids: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildAgentResult | None:
        """
        等待指定父 Agent 下一个子 Agent 产出终态结果。

        run_ids 为空时接收该父 Agent 任意子 Agent 的下一个结果。
        如果结果队列已有匹配结果,立即返回;否则阻塞到下一个结果或超时。
        未匹配 run_ids 的结果会放回队列,避免被错误消费。
        """

        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        target_run_ids = set(run_ids or [])
        result_queue = self._result_queues[parent_run_id]
        skipped_results: list[ChildAgentResult] = []
        while True:
            timeout = 0.05
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._restore_skipped_results(parent_run_id, skipped_results)
                    return None
                timeout = min(timeout, remaining)
            try:
                result = result_queue.get(timeout=timeout)
            except Empty:
                if not self._has_pending_children(parent_run_id=parent_run_id, run_ids=target_run_ids):
                    self._restore_skipped_results(parent_run_id, skipped_results)
                    return None
                continue
            if not target_run_ids or result.run_id in target_run_ids:
                self._restore_skipped_results(parent_run_id, skipped_results)
                return result
            skipped_results.append(result)

    def wait_for_children_for_session(
        self,
        *,
        session_id: str,
        run_ids: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildAgentResult | None:
        """跨父 run 等待同一主会话的下一个子 Agent 终态结果。"""

        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        target_run_ids = set(run_ids or [])
        skipped_results: list[ChildAgentResult] = []
        while True:
            available = self.drain_results_for_session(session_id)
            for index, result in enumerate(available):
                if not target_run_ids or result.run_id in target_run_ids:
                    self._restore_session_results([*skipped_results, *available[index + 1:]])
                    return result
                skipped_results.append(result)
            records = self.list_children_for_session(session_id)
            if target_run_ids:
                records = [record for record in records if record.run_id in target_run_ids]
            if not any(record.status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING} for record in records):
                self._restore_session_results(skipped_results)
                return None
            sleep_seconds = 0.05
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._restore_session_results(skipped_results)
                    return None
                sleep_seconds = min(sleep_seconds, remaining)
            time.sleep(sleep_seconds)

    def stop(self, run_id: str) -> bool:
        """向子 Agent 发送协作式停止信号。"""

        record = self._require_record(run_id)
        if record.status in {ChildAgentStatus.COMPLETED, ChildAgentStatus.FAILED, ChildAgentStatus.STOPPED}:
            return False
        assert record.context is not None
        record.context.cancellation.set()
        self._emit("child_agent.stop_requested", record)
        return True

    def update_context(self, run_id: str, update: Mapping[str, Any]) -> None:
        """把一条上下文更新排入子 Agent 的下一次安全检查点。"""

        record = self._require_record(run_id)
        if record.status not in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING}:
            raise RuntimeError("只有未完成的子 Agent 才能接收上下文更新。")
        assert record.context is not None
        record.context._append_update(update)
        self._emit("child_agent.context_updated", record)

    def close(self) -> None:
        """停止接收新任务并关闭子 Agent 线程池。"""

        with self._lock:
            self._closed = True
            run_ids = list(self._records)
        for run_id in run_ids:
            self.stop(run_id)
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, record: ChildAgentRecord, executor: ChildAgentExecutor) -> None:
        """在线程池中执行一个子 Agent 并投递最终结果。"""

        assert record.context is not None
        record.status = ChildAgentStatus.RUNNING
        self._emit("child_agent.started", record)
        try:
            value = executor(record.context)
            if record.context.cancellation.is_set():
                raise ChildAgentStopped("子 Agent 在完成前收到停止信号。")
        except ChildAgentStopped as exc:
            result = ChildAgentResult(
                run_id=record.run_id,
                parent_run_id=record.contract.parent_run_id,
                status=ChildAgentStatus.STOPPED,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            result = ChildAgentResult(
                run_id=record.run_id,
                parent_run_id=record.contract.parent_run_id,
                status=ChildAgentStatus.FAILED,
                error=str(exc),
            )
        else:
            result = ChildAgentResult(
                run_id=record.run_id,
                parent_run_id=record.contract.parent_run_id,
                status=ChildAgentStatus.COMPLETED,
                result=value,
                summary=str(value) if isinstance(value, str) else "",
            )
        self._finish(record, result)

    def _finish(self, record: ChildAgentRecord, result: ChildAgentResult) -> None:
        """先完成锁外终态落库，再原子发布终态、结果和可领取唤醒的内存事件。"""

        event_name = f"child_agent.{result.status.value}"
        completed_record = replace(record, status=result.status, result=result)
        event = self._event_from_record(event_name, completed_record)
        try:
            if self._event_callback is not None:
                self._event_callback(event_name, completed_record)
        finally:
            # 唯一锁顺序：manager 锁 → 已知 Queue 内部锁。两个邮箱均无界，
            # put_nowait 只更新内存，不执行回调或等待；消费者 get 结束后才拿 manager 锁。
            # 回调失败也必须发布终态，避免永久活动；新 Turn 此前始终不可预留。
            with self._lock:
                record.result = result
                record.status = result.status
                if event is not None:
                    self._event_queues_by_session[event.session_id].put_nowait(event)
                self._result_queues[result.parent_run_id].put_nowait(result)

    def _submit(self, record: ChildAgentRecord, executor: ChildAgentExecutor) -> Future[Any]:
        """锁外提交子任务；线程池拒绝时投递失败终态，避免记录永久停在 CREATED。"""

        try:
            future = self._executor.submit(self._run, record, executor)
        except Exception as exc:
            error = "子 Agent 任务提交失败。"
            result = ChildAgentResult(
                run_id=record.run_id,
                parent_run_id=record.contract.parent_run_id,
                status=ChildAgentStatus.FAILED,
                error=error,
            )
            self._finish(record, result)
            raise RuntimeError(error) from exc
        with self._lock:
            self._futures[record.run_id] = future
        return future

    def _require_record(self, run_id: str) -> ChildAgentRecord:
        """读取运行记录,不存在时抛出明确错误。"""

        record = self.get(run_id)
        if record is None:
            raise KeyError(f"子 Agent {run_id} 不存在。")
        return record

    def _has_pending_children(self, *, parent_run_id: str, run_ids: set[str]) -> bool:
        """判断指定父 Agent 是否还有目标子 Agent 尚未进入终态。"""

        records = self.list_children(parent_run_id)
        if run_ids:
            records = [record for record in records if record.run_id in run_ids]
        return any(record.status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING} for record in records)

    def _restore_skipped_results(self, parent_run_id: str, results: list[ChildAgentResult]) -> None:
        """把本次等待中跳过的非目标结果放回父 Agent 结果队列。"""

        if not results:
            return
        result_queue = self._result_queues[parent_run_id]
        for result in results:
            result_queue.put(result)

    def _restore_session_results(self, results: list[ChildAgentResult]) -> None:
        """把未被 session 级等待消费的结果放回各自父 run 队列。"""

        for result in results:
            self._result_queues[result.parent_run_id].put(result)

    def _discard_queued_results(self, parent_run_id: str, run_id: str) -> None:
        """移除同一 DSH Child Agent上一轮尚未消费的结果，避免追问收到旧 Turn。"""

        result_queue = self._result_queues[parent_run_id]
        retained: list[ChildAgentResult] = []
        while True:
            try:
                result = result_queue.get_nowait()
            except Empty:
                break
            if result.run_id != run_id:
                retained.append(result)
        for result in retained:
            result_queue.put(result)

    def _emit(self, event_name: str, record: ChildAgentRecord) -> None:
        """向可选事件观察者发送状态变化。"""

        event = self._event_from_record(event_name, record)
        if event is not None:
            self._event_queues_by_session[event.session_id].put(event)
        if self._event_callback is not None:
            self._event_callback(event_name, record)

    @staticmethod
    def _event_from_record(event_name: str, record: ChildAgentRecord) -> ChildAgentEvent | None:
        """从固定 Turn 快照构造事件，供普通通知与终态原子发布共用。"""

        session_id = record.contract.session_id
        if not session_id:
            return None
        result = record.result
        return ChildAgentEvent(
            event_name=event_name,
            run_id=record.run_id,
            session_id=session_id,
            parent_run_id=record.contract.parent_run_id,
            goal=record.contract.goal,
            mode=record.contract.mode,
            status=record.status,
            access_mode=record.effective_access_mode,
            allowed_tools=tuple(sorted(record.effective_tools)),
            created_at=time.time(),
            category=record.contract.category,
            name=record.contract.name,
            provider=record.contract.provider,
            summary=result.summary if result is not None else "",
            result=result.result if result is not None else None,
            error=result.error if result is not None else None,
        )
