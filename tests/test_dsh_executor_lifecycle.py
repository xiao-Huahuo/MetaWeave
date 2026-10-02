"""用可控事件验证 DSH 启动、取消、并发容量和异常回收。

测试不访问模型或启动真实端口；假 SDK 严格停在握手/Turn边界，所有测试线程均有界回收。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.services.child_agent.types import ChildAgentExecutionContext, ChildAgentStopped
from agent_service.services.dsh_adapter.executor import DshChildAgentExecutor, _RuntimeStartup


class _Control:
    """每个测试 Runtime 独立拥有的握手、Turn和关闭屏障。"""

    def __init__(self, *, blocked_start: bool = False, blocked_turn: bool = False) -> None:
        """按需要阻塞启动或 Turn，关闭时始终释放全部屏障。"""

        self.started = threading.Event()
        self.start_ready = threading.Event()
        self.turn_started = threading.Event()
        self.turn_ready = threading.Event()
        self.closed = threading.Event()
        self.fail_start = False
        self.fail_close = False
        self.instances = 0
        if not blocked_start:
            self.start_ready.set()
        if not blocked_turn:
            self.turn_ready.set()


def _executor(monkeypatch, tmp_path: Path, controls: dict[str, _Control], *, capacity: int = 2):
    """创建真实执行器，替换 SDK与资源包以观察租约和进程所有权。"""

    leases: set[str] = set()
    released: list[str] = []

    def acquire(owner: str, **_kwargs):
        """模拟按 owner租用安装好的 Runtime。"""

        leases.add(owner)
        return tmp_path / "node.exe"

    def release(owner: str):
        """记录清理路径并允许幂等释放。"""

        leases.discard(owner)
        released.append(owner)

    class Harness:
        """只实现执行器实际使用的 SDK协议，握手可由测试释放。"""

        def __init__(self, config):
            """通过每 run的 Runtime工作目录定位独立屏障。"""

            self.config = config
            self.control = controls[Path(config.runtime_cwd).name]
            self.control.instances += 1
            self.initialize_response = SimpleNamespace(serverInfo=SimpleNamespace(
                name="deepseek-harness-sdk-runtime",
                capabilities=["mw-session-open-v1", "mw-session-flush-v1", "mw-tools-v1"],
            ))
            self.client = SimpleNamespace(stderr_lines=[], request=self.request)

        def start(self):
            """模拟一直不回复的 initialize握手及其运输层关闭。"""

            self.control.started.set()
            assert self.control.start_ready.wait(3), "test startup barrier timed out"
            if self.control.fail_start or self.control.closed.is_set():
                raise RuntimeError("initialization failed")

        def request(self, _method, *_args, **_kwargs):
            """提供成功 Session打开/flush响应。"""

            return SimpleNamespace(disposition="created", durableSeq=1, tools=["read", "read_image", "write", "edit", "pwsh"])

        def start_session(self, _session_id):
            """返回当前 harness的可控 Turn执行入口。"""

            return SimpleNamespace(run=self.run)

        def run(self, _goal):
            """模拟 SDK阻塞通知等待；关闭 Runtime会打断该等待。"""

            self.control.turn_started.set()
            assert self.control.turn_ready.wait(3), "test turn barrier timed out"
            if self.control.closed.is_set():
                raise RuntimeError("turn transport closed")
            return SimpleNamespace(finish_reason="completed", final_response="done")

        def close(self):
            """使启动和执行线程均可退出，并可模拟 SDK清理本身报错。"""

            self.control.closed.set()
            self.control.start_ready.set()
            self.control.turn_ready.set()
            if self.control.fail_close:
                raise RuntimeError("secondary close failed")

    monkeypatch.setattr("agent_service.services.dsh_adapter.executor.DeepSeekHarness", Harness)
    config = AgentConfig.load_config(
        overrides={"storage": {"base_data_dir": str(tmp_path)}, "dsh": {"max_live_runtimes": capacity}},
        load_env=False, load_dotenv=False, ensure_models=False,
    )
    settings = SimpleNamespace(get_llm_config=lambda **_kwargs: {
        "effective_model_source": "remote", "effective_model_name": "deepseek-chat",
        "effective_base_url": "https://example.invalid", "effective_api_key": "test-credential",
    })
    runtime = SimpleNamespace(
        acquire_runtime=acquire, release_runtime=release,
        resolve_launcher=lambda: tmp_path / "launcher.exe",
        resolve_runtime_launch_args=lambda _access: (str(tmp_path / "node.exe"),),
    )
    return DshChildAgentExecutor(config=config, settings_service=settings, runtime_manager=runtime), leases, released


def _context(run_id: str, tmp_path: Path) -> ChildAgentExecutionContext:
    """创建带独立取消事件的 DSH任务上下文。"""

    return ChildAgentExecutionContext(
        run_id=run_id, parent_run_id="parent-1", goal="verify lifecycle", user_id="u1",
        session_id="session-1", agent_mode="react", allowed_tools=frozenset(),
        access_mode="sandbox", input_refs=(), output_contract={},
        cancellation=threading.Event(), provider="dsh", workspace_root=str(tmp_path),
    )


def _launch(callback: Callable[[], object]):
    """保存子线程结果，失败时亦在主测试线程中检验原异常。"""

    output: list[object] = []

    def invoke():
        """避免未捕获线程异常干扰 pytest结果。"""

        try:
            output.append(callback())
        except Exception as exc:
            output.append(exc)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    return worker, output


def _finish(executor, controls: dict[str, _Control], workers):
    """即使红测失败，也先释放屏障并回收所有测试线程。"""

    for control in controls.values():
        control.start_ready.set()
        control.turn_ready.set()
    for worker in workers:
        worker.join(timeout=4)
        assert not worker.is_alive()
    executor.shutdown()


def test_startup_failure_preserves_error_and_releases_lease_when_close_fails(monkeypatch, tmp_path):
    """清理报错不得掩盖原握手错误或遗留 Runtime租约。"""

    control = _Control()
    control.fail_start = control.fail_close = True
    executor, leases, released = _executor(monkeypatch, tmp_path, {"run-1": control})
    with pytest.raises(RuntimeError, match="initialization failed"):
        executor(_context("run-1", tmp_path))
    assert not leases
    assert released == ["run-1"]
    assert control.closed.is_set()


def test_cancellation_interrupts_unanswered_startup(monkeypatch, tmp_path):
    """取消监视应覆盖 initialize握手，而非只在 Turn开始后生效。"""

    controls = {"run-1": _Control(blocked_start=True)}
    executor, leases, _ = _executor(monkeypatch, tmp_path, controls)
    context = _context("run-1", tmp_path)
    worker, output = _launch(lambda: executor(context))
    try:
        assert controls["run-1"].started.wait(1)
        context.cancellation.set()
        assert controls["run-1"].closed.wait(0.75)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert isinstance(output[0], ChildAgentStopped)
        assert not leases
    finally:
        _finish(executor, controls, [worker])


def test_stalled_startup_does_not_block_independent_child(monkeypatch, tmp_path):
    """一个 Runtime等待握手期间，另一个 run应独立启动和完成。"""

    controls = {"run-1": _Control(blocked_start=True), "run-2": _Control()}
    executor, _, _ = _executor(monkeypatch, tmp_path, controls)
    first, _ = _launch(lambda: executor(_context("run-1", tmp_path)))
    workers = [first]
    try:
        assert controls["run-1"].started.wait(1)
        second, output = _launch(lambda: executor(_context("run-2", tmp_path)))
        workers.append(second)
        assert controls["run-2"].turn_started.wait(0.75)
        second.join(timeout=1)
        assert output == ["done"]
        assert not controls["run-1"].closed.is_set()
    finally:
        _finish(executor, controls, workers)


def test_pending_startup_owns_capacity_slot(monkeypatch, tmp_path):
    """尚未发布热句柄的启动也占用容量，容量拒绝不得等待别的握手。"""

    controls = {"run-1": _Control(blocked_start=True), "run-2": _Control()}
    executor, _, _ = _executor(monkeypatch, tmp_path, controls, capacity=1)
    first, _ = _launch(lambda: executor(_context("run-1", tmp_path)))
    workers = [first]
    try:
        assert controls["run-1"].started.wait(1)
        second, output = _launch(lambda: executor(_context("run-2", tmp_path)))
        workers.append(second)
        second.join(timeout=0.75)
        assert not second.is_alive()
        assert isinstance(output[0], RuntimeError)
        assert "容量" in str(output[0])
        assert controls["run-2"].instances == 0
    finally:
        _finish(executor, controls, workers)


@pytest.mark.parametrize("phase", ["startup", "turn"])
def test_runtime_timeouts_close_owned_resource(monkeypatch, tmp_path, phase):
    """握手与整个 Turn分别使用独立超时，并结束为失败异常。"""

    controls = {"run-1": _Control(blocked_start=phase == "startup", blocked_turn=phase == "turn")}
    executor, leases, _ = _executor(monkeypatch, tmp_path, controls)
    executor.config.dsh.startup_timeout_seconds = 0.15
    executor.config.dsh.turn_timeout_seconds = 0.15
    worker, output = _launch(lambda: executor(_context("run-1", tmp_path)))
    try:
        assert controls["run-1"].started.wait(1)
        assert controls["run-1"].closed.wait(0.75)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert isinstance(output[0], TimeoutError)
        assert not leases
    finally:
        _finish(executor, controls, [worker])


def test_shutdown_interrupts_pending_handshake(monkeypatch, tmp_path):
    """应用退出可以访问启动中的 owner，不能死锁在执行器全局锁。"""

    controls = {"run-1": _Control(blocked_start=True)}
    executor, leases, _ = _executor(monkeypatch, tmp_path, controls)
    first, _ = _launch(lambda: executor(_context("run-1", tmp_path)))
    workers = [first]
    try:
        assert controls["run-1"].started.wait(1)
        closer, output = _launch(executor.shutdown)
        workers.append(closer)
        closer.join(timeout=0.75)
        assert not closer.is_alive()
        assert output == [None]
        first.join(timeout=1)
        assert not first.is_alive()
        assert not leases
    finally:
        _finish(executor, controls, workers)


def test_concurrent_same_run_starts_only_one_runtime(monkeypatch, tmp_path):
    """同 run的冷恢复并发请求复用一次启动，不能创建两条 Runtime。"""

    controls = {"run-1": _Control(blocked_start=True)}
    executor, leases, _ = _executor(monkeypatch, tmp_path, controls)
    context = _context("run-1", tmp_path)
    first, first_output = _launch(lambda: executor._get_or_start(context))
    workers = [first]
    try:
        assert controls["run-1"].started.wait(1)
        second, second_output = _launch(lambda: executor._get_or_start(context))
        workers.append(second)
        controls["run-1"].start_ready.set()
        first.join(timeout=1)
        second.join(timeout=1)
        assert not first.is_alive() and not second.is_alive()
        assert first_output[0] is second_output[0]
        assert controls["run-1"].instances == 1
        assert leases == {"run-1"}
    finally:
        _finish(executor, controls, workers)


def test_running_turn_cancellation_releases_lease(monkeypatch, tmp_path):
    """Turn已进入通知等待后，取消仍关闭资源并以 stopped异常结束。"""

    controls = {"run-1": _Control(blocked_turn=True)}
    executor, leases, released = _executor(monkeypatch, tmp_path, controls)
    context = _context("run-1", tmp_path)
    worker, output = _launch(lambda: executor(context))
    try:
        assert controls["run-1"].turn_started.wait(1)
        context.cancellation.set()
        assert controls["run-1"].closed.wait(0.75)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert isinstance(output[0], ChildAgentStopped)
        assert not leases and released == ["run-1"]
    finally:
        _finish(executor, controls, [worker])


def test_same_run_double_call_does_not_reenter_session(monkeypatch, tmp_path):
    """拒绝同一 run的第二个执行调用，同时保留第一个已运行的 Turn。"""

    controls = {"run-1": _Control(blocked_turn=True)}
    executor, _, _ = _executor(monkeypatch, tmp_path, controls)
    worker, output = _launch(lambda: executor(_context("run-1", tmp_path)))
    try:
        assert controls["run-1"].turn_started.wait(1)
        with pytest.raises(RuntimeError, match="仍在运行"):
            executor(_context("run-1", tmp_path))
        assert not controls["run-1"].closed.is_set()
        controls["run-1"].turn_ready.set()
        worker.join(timeout=1)
        assert output == ["done"]
        assert controls["run-1"].instances == 1
    finally:
        _finish(executor, controls, [worker])


def test_shutdown_wakes_waiters_for_pending_run(monkeypatch, tmp_path):
    """shutdown唤醒同 run启动等待者，并阻止 owner在退出后发布热句柄。"""

    controls = {"run-1": _Control(blocked_start=True)}
    executor, leases, _ = _executor(monkeypatch, tmp_path, controls)
    first, first_output = _launch(lambda: executor._get_or_start(_context("run-1", tmp_path)))
    workers = [first]
    try:
        assert controls["run-1"].started.wait(1)
        second, second_output = _launch(lambda: executor._get_or_start(_context("run-1", tmp_path)))
        workers.append(second)
        executor.shutdown()
        first.join(timeout=1)
        second.join(timeout=1)
        assert not first.is_alive() and not second.is_alive()
        assert isinstance(first_output[0], (RuntimeError, ChildAgentStopped))
        assert isinstance(second_output[0], ChildAgentStopped)
        assert not leases and not executor._handles and not executor._starting
    finally:
        _finish(executor, controls, workers)


@pytest.mark.parametrize("name", ["startup_timeout_seconds", "turn_timeout_seconds", "shutdown_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_dsh_deadlines_reject_nonfinite_or_nonpositive_values(name, value):
    """配置边界拒绝会恢复无限等待或使超时失效的数值。"""

    with pytest.raises(ValueError, match=name):
        AgentConfig.DshConfig(**{name: value})


def test_dsh_deadlines_load_from_environment(monkeypatch, tmp_path):
    """服务级期限完整走 AgentConfig的环境变量入口。"""

    for key, value in {
        "AGENT_DSH_STARTUP_TIMEOUT_SECONDS": "0.5", "AGENT_DSH_TURN_TIMEOUT_SECONDS": "2.5",
        "AGENT_DSH_SHUTDOWN_TIMEOUT_SECONDS": "0.2",
    }.items():
        monkeypatch.setenv(key, value)
    config = AgentConfig.load_config(
        overrides={"storage": {"base_data_dir": str(tmp_path)}},
        load_env=True, load_dotenv=False, ensure_models=False,
    )
    assert config.dsh.startup_timeout_seconds == 0.5
    assert config.dsh.turn_timeout_seconds == 2.5
    assert config.dsh.shutdown_timeout_seconds == 0.2


@pytest.mark.parametrize("action", ["cancel", "shutdown"])
def test_process_created_during_cancellation_is_reaped(monkeypatch, tmp_path, action):
    """Popen返回前取消/退出，也必须回收尚未赋给 SDK的原始进程。"""

    executor, _, _ = _executor(monkeypatch, tmp_path, {})
    startup = _RuntimeStartup(context=_context("run-1", tmp_path))
    entered = threading.Event()
    release = threading.Event()
    terminated: list[bool] = []
    waited: list[float] = []
    process = SimpleNamespace(
        poll=lambda: 0 if terminated else None,
        terminate=lambda: terminated.append(True),
        kill=lambda: pytest.fail("terminate should succeed"),
        wait=lambda *, timeout: waited.append(timeout) or 0,
    )

    def create(*_args, **_kwargs):
        """在进程已存在但 SDK尚未拿到 Popen引用时阻塞。"""

        entered.set()
        assert release.wait(3)
        return process

    monkeypatch.setattr("agent_service.services.dsh_adapter.executor.subprocess.Popen", create)
    worker, output = _launch(lambda: executor._create_process(startup, ["fake-runtime"]))
    try:
        assert entered.wait(1)
        if action == "cancel":
            startup.context.cancellation.set()
        else:
            executor.shutdown()
        release.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert isinstance(output[0], ChildAgentStopped)
        assert terminated == [True]
        assert waited == [executor.config.dsh.shutdown_timeout_seconds]
    finally:
        release.set()
        worker.join(timeout=4)
        executor.shutdown()


def test_close_failure_still_terminates_registered_process(monkeypatch, tmp_path):
    """SDK.close报错后 executor仍负责原始 launcher进程的结束。"""

    executor, _, _ = _executor(monkeypatch, tmp_path, {})
    terminated: list[bool] = []
    process = SimpleNamespace(
        poll=lambda: 0 if terminated else None,
        terminate=lambda: terminated.append(True), wait=lambda *, timeout: 0,
    )
    harness = SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close failed")))
    executor._close_harness(harness, "run-1", process)
    assert terminated == [True]
    executor.shutdown()
