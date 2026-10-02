"""
子 Agent 管理器测试。

功能说明:
使用不依赖真实 LLM 的假执行器验证子任务合同、权限继承、生命周期、前后台模式、
按父级隔离的结果队列、上下文更新和协作式停止。
"""

from __future__ import annotations

from threading import Barrier, Event, Thread
import time

import pytest

from agent_service.services.child_agent import manager as manager_module
from agent_service.services.child_agent import (
    ChildAgentContract,
    ChildAgentEvent,
    ChildAgentManager,
    ChildAgentStatus,
)


def _contract(parent_run_id: str = "parent_1", **kwargs: object) -> ChildAgentContract:
    """构造测试用子任务合同。"""

    return ChildAgentContract(
        goal=str(kwargs.pop("goal", "完成测试任务")),
        parent_run_id=parent_run_id,
        **kwargs,
    )


def test_foreground_child_waits_and_returns_result() -> None:
    """前台子 Agent 应在 spawn 返回前完成。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground"),
            executor=lambda context: "完成",
            parent_tools=frozenset({"read_file"}),
            parent_access_mode="sandbox",
        )
        assert record.status == ChildAgentStatus.COMPLETED
        assert record.result is not None
        assert record.result.result == "完成"
        assert manager.drain_results("parent_1")[0].status == ChildAgentStatus.COMPLETED
    finally:
        manager.close()


def test_child_category_is_passed_through() -> None:
    """子 Agent 类别应透传到执行上下文、记录与生命周期事件。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", category="explore", session_id="session_cat"),
            executor=lambda context: context.category,
            parent_tools=frozenset({"read_file", "write_file"}),
            parent_access_mode="sandbox",
        )
        assert record.contract.category == "explore"
        assert record.context is not None
        assert record.context.category == "explore"
        assert record.result is not None
        assert record.result.result == "explore"
        events = manager.drain_events_for_session("session_cat")
        assert len(events) >= 2
        assert all(event.category == "explore" for event in events)
    finally:
        manager.close()


def test_child_name_is_passed_through() -> None:
    """子 Agent 名字应透传到执行上下文、记录与生命周期事件。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", name="plan1", session_id="session_name"),
            executor=lambda context: context.name,
            parent_tools=frozenset({"read_file"}),
            parent_access_mode="sandbox",
        )
        assert record.contract.name == "plan1"
        assert record.context is not None
        assert record.context.name == "plan1"
        assert record.result is not None
        assert record.result.result == "plan1"
        events = manager.drain_events_for_session("session_name")
        assert len(events) >= 2
        assert all(event.name == "plan1" for event in events)
    finally:
        manager.close()


def test_dsh_child_can_continue_with_same_run_id() -> None:
    """DSH追问应复用 Child Agent身份并把新 Prompt交给原执行器。"""

    manager = ChildAgentManager()
    prompts: list[str] = []
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", provider="dsh", session_id="session_dsh"),
            executor=lambda context: prompts.append(context.goal) or context.goal,
            parent_tools=frozenset({"dsh.read"}),
            parent_access_mode="sandbox",
        )
        continued = manager.continue_child(run_id=record.run_id, prompt="修复失败测试", mode="foreground")
        assert continued.run_id == record.run_id
        assert prompts == [record.contract.goal, "修复失败测试"]
        assert continued.result is not None
        assert continued.result.result == "修复失败测试"
    finally:
        manager.close()


def test_child_completion_wakeup_claim_is_once_per_turn() -> None:
    """多个观察者只能有一个领取同一 Turn 的终态唤醒，追问后的新 Turn 可再次领取。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", provider="dsh", session_id="session_dsh"),
            executor=lambda context: context.goal,
        )

        barrier = Barrier(3)
        claims: list[bool] = []

        def claim() -> None:
            barrier.wait()
            claims.append(manager.claim_completion_wakeup(record.run_id))

        observers = [Thread(target=claim), Thread(target=claim)]
        for observer in observers:
            observer.start()
        barrier.wait()
        for observer in observers:
            observer.join(timeout=1)

        assert sorted(claims) == [False, True]
        assert manager.claim_completion_wakeup(record.run_id) is False

        manager.continue_child(run_id=record.run_id, prompt="继续检查", mode="foreground")

        assert manager.claim_completion_wakeup(record.run_id) is True
        assert manager.claim_completion_wakeup(record.run_id) is False
    finally:
        manager.close()


def test_concurrent_dsh_continuations_reserve_only_one_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个续问同时通过旧终态检查时，只能预留和执行一个新 Turn。"""

    manager = ChildAgentManager(max_workers=2)
    reserving = Event()
    competing = Event()
    release_reservation = Event()
    release_turn = Event()
    outcomes: list[str] = []
    prompts: list[str] = []
    callers: list[Thread] = []

    def execute(context):
        """保持新 Turn 活动，防止另一续问在首个新 Turn 完成后合法启动。"""

        prompts.append(context.goal)
        if context.goal != "初始任务":
            release_turn.wait(timeout=2)
        return context.goal

    def reserve_cancellation():
        """在检查终态与写入 CREATED 之间暂停第一个续问。"""

        if not reserving.is_set():
            reserving.set()
            release_reservation.wait(timeout=2)
        else:
            competing.set()
        return Event()

    def continue_turn(run_id: str, prompt: str) -> None:
        """记录续问是否真正被接受。"""

        try:
            manager.continue_child(run_id=run_id, prompt=prompt)
            outcomes.append("accepted")
        except RuntimeError:
            outcomes.append("rejected")

    try:
        record = manager.spawn(
            contract=_contract(goal="初始任务", mode="foreground", provider="dsh"),
            executor=execute,
        )
        monkeypatch.setattr(manager_module, "Event", reserve_cancellation)
        callers = [
            Thread(target=continue_turn, args=(record.run_id, "续问 A")),
            Thread(target=continue_turn, args=(record.run_id, "续问 B")),
        ]
        callers[0].start()
        assert reserving.wait(timeout=1)
        callers[1].start()
        competing.wait(timeout=0.2)
        release_reservation.set()
        for caller in callers:
            caller.join(timeout=1)
        assert all(not caller.is_alive() for caller in callers)
        assert sorted(outcomes) == ["accepted", "rejected"]
        release_turn.set()
        manager.close()
        assert len(prompts) == 2
    finally:
        release_reservation.set()
        release_turn.set()
        for caller in callers:
            if caller.ident is not None:
                caller.join(timeout=1)
        manager.close()


def test_background_children_run_concurrently_and_queue_results() -> None:
    """后台子 Agent 不阻塞父调用,并且同一父级可并发收集多个结果。"""

    manager = ChildAgentManager(max_workers=2)
    started = Event()
    release = Event()

    def worker(context):
        started.set()
        release.wait(timeout=2)
        return context.goal

    try:
        first = manager.spawn(
            contract=_contract(goal="任务 A"),
            executor=worker,
            parent_tools=frozenset({"read_file"}),
        )
        second = manager.spawn(
            contract=_contract(goal="任务 B"),
            executor=worker,
            parent_tools=frozenset({"read_file"}),
        )
        assert started.wait(timeout=1)
        assert first.status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING}
        assert second.status in {ChildAgentStatus.CREATED, ChildAgentStatus.RUNNING}
        assert manager.drain_results("parent_1") == []
        release.set()
        collected = []
        deadline = time.time() + 2
        while len(collected) < 2 and time.time() < deadline:
            collected.extend(manager.drain_results("parent_1"))
            time.sleep(0.01)
        assert {result.result for result in collected} == {"任务 A", "任务 B"}
    finally:
        release.set()
        manager.close()


def test_dsh_continuation_submission_failure_reaches_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """线程池拒绝续问提交时，新 Turn 必须进入失败终态并投递失败结果。"""

    manager = ChildAgentManager()

    def reject_submission(*args, **kwargs):
        """模拟关闭或异常退出后的线程池提交失败。"""

        raise RuntimeError("test submission rejected")

    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", provider="dsh"),
            executor=lambda context: "完成",
        )
        monkeypatch.setattr(manager._executor, "submit", reject_submission)
        with pytest.raises(RuntimeError):
            manager.continue_child(run_id=record.run_id, prompt="继续任务")
        assert record.status == ChildAgentStatus.FAILED
        assert record.result is not None
        results = manager.drain_results("parent_1")
        assert len(results) == 1
        assert results[0].status == ChildAgentStatus.FAILED
    finally:
        manager.close()


def test_terminal_publication_waits_for_callback_before_continuation() -> None:
    """终态落库完成后才允许结果消费、自动唤醒和新父 run 续问。"""

    completing = Event()
    release_completion = Event()
    persisted: list[tuple[str, str]] = []

    def on_event(event_name, record):
        """模拟旧 Turn 的慢数据库回调，记录真实完成的写入顺序。"""

        if event_name == "child_agent.completed":
            if not completing.is_set():
                completing.set()
                release_completion.wait(timeout=2)
            persisted.append((record.contract.parent_run_id, record.result.summary))

    manager = ChildAgentManager(max_workers=2, event_callback=on_event)
    try:
        record = manager.spawn(
            contract=_contract(provider="dsh", session_id="session-dsh"),
            executor=lambda context: context.goal,
        )
        assert completing.wait(timeout=1)
        assert record.status == ChildAgentStatus.RUNNING
        assert manager.claim_completion_wakeup(record.run_id) is False
        assert manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=0.05) is None
        events = manager.drain_events_for_session("session-dsh")
        assert all(event.status != ChildAgentStatus.COMPLETED for event in events)
        with pytest.raises(RuntimeError, match="仍在运行"):
            manager.continue_child(run_id=record.run_id, prompt="续问", parent_run_id="new-parent")
        assert record.contract.parent_run_id == "parent_1"
        release_completion.set()
        manager._futures[record.run_id].result(timeout=1)
        result = manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=1)
        assert result is not None
        assert result.summary == "完成测试任务"
        events = manager.drain_events_for_session("session-dsh")
        assert len(events) == 1
        assert events[0].status == ChildAgentStatus.COMPLETED
        assert manager.claim_completion_wakeup(record.run_id) is True
        assert manager.claim_completion_wakeup(record.run_id) is False
        manager.continue_child(
            run_id=record.run_id,
            prompt="续问",
            parent_run_id="new-parent",
            mode="foreground",
        )
        assert persisted == [("parent_1", "完成测试任务"), ("new-parent", "续问")]
        assert manager.claim_completion_wakeup(record.run_id) is True
        assert manager.claim_completion_wakeup(record.run_id) is False
    finally:
        release_completion.set()
        manager.close()


def test_terminal_callback_failure_still_publishes_result_and_event() -> None:
    """终态回调异常也必须释放活动态并发布一次结果、通知及唤醒资格。"""

    snapshots = []

    def on_event(event_name, record):
        """只在终态通知模拟持久化失败。"""

        if event_name == "child_agent.completed":
            snapshots.append(record)
            raise RuntimeError("test terminal callback failed")

    manager = ChildAgentManager(event_callback=on_event)
    try:
        with pytest.raises(RuntimeError, match="test terminal callback failed"):
            manager.spawn(
                contract=_contract(mode="foreground", session_id="session-dsh"),
                executor=lambda context: "完成",
            )
        record = manager.get(snapshots[0].run_id)
        assert record is not None
        assert record.status == ChildAgentStatus.COMPLETED
        result = manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=1)
        assert result is not None
        assert result.result == "完成"
        events = manager.drain_events_for_session("session-dsh")
        assert [event.status for event in events] == [
            ChildAgentStatus.CREATED,
            ChildAgentStatus.RUNNING,
            ChildAgentStatus.COMPLETED,
        ]
        assert manager.claim_completion_wakeup(record.run_id) is True
        assert manager.claim_completion_wakeup(record.run_id) is False
    finally:
        manager.close()


def test_wait_for_children_returns_one_result_at_a_time() -> None:
    """父 Agent 每次等待只应解除一个后台子 Agent 结果。"""

    manager = ChildAgentManager(max_workers=2)
    release = Event()

    def worker(context):
        release.wait(timeout=2)
        return context.goal

    try:
        first = manager.spawn(contract=_contract(goal="任务 A"), executor=worker)
        second = manager.spawn(contract=_contract(goal="任务 B"), executor=worker)
        release.set()
        first_result = manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=2)
        second_result = manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=2)
        assert first_result is not None
        assert second_result is not None
        assert {first_result.run_id, second_result.run_id} == {first.run_id, second.run_id}
        assert {first_result.status, second_result.status} == {ChildAgentStatus.COMPLETED}
    finally:
        release.set()
        manager.close()


def test_wait_for_children_returns_queued_result_immediately() -> None:
    """若子 Agent 已产出结果,父 Agent 后续等待应直接获取队列结果。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground"),
            executor=lambda context: "已经完成",
        )
        started_at = time.perf_counter()
        result = manager.wait_for_children(parent_run_id="parent_1", timeout_seconds=2)
        elapsed = time.perf_counter() - started_at
        assert result is not None
        assert result.run_id == record.run_id
        assert result.result == "已经完成"
        assert elapsed < 0.2
    finally:
        manager.close()


def test_wait_for_children_for_session_crosses_parent_run_ids() -> None:
    """自动唤醒产生新父 run 后，仍能等待同一 session 旧 run 创建的子 Agent。"""

    manager = ChildAgentManager()
    release = Event()
    try:
        record = manager.spawn(
            contract=_contract(parent_run_id="original-run", session_id="session-1"),
            executor=lambda context: release.wait(timeout=1) or "完成",
        )
        release.set()

        result = manager.wait_for_children_for_session(
            session_id="session-1",
            timeout_seconds=2,
        )

        assert result is not None
        assert result.run_id == record.run_id
    finally:
        release.set()
        manager.close()


def test_child_agent_events_are_queued_by_session() -> None:
    """子 Agent 生命周期事件应能按主会话投递给前端流。"""

    manager = ChildAgentManager()
    try:
        record = manager.spawn(
            contract=_contract(mode="foreground", session_id="session_1"),
            executor=lambda context: "完成",
        )
        events = manager.drain_events_for_session("session_1")
        assert [event.event_name for event in events] == [
            "child_agent.created",
            "child_agent.started",
            "child_agent.completed",
        ]
        assert {event.run_id for event in events} == {record.run_id}
        assert manager.drain_events_for_session("session_1") == []
    finally:
        manager.close()


def test_child_permissions_are_intersection_of_parent_and_contract() -> None:
    """子 Agent 不能获得父 Agent 没有的权限或工具。"""

    manager = ChildAgentManager()
    try:
        with pytest.raises(PermissionError):
            manager.spawn(
                contract=_contract(access_mode="full_access"),
                executor=lambda context: None,
                parent_tools=frozenset({"read_file"}),
                parent_access_mode="sandbox",
            )

        captured = []
        manager.spawn(
            contract=_contract(allowed_tools=frozenset({"read_file", "write_file"}), mode="foreground"),
            executor=lambda context: captured.append((context.allowed_tools, context.access_mode)),
            parent_tools=frozenset({"read_file"}),
            parent_access_mode="full_access",
        )
        assert captured == [(frozenset({"read_file"}), "sandbox")]
    finally:
        manager.close()


def test_child_cannot_spawn_another_child() -> None:
    """管理器应在服务端拒绝子 Agent 的嵌套召唤。"""

    manager = ChildAgentManager()
    try:
        with pytest.raises(PermissionError):
            manager.spawn(
                contract=_contract(),
                executor=lambda context: None,
                caller_is_child=True,
            )
    finally:
        manager.close()


def test_stop_and_context_update_are_observable_by_executor() -> None:
    """子 Agent 应能读取父级更新并响应协作式停止。"""

    manager = ChildAgentManager()
    ready = Event()
    stopped = Event()
    seen_updates: list[dict] = []

    def worker(context):
        ready.set()
        while True:
            seen_updates.extend(dict(item) for item in context.drain_updates())
            try:
                context.raise_if_stopped()
            except RuntimeError:
                stopped.set()
                raise
            time.sleep(0.01)

    try:
        record = manager.spawn(contract=_contract(), executor=worker)
        assert ready.wait(timeout=1)
        manager.update_context(record.run_id, {"kind": "new_information", "value": "继续"})
        manager.stop(record.run_id)
        assert stopped.wait(timeout=1)
        deadline = time.time() + 1
        while record.status != ChildAgentStatus.STOPPED and time.time() < deadline:
            time.sleep(0.01)
        assert record.status == ChildAgentStatus.STOPPED
        assert seen_updates == [{"kind": "new_information", "value": "继续"}]
    finally:
        manager.close()
