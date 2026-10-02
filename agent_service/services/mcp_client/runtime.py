"""Application-owned MCP connection actors; each SDK context is entered/exited by its owning task."""
from __future__ import annotations
import asyncio
import concurrent.futures
import logging
import threading
from dataclasses import dataclass, field
from typing import Any
from agent_service.tools.mcp.client import MCPClient, MCPServerConfig

logger = logging.getLogger(__name__)


@dataclass
class ConnectionActor:
    """Single writer for a connection's command queue and live snapshot."""
    payload: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    state: str = "connecting"
    error: str = ""
    tools: list[dict] = field(default_factory=list)
    task: asyncio.Task | None = None
    ready: asyncio.Future | None = None


class McpClientRuntime:
    """One loop/thread per application; independent actors isolate failures between connections."""

    def __init__(self, config) -> None:
        """Store bounds; no thread starts during construction."""
        self.config = config
        self.loop = None
        self.thread = None
        self.actors: dict[tuple[str, str], ConnectionActor] = {}

    def start(self) -> None:
        """Start the dedicated SDK owner loop once, with bounded readiness wait."""
        if self.thread is not None:
            return
        ready = threading.Event()
        def run() -> None:
            """Own and close the event loop in the same background thread."""
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            ready.set()
            self.loop.run_forever()
            self.loop.close()
        self.thread = threading.Thread(target=run, name="mcp-client-runtime", daemon=True)
        self.thread.start()
        if not ready.wait(self.config.mcp.shutdown_timeout_seconds):
            raise TimeoutError("MCP 客户端运行时启动超时")

    def submit(self, coroutine, timeout: float | None = None, cancel_event=None):
        """Bridge synchronous Agent/service callers; propagate cancellation on timeout."""
        if self.loop is None or self.thread is None:
            coroutine.close()
            raise RuntimeError("MCP 客户端运行时尚未启动")
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            if cancel_event is None:
                return future.result(timeout or self.config.mcp.timeout_seconds)
            import time
            deadline = time.monotonic() + (timeout or self.config.mcp.timeout_seconds)
            while True:
                if cancel_event.is_set():
                    future.cancel()
                    raise RuntimeError("MCP 调用已取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise concurrent.futures.TimeoutError()
                try:
                    return future.result(min(remaining, 0.1))
                except concurrent.futures.TimeoutError:
                    continue
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("MCP 操作超时") from None

    async def _own(self, actor: ConnectionActor) -> None:
        """Connect, discover, serialize calls and always close SDK resources in this task."""
        payload = actor.payload
        client = MCPClient(config=MCPServerConfig(
            command=payload.get("command", ""), args=payload.get("args", []),
            env=payload.get("env", {}), cwd=payload.get("cwd") or None,
            transport=payload["transport"], url=payload.get("url", ""),
            headers=payload.get("headers", {}), timeout_seconds=payload["timeout_seconds"],
        ))
        try:
            async with client:
                async with asyncio.timeout(payload["timeout_seconds"]):
                    tools = await client.list_tools()
                actor.tools = [dict(name=t.name, title=t.title, description=t.description, input_schema=t.input_schema,
                                    annotations=t.annotations) for t in tools]
                actor.state = "connected"
                actor.ready.set_result(True)
                while True:
                    operation, future = await actor.queue.get()
                    if future.cancelled():
                        continue
                    invocation = asyncio.create_task(client.call_tool(operation[0], operation[1]))
                    def cancel_invocation(done, task=invocation):
                        """Cancel only the caller-owned request, preserving unrelated actor requests."""
                        if done.cancelled():
                            task.cancel()
                    future.add_done_callback(cancel_invocation)
                    try:
                        async with asyncio.timeout(payload["timeout_seconds"]):
                            result = await invocation
                        if not future.done():
                            future.set_result(result)
                    except asyncio.CancelledError:
                        if not future.done():
                            future.set_exception(RuntimeError("MCP 调用已取消"))
                        if asyncio.current_task().cancelling():
                            raise
                    except Exception:
                        if not future.done():
                            future.set_exception(RuntimeError("MCP 工具调用失败或超时；请检查服务诊断"))
                    finally:
                        future.remove_done_callback(cancel_invocation)
                        if not invocation.done():
                            invocation.cancel()
                            await asyncio.gather(invocation, return_exceptions=True)
        except asyncio.CancelledError:
            actor.state = "stopped"
            raise
        except Exception:
            actor.state = "failed"
            actor.error = "连接或初始化失败；请检查程序、地址、认证及超时配置"
            logger.warning("MCP connection failed | transport=%s", payload["transport"])
            if not actor.ready.done():
                actor.ready.set_result(False)
        finally:
            while not actor.queue.empty():
                _, future = actor.queue.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError("MCP 连接已关闭"))

    async def connect(self, key: tuple[str, str], payload: dict, reconnect: bool = False) -> dict:
        """Reuse matching live actors; replace only this connection when configuration changes."""
        actor = self.actors.get(key)
        transport_fields = ("transport", "command", "args", "env", "cwd", "url", "headers", "timeout_seconds")
        if actor and all(actor.payload.get(field) == payload.get(field) for field in transport_fields) and actor.state in {"connected", "connecting"} and not reconnect:
            if actor.state == "connecting":
                await asyncio.wait_for(asyncio.shield(actor.ready), payload["timeout_seconds"])
            actor.payload = dict(payload)
            return self.snapshot(key)
        await self.stop(key)
        if len(self.actors) >= self.config.mcp.max_connections:
            raise ValueError("MCP 连接数已达到服务上限")
        actor = ConnectionActor(payload=payload)
        actor.ready = asyncio.get_running_loop().create_future()
        self.actors[key] = actor
        actor.task = asyncio.create_task(self._own(actor))
        try:
            await asyncio.wait_for(asyncio.shield(actor.ready), payload["timeout_seconds"])
        except TimeoutError:
            await self.stop(key)
            raise
        return self.snapshot(key)

    def snapshot(self, key: tuple[str, str]) -> dict:
        """Return copied, secret-free state on the owner loop."""
        actor = self.actors.get(key)
        return {"state": actor.state, "error": actor.error, "tools": list(actor.tools)} if actor else {
            "state": "stopped", "error": "", "tools": [],
        }

    async def snapshots(self) -> dict:
        """Copy actor state for management/API callers without shared mutations."""
        return {key: self.snapshot(key) for key in self.actors}

    async def call(self, key: tuple[str, str], name: str, arguments: dict):
        """Queue an independent invocation, with bounded wait and explicit future cancellation."""
        actor = self.actors.get(key)
        if not actor or actor.state != "connected":
            raise RuntimeError("MCP 服务尚未连接")
        future = asyncio.get_running_loop().create_future()
        await actor.queue.put(((name, arguments), future))
        return await asyncio.wait_for(future, actor.payload["timeout_seconds"])

    async def stop(self, key: tuple[str, str]) -> None:
        """Cancel only this actor; wait for its SDK context and subprocess cleanup."""
        actor = self.actors.pop(key, None)
        if actor and actor.task:
            if not actor.ready.done():
                actor.ready.set_result(False)
            actor.task.cancel()
            try:
                await asyncio.wait_for(actor.task, self.config.mcp.shutdown_timeout_seconds)
            except asyncio.CancelledError:
                pass

    async def _close(self) -> None:
        """Close all independently owned connections before stopping the loop."""
        for key in list(self.actors):
            await self.stop(key)

    def shutdown(self) -> None:
        """Release actors, loop and thread; repeated shutdown is harmless."""
        if self.thread is None:
            return
        try:
            self.submit(self._close(), self.config.mcp.shutdown_timeout_seconds * 2)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(self.config.mcp.shutdown_timeout_seconds)
            self.thread = None
            self.loop = None
