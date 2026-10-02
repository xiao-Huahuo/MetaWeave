"""DSH 子 Agent Runtime 异常回收测试。

功能说明：
验证 Runtime 已启动但 Turn 执行失败时，执行器关闭句柄并释放 PackageManager 租约，
避免后续修复、卸载和新子 Agent 永久被“正在使用”阻塞。
"""

from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from agent_service.services.dsh_adapter.executor import DshChildAgentExecutor, _RuntimeHandle
from agent_service.services.child_agent.manager import ChildAgentManager
from agent_service.services.child_agent.types import ChildAgentContract, ChildAgentStatus
from agent_service.vendor.deepseek_harness.api import RunResult


def _lifecycle_state(executor: DshChildAgentExecutor) -> None:
    """为只注入热句柄的测试补齐执行器容量与执行所有权状态。"""

    executor.config = SimpleNamespace(dsh=SimpleNamespace(
        startup_timeout_seconds=120, turn_timeout_seconds=1800, shutdown_timeout_seconds=1,
    ))
    executor._starting = {}
    executor._closing = {}
    executor._active = {}
    executor._closed = False


def test_failed_turn_releases_runtime_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DSH Turn 抛错后应移除热句柄、关闭进程并释放同一 run_id 租约。"""

    released: list[str] = []
    harness = SimpleNamespace(
        close=lambda: None,
        start_session=lambda _session_id: SimpleNamespace(
            run=lambda _goal: (_ for _ in ()).throw(RuntimeError("runtime failed"))
        ),
        client=SimpleNamespace(stderr_lines=[]),
    )
    handle = _RuntimeHandle(
        harness=harness,
        session_id="session-1",
        session_root=tmp_path,
        web_url_file=tmp_path / "web-url.txt",
        web_token="token",
        access_mode="sandbox",
        user_id="u1",
    )
    executor = DshChildAgentExecutor.__new__(DshChildAgentExecutor)
    _lifecycle_state(executor)
    executor._lock = threading.RLock()
    executor._handles = {"run-1": handle}
    executor.runtime_manager = SimpleNamespace(release_runtime=released.append)
    monkeypatch.setattr(executor, "_get_or_start", lambda _context: handle)
    monkeypatch.setattr(executor, "_refresh_web_url", lambda _handle: None)
    context = SimpleNamespace(
        run_id="run-1",
        goal="fail",
        cancellation=threading.Event(),
        raise_if_stopped=lambda: None,
        publish_tools=lambda _tools: None,
        allowed_tools=frozenset(),
        access_mode="sandbox",
        workspace_root=str(tmp_path),
        input_refs=(),
        output_contract={},
    )

    with pytest.raises(RuntimeError, match="runtime failed"):
        executor(context)

    assert "run-1" not in executor._handles
    assert released == ["run-1"]


@pytest.mark.parametrize(
    ("finish_reason", "cancelled", "expected_status"),
    [
        ("completed", False, ChildAgentStatus.COMPLETED),
        ("error", False, ChildAgentStatus.FAILED),
        ("aborted", False, ChildAgentStatus.FAILED),
        ("blocked", False, ChildAgentStatus.FAILED),
        ("max-tokens", False, ChildAgentStatus.FAILED),
        (None, False, ChildAgentStatus.FAILED),
        ("unexpected", False, ChildAgentStatus.FAILED),
        ("aborted", True, ChildAgentStatus.STOPPED),
    ],
)
def test_runtime_terminal_reason_controls_child_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    finish_reason: str | None,
    cancelled: bool,
    expected_status: ChildAgentStatus,
) -> None:
    """SDK 返回失败终态也必须标为 failed；取消保留 stopped，成功保留热会话。"""

    released: list[str] = []
    flushed: list[str] = []
    closed: list[bool] = []
    reason = {"kind": finish_reason, "error": {"message": "private-provider-context"}}
    result = RunResult(
        session_id="session-1",
        final_response="partial or complete response",
        finish_reason=finish_reason,
        events=[{"type": "turn/end", "data": {"reason": reason}}],
        notifications=[],
    )
    harness = SimpleNamespace(
        close=lambda: closed.append(True),
        start_session=lambda _session_id: SimpleNamespace(run=lambda _goal: result),
        client=SimpleNamespace(
            stderr_lines=[],
            request=lambda method, *_args, **_kwargs: flushed.append(method),
        ),
    )
    handle = _RuntimeHandle(
        harness=harness,
        session_id="session-1",
        session_root=tmp_path,
        web_url_file=tmp_path / "web-url.txt",
        web_token="token",
        access_mode="sandbox",
        user_id="u1",
    )
    executor = DshChildAgentExecutor.__new__(DshChildAgentExecutor)
    _lifecycle_state(executor)
    executor._lock = threading.RLock()
    executor._handles = {}
    executor.runtime_manager = SimpleNamespace(release_runtime=released.append)

    def start(context):
        """绑定 manager 生成的 run_id，并在 SDK 返回前模拟已收到的取消。"""

        executor._handles[context.run_id] = handle
        if cancelled:
            context.cancellation.set()
        return handle

    monkeypatch.setattr(executor, "_get_or_start", start)
    manager = ChildAgentManager(max_workers=1)
    try:
        record = manager.spawn(
            contract=ChildAgentContract(
                goal="verify terminal result", parent_run_id="parent-1", user_id="u1",
                session_id="session-1", provider="dsh", mode="foreground",
            ),
            executor=executor,
        )
        assert record.status == expected_status
        assert flushed == ([] if cancelled else ["session/flush"])
        assert record.result is not None
        assert "private-provider-context" not in (record.result.error or "")
        if expected_status == ChildAgentStatus.COMPLETED:
            assert record.result.result == result.final_response
            assert record.run_id in executor._handles
            assert not released and not closed
        else:
            assert record.run_id not in executor._handles
            assert released == [record.run_id]
            assert closed == [True]
    finally:
        manager.close()
        executor.shutdown()
