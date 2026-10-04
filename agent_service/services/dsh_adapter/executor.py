"""通过固定 Python SDK 驱动受管 DSH Windows Runtime。

一个 ``ChildAgentExecutionContext`` 对应一个稳定 DSH Session和热 Runtime；SDK
负责 JSON-RPC，PackageManager负责二进制，MW只在此处映射配置、权限与 Web入口。
"""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from agent_service.core.agent_config import AgentConfig
from agent_service.services.child_agent.types import ChildAgentExecutionContext, ChildAgentStopped
from agent_service.services.dsh_runtime import DshRuntimePackageManager
from agent_service.services.settings.service import SettingsService
from agent_service.vendor.deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

logger = logging.getLogger(__name__)


class _SessionOpenResponse(BaseModel):
    """MW固定 Runtime 的 ``session/open`` 成功响应。"""

    sessionId: str
    disposition: str
    durableSeq: int
    tools: list[str]


class _SessionFlushResponse(BaseModel):
    """MW固定 Runtime 的 ``session/flush`` 成功响应。"""

    sessionId: str
    durableSeq: int


@dataclass(slots=True)
class _RuntimeHandle:
    """保存一个 Child Agent 热 Runtime及其只读 Web访问材料。"""

    harness: DeepSeekHarness
    session_id: str
    session_root: Path
    web_url_file: Path
    web_token: str
    access_mode: str
    user_id: str
    process: subprocess.Popen[str] | None = None
    web_base_url: str = ""
    running: bool = False
    last_activity: float = 0.0
    tools: frozenset[str] = frozenset()


@dataclass(slots=True)
class _RuntimeStartup:
    """占用一个容量槽的启动 owner；SDK和进程在发布热句柄前也可取消。"""

    context: ChildAgentExecutionContext
    ready: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    close_done: threading.Event = field(default_factory=threading.Event)
    harness: DeepSeekHarness | None = None
    process: subprocess.Popen[str] | None = None
    stopped: bool = False
    close_started: bool = False
    error: Exception | None = None


@dataclass(slots=True)
class _ExecutionWatch:
    """区分启动期限与整个代码 Turn期限，超时必须以 failed结束。"""

    startup_deadline: float
    turn_deadline: float | None = None
    timed_out: threading.Event = field(default_factory=threading.Event)


class DshChildAgentExecutor:
    """复用热 DSH Runtime执行代码 Turn并提供对应只读 Web URL。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        settings_service: SettingsService,
        runtime_manager: DshRuntimePackageManager,
    ) -> None:
        """绑定 MW配置、用户模型设置与 Runtime资源管理器。"""

        self.config = config
        self.settings_service = settings_service
        self.runtime_manager = runtime_manager
        self.conversations_root = (Path(config.storage.base_data_dir) / "dsh" / "conversations").resolve()
        self.conversations_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._handles: dict[str, _RuntimeHandle] = {}
        self._starting: dict[str, _RuntimeStartup] = {}
        self._closing: dict[str, threading.Event] = {}
        self._active: dict[str, tuple[ChildAgentExecutionContext, threading.Event]] = {}
        self._closed = False

    def __call__(self, context: ChildAgentExecutionContext) -> str:
        """在当前 Child Agent的稳定 DSH Conversation中执行一个 Turn。"""

        context.raise_if_stopped()
        done = threading.Event()
        with self._lock:
            if self._closed:
                raise RuntimeError("DSH 执行器已关闭")
            if context.run_id in self._active:
                raise RuntimeError("DSH 子 Agent当前仍在运行")
            self._active[context.run_id] = (context, done)
        watch = _ExecutionWatch(time.monotonic() + self.config.dsh.startup_timeout_seconds)
        monitor = threading.Thread(
            target=self._monitor_cancellation,
            args=(context, done, watch),
            name=f"dsh-cancel-{context.run_id[-8:]}",
            daemon=True,
        )
        monitor.start()
        handle: _RuntimeHandle | None = None
        try:
            handle = self._get_or_start(context)
            context.raise_if_stopped()
            context.publish_tools(handle.tools)
            with self._lock:
                if self._handles.get(context.run_id) is not handle:
                    raise ChildAgentStopped("DSH 子 Agent Runtime已停止")
                handle.running = True
                handle.last_activity = time.monotonic()
            watch.turn_deadline = time.monotonic() + self.config.dsh.turn_timeout_seconds
            result = handle.harness.start_session(handle.session_id).run(self._build_prompt(context))
            handle.harness.client.request(
                "session/flush",
                {"sessionId": handle.session_id},
                response_model=_SessionFlushResponse,
            )
            context.raise_if_stopped()
            # SDK 的 idle 只表示当前 Turn 已停止，仍需验收真正的完成原因。
            # 只发布固定协议枚举，避免把提供商错误中的凭据或模型上下文持久化。
            if result.finish_reason != "completed":
                reason = (
                    result.finish_reason
                    if result.finish_reason in {"error", "aborted", "blocked", "max-tokens"}
                    else "invalid-terminal-reason"
                )
                raise RuntimeError(f"DSH 子 Agent任务未成功完成: {reason}")
            return result.final_response
        except Exception as exc:
            self.stop(context.run_id, cancel=False)
            if watch.timed_out.is_set():
                raise TimeoutError("DSH 子 Agent启动或任务执行超时") from exc
            if context.cancellation.is_set():
                raise ChildAgentStopped("DSH 子 Agent已停止") from exc
            raise
        finally:
            done.set()
            monitor.join(timeout=self.config.dsh.shutdown_timeout_seconds)
            if handle is not None:
                self._refresh_web_url(handle)
            with self._lock:
                self._active.pop(context.run_id, None)
                if handle is not None:
                    handle.running = False
                    handle.last_activity = time.monotonic()

    @staticmethod
    def session_id_for_run(run_id: str) -> str:
        """把稳定 MW Child Agent ID映射为规范 UUID格式的 DSH Session ID。"""

        return str(uuid5(NAMESPACE_URL, f"metaweave:dsh:{run_id}"))

    def web_url(self, *, run_id: str, user_id: str) -> str:
        """返回指定用户所属热 DSH Conversation的受限 Web URL。"""

        with self._lock:
            handle = self._handles.get(run_id)
            if handle is None:
                raise KeyError("DSH 子 Agent Runtime当前不在线")
            if handle.user_id != user_id:
                raise PermissionError("不能查看其他用户的 DSH 子 Agent")
            handle.last_activity = time.monotonic()
        self._refresh_web_url(handle)
        if not handle.web_base_url:
            raise RuntimeError("DSH Runtime尚未公布 Web地址")
        query = urlencode({
            "mw_token": handle.web_token,
            "session": handle.session_id,
            "readonly": "1",
        })
        return f"{handle.web_base_url.rstrip('/')}#{query}"

    def ensure_web(self, *, child: dict[str, Any], user_id: str) -> str:
        """冷恢复已持久化的 DSH Child Agent并返回只读 Web URL。"""

        if child.get("provider") != "dsh":
            raise ValueError("该子 Agent不是 DSH 类型")
        run_id = str(child.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("DSH 子 Agent缺少 run_id")
        with self._lock:
            online = run_id in self._handles
        if not online:
            context = ChildAgentExecutionContext(
                run_id=run_id,
                parent_run_id=str(child.get("parent_run_id") or ""),
                goal=str(child.get("goal") or "查看历史"),
                user_id=user_id,
                session_id=str(child.get("session_id") or ""),
                agent_mode="react",
                allowed_tools=frozenset(str(item) for item in child.get("allowed_tools") or []),
                access_mode=str(child.get("access_mode") or "sandbox"),
                input_refs=(),
                output_contract={},
                cancellation=threading.Event(),
                category=str(child.get("category") or "dsh"),
                name=str(child.get("name") or ""),
                provider="dsh",
                workspace_root=str(child.get("workspace_root") or ""),
            )
            self._get_or_start(context)
        deadline = time.monotonic() + 5
        while True:
            try:
                return self.web_url(run_id=run_id, user_id=user_id)
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    def stop(self, run_id: str, *, cancel: bool = True) -> None:
        """原子领取启动/热 Runtime的关闭权，再在锁外结束进程和释放租约。"""

        with self._lock:
            active = self._active.get(run_id)
            startup = self._starting.get(run_id)
            harness = None
            process = None
            if startup is not None:
                startup.stopped = True
                if startup.harness is not None and not startup.close_started:
                    startup.close_started = True
                    harness, process = startup.harness, startup.process
            handle = self._handles.pop(run_id, None)
            closing = threading.Event() if handle is not None else None
            if closing is not None:
                self._closing[run_id] = closing
        if cancel:
            if active is not None:
                active[0].cancellation.set()
            if startup is not None:
                startup.context.cancellation.set()
        if startup is not None:
            # 唤醒同 run等待者；容量槽和租约仍由原启动 owner回收。
            startup.ready.set()
            if harness is not None:
                try:
                    self._close_harness(harness, run_id, process)
                finally:
                    startup.close_done.set()
        if handle is not None:
            assert closing is not None
            self._finish_handle(run_id, handle, closing)

    def shutdown(self) -> None:
        """拒绝新启动，停止所有 owner并有界等待启动与执行线程退出。"""

        with self._lock:
            self._closed = True
            startups = list(self._starting.values())
            active_done = [item[1] for item in self._active.values()]
            closing_done = list(self._closing.values())
            run_ids = list(set(self._handles) | set(self._starting) | set(self._active))
        for run_id in run_ids:
            self.stop(run_id)
        deadline = time.monotonic() + self.config.dsh.shutdown_timeout_seconds
        for done in [*(item.finished for item in startups), *active_done, *closing_done]:
            if not done.wait(max(0, deadline - time.monotonic())):
                logger.warning("等待 DSH owner退出超时")

    def _get_or_start(self, context: ChildAgentExecutionContext) -> _RuntimeHandle:
        """每 run仅一个启动 owner；全局锁只保护容量、占位与热句柄发布。"""

        self._reap_idle()
        deadline = time.monotonic() + self.config.dsh.startup_timeout_seconds
        while True:
            context.raise_if_stopped()
            victim = None
            closing = None
            startup = None
            owner = False
            with self._lock:
                if self._closed:
                    raise ChildAgentStopped("DSH 执行器已关闭")
                existing = self._handles.get(context.run_id)
                if existing is not None:
                    if existing.user_id != context.user_id:
                        raise PermissionError("不能复用其他用户的 DSH Runtime")
                    if existing.access_mode == context.access_mode:
                        return existing
                    if existing.running:
                        raise RuntimeError("运行中的 DSH Runtime不能变更权限")
                    victim = (context.run_id, self._handles.pop(context.run_id))
                elif context.run_id in self._closing:
                    closing = self._closing[context.run_id]
                elif context.run_id in self._starting:
                    startup = self._starting[context.run_id]
                    if startup.context.user_id != context.user_id:
                        raise PermissionError("不能复用其他用户的 DSH Runtime")
                else:
                    live = len(self._handles) + len(self._starting) + len(self._closing)
                    if live >= self.config.dsh.max_live_runtimes:
                        idle = [
                            item for item in self._handles.items()
                            if not item[1].running and item[0] not in self._active
                        ]
                        if not idle:
                            raise RuntimeError("DSH Runtime容量已满，当前 Runtime均在运行或启动")
                        victim_id, victim_handle = min(idle, key=lambda item: item[1].last_activity)
                        self._handles.pop(victim_id)
                        victim = (victim_id, victim_handle)
                    else:
                        startup = _RuntimeStartup(context=context)
                        self._starting[context.run_id] = startup
                        owner = True
                if victim is not None:
                    closing = threading.Event()
                    self._closing[victim[0]] = closing
            if victim is not None:
                assert closing is not None
                self._finish_handle(*victim, closing)
                continue
            if owner:
                assert startup is not None
                return self._start_runtime(startup, deadline=deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("等待 DSH Runtime启动超时")
            ready = startup.ready if startup is not None else closing
            assert ready is not None
            if not ready.wait(min(0.1, remaining)):
                continue
            if startup is not None:
                if startup.error is not None:
                    raise startup.error
                if startup.stopped:
                    raise ChildAgentStopped("DSH 子 Agent启动已停止")

    def _start_runtime(self, startup: _RuntimeStartup, *, deadline: float) -> _RuntimeHandle:
        """在锁外安装、读取模型、创建进程和握手；未发布资源由启动 owner负责释放。"""

        context = startup.context
        leased = False
        published = False
        error: Exception | None = None
        try:
            self.runtime_manager.acquire_runtime(context.run_id, cancellation=context.cancellation)
            leased = True
            context.raise_if_stopped()
            launcher = self.runtime_manager.resolve_launcher()
            runtime_args = self.runtime_manager.resolve_runtime_launch_args(context.access_mode)
            model = self._resolve_model(context.user_id)
            workspace = self._resolve_workspace(context.workspace_root)
            conversation_root = (self.conversations_root / context.run_id).resolve()
            if self.conversations_root not in conversation_root.parents:
                raise ValueError("DSH Conversation目录越界")
            session_root = conversation_root / "sessions"
            session_root.mkdir(parents=True, exist_ok=True)
            dsh_home = conversation_root / "home"
            dsh_home.mkdir(parents=True, exist_ok=True)
            web_url_file = conversation_root / "web-url.txt"
            web_url_file.unlink(missing_ok=True)
            web_token = secrets.token_urlsafe(32)
            session_id = self.session_id_for_run(context.run_id)
            harness = DeepSeekHarness(DeepSeekHarnessConfig(
                provider="deepseek-official",
                model=model["model_name"],
                cwd=str(workspace),
                runtime_cwd=str(conversation_root),
                session_root=str(session_root),
                launch_args_override=(str(launcher), *runtime_args),
                base_url=model["base_url"],
                api_key=model["api_key"],
                request_timeout_seconds=self._startup_remaining(deadline),
                shutdown_timeout_seconds=self.config.dsh.shutdown_timeout_seconds,
                process_factory=lambda *args, **kwargs: self._create_process(startup, *args, **kwargs),
                env={
                    "DSH_MW_MANAGED": "1",
                    "DSH_HOME": str(dsh_home),
                    "DSH_MW_WEB_READ_ONLY": "1",
                    "DSH_MW_WEB_TOKEN": web_token,
                    "DSH_MW_SESSION_ID": session_id,
                    "DSH_MW_WEB_URL_FILE": str(web_url_file),
                    "DSH_PERMISSION_MODE": {
                        "readonly": "read-only",
                        "sandbox": "workspace-write",
                        "full_access": "danger-full-access",
                    }[context.access_mode],
                },
            ))
            with self._lock:
                startup.harness = harness
                stopped = startup.stopped or self._closed
            if stopped:
                raise ChildAgentStopped("DSH 子 Agent启动已停止")
            context.raise_if_stopped()
            harness.start()
            server_info = harness.initialize_response.serverInfo if harness.initialize_response else None
            capabilities = set(server_info.capabilities if server_info else [])
            required = {"mw-session-open-v1", "mw-session-flush-v1", "mw-tools-v1"}
            if server_info is None or server_info.name != "deepseek-harness-sdk-runtime" or not required <= capabilities:
                raise RuntimeError("DSH Runtime不兼容 MW Session与真实工具目录协议，请修复 SDK安装")
            opened = harness.client.request(
                "session/open", {"sessionId": session_id}, response_model=_SessionOpenResponse,
                timeout_seconds=self._startup_remaining(deadline),
            )
            if opened.disposition not in {"created", "resumed", "already-open"}:
                raise RuntimeError("DSH session/open返回未知状态")
            tools = frozenset(opened.tools)
            if context.access_mode == "readonly" and tools - {"read", "read_image"}:
                raise RuntimeError("DSH readonly Runtime暴露了非只读工具，请修复 SDK安装")
            context.raise_if_stopped()
            self._startup_remaining(deadline)
            handle = _RuntimeHandle(
                harness=harness, session_id=session_id, session_root=session_root,
                web_url_file=web_url_file, web_token=web_token,
                access_mode=context.access_mode, user_id=context.user_id,
                process=startup.process, last_activity=time.monotonic(),
                tools=tools,
            )
            self._refresh_web_url(handle)
            with self._lock:
                if startup.stopped or self._closed:
                    raise ChildAgentStopped("DSH 子 Agent启动已停止")
                self._handles[context.run_id] = handle
                self._starting.pop(context.run_id)
                published = True
            return handle
        except Exception as exc:
            error = exc
            raise
        finally:
            if not published:
                try:
                    self._close_startup(startup)
                finally:
                    if leased:
                        self.runtime_manager.release_runtime(context.run_id)
                    with self._lock:
                        startup.error = error
                        if self._starting.get(context.run_id) is startup:
                            self._starting.pop(context.run_id)
            startup.ready.set()
            startup.finished.set()

    @staticmethod
    def _startup_remaining(deadline: float) -> float:
        """冷恢复同样复用整体启动期限，避免每个握手请求重新计时。"""

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("DSH Runtime启动超时")
        return remaining

    def _create_process(self, startup: _RuntimeStartup, *args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        """登记 SDK赋值前的 Popen窗口，取消或退出时也能回收刚创建的进程。"""

        process = subprocess.Popen(*args, **kwargs)
        with self._lock:
            startup.process = process
            stopped = startup.stopped or self._closed
        if stopped or startup.context.cancellation.is_set():
            self._terminate_process(process, startup.context.run_id)
            raise ChildAgentStopped("DSH 子 Agent进程创建已停止")
        return process

    def _close_startup(self, startup: _RuntimeStartup) -> None:
        """只允许一个线程关闭启动中 SDK，清理异常不掩盖原失败。"""

        with self._lock:
            claim = startup.harness is not None and not startup.close_started
            if claim:
                startup.close_started = True
            harness, process = startup.harness, startup.process
        if claim:
            assert harness is not None
            try:
                self._close_harness(harness, startup.context.run_id, process)
            finally:
                startup.close_done.set()
        elif startup.close_started:
            if not startup.close_done.wait(self.config.dsh.shutdown_timeout_seconds):
                if process is not None:
                    self._terminate_process(process, startup.context.run_id)

    def _finish_handle(self, run_id: str, handle: _RuntimeHandle, done: threading.Event) -> None:
        """关闭热句柄后释放租约和容量；同 run在关闭结束前不能重新启动。"""

        try:
            self._close_harness(handle.harness, run_id, handle.process)
        finally:
            try:
                self.runtime_manager.release_runtime(run_id)
            finally:
                with self._lock:
                    if self._closing.get(run_id) is done:
                        self._closing.pop(run_id)
                done.set()

    def _close_harness(
        self, harness: DeepSeekHarness, run_id: str, process: subprocess.Popen[str] | None = None,
    ) -> None:
        """保留主错误；SDK退出异常时仍终止由 executor登记的原始进程。"""

        try:
            harness.close()
        except Exception as exc:
            logger.warning("关闭 DSH SDK失败 | run_id=%s | error_type=%s", run_id, type(exc).__name__)
        finally:
            if process is not None:
                self._terminate_process(process, run_id)

    def _terminate_process(self, process: subprocess.Popen[str], run_id: str) -> None:
        """以配置中的有界等待回收仍存活的 Windows Job launcher。"""

        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.config.dsh.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.config.dsh.shutdown_timeout_seconds)
        except Exception as exc:
            logger.warning("回收 DSH进程失败 | run_id=%s | error_type=%s", run_id, type(exc).__name__)

    def _reap_idle(self) -> None:
        """原子移除过期空闲句柄，然后锁外回收；关闭期间继续占用容量槽。"""

        cutoff = time.monotonic() - self.config.dsh.idle_timeout_seconds
        expired = []
        with self._lock:
            for run_id, handle in list(self._handles.items()):
                if not handle.running and run_id not in self._active and handle.last_activity < cutoff:
                    done = threading.Event()
                    self._handles.pop(run_id)
                    self._closing[run_id] = done
                    expired.append((run_id, handle, done))
        for item in expired:
            self._finish_handle(*item)

    @staticmethod
    def _build_prompt(context: ChildAgentExecutionContext) -> str:
        """把真实能力、权限、工作区和父任务合同传给独立 DSH 模型。"""

        parts = [
            f"工作区绝对路径: {context.workspace_root}",
            f"权限: {context.access_mode}; 实际工具名: {', '.join(sorted(context.allowed_tools)) or '无'}",
        ]
        if context.access_mode == "readonly":
            parts.append(
                "readonly 仅能读取指定文本和图片，无 Shell，不能写入、搜索或枚举目录。"
                "Python版本、Git状态、文件计数和测试需要主 Agent 另派 sandbox DSH；不得猜测结果或声称任务全部完成。"
            )
        elif "pwsh" in context.allowed_tools:
            parts.append("命令、目录枚举、搜索、Git和测试通过实际存在的 pwsh 执行；没有独立 search/git/test 工具。")
        else:
            parts.append("当前工具目录无 Shell，不能执行命令、目录枚举、Git或测试；请如实报告能力缺失，不得猜测执行结果。")
        if context.input_refs:
            parts.append(f"输入引用: {json.dumps(list(context.input_refs), ensure_ascii=False)}")
        if context.output_contract:
            parts.append(f"输出要求: {json.dumps(dict(context.output_contract), ensure_ascii=False)}")
        return "\n".join(parts) + f"\n\n任务:\n{context.goal}"

    def _resolve_model(self, user_id: str) -> dict[str, str]:
        """读取用户覆盖优先的远程大模型配置并拒绝本地模型回退。"""

        configured = self.settings_service.get_llm_config(user_id=user_id)
        model_name = str(configured.get("effective_model_name") or "").strip()
        base_url = str(configured.get("effective_base_url") or "").strip()
        api_key = str(configured.get("effective_api_key") or "").strip()
        if not SettingsService.supports_dsh_model(configured):
            raise ValueError("DSH 子 Agent需要已配置的远程 DeepSeek模型、Base URL和凭据")
        return {"model_name": model_name, "base_url": base_url, "api_key": api_key}

    def _resolve_workspace(self, requested: str) -> Path:
        """解析父 Agent明确提供的工作区；未提供时使用 MW项目根目录。"""

        workspace = Path(requested or self.config.storage.project_root).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError("DSH 子 Agent工作区不存在或不是目录")
        return workspace

    def _monitor_cancellation(
        self,
        context: ChildAgentExecutionContext,
        done: threading.Event,
        watch: _ExecutionWatch,
    ) -> None:
        """监视启动和 Turn的取消与独立期限，锁外结束对应 owner。"""

        while not done.wait(0.1):
            if context.cancellation.is_set():
                self.stop(context.run_id)
                return
            deadline = watch.startup_deadline if watch.turn_deadline is None else watch.turn_deadline
            if time.monotonic() >= deadline:
                watch.timed_out.set()
                self.stop(context.run_id)
                return

    @staticmethod
    def _refresh_web_url(handle: _RuntimeHandle) -> None:
        """从固定 URL文件或 SDK stderr发现同进程 loopback Web地址。"""

        candidates: list[str] = []
        if handle.web_url_file.is_file():
            candidates.append(handle.web_url_file.read_text(encoding="utf-8").strip())
        candidates.extend(
            line.split("dsh web:", 1)[1].strip()
            for line in handle.harness.client.stderr_lines
            if "dsh web:" in line
        )
        for candidate in reversed(candidates):
            parsed = urlparse(candidate)
            if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
                handle.web_base_url = candidate
                return
