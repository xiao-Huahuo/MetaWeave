"""Authenticated SDK MCP ingress and real, lifespan-owned per-user HTTP listeners."""
from __future__ import annotations
import asyncio
import json
import logging
import socket
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp import types
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)
request_token: ContextVar[str] = ContextVar("mcp_bearer", default="")


def protocol_app(service, user_id: str) -> Starlette:
    """Create a fresh stateless SDK manager; token context never outlives its HTTP request."""
    server = Server("MetaWeave")
    calls = asyncio.Semaphore(service.config.mcp.max_server_calls)

    @server.list_tools()
    async def list_tools():
        """Return only the intersection of current exposure and authenticated credential grants."""
        record = await asyncio.to_thread(service.authenticate, user_id, request_token.get())
        tools = await asyncio.to_thread(service.allowed_tools, record)
        return [types.Tool(name=t["name"], title=t["title"], description=t["description"], inputSchema=t["input_schema"],
                           annotations=types.ToolAnnotations(readOnlyHint=not t["write"], destructiveHint=t["write"])) for t in tools]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        """Apply complete business validation and preserve structured results; redact internal exceptions."""
        try:
            async with asyncio.timeout(service.config.mcp.timeout_seconds):
                await calls.acquire()
            try:
                result = await asyncio.to_thread(service.call, user_id, request_token.get(), name, arguments)
            finally:
                calls.release()
            structured = result if isinstance(result, dict) else {"result": result}
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(structured, ensure_ascii=False, default=str))], structuredContent=structured)
        except PermissionError:
            return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text="工具或资源无访问权限")])
        except Exception as exc:
            logger.warning("MCP call failed | tool=%s type=%s", name, type(exc).__name__)
            return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text="调用失败，请检查工具参数、资源及服务诊断")])

    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)

    @asynccontextmanager
    async def lifespan(app):
        """Enter and exit the SDK manager in its application owner task."""
        async with manager.run():
            yield

    async def endpoint(request):
        """Authenticate before any MCP parsing; protect HTTP ingress from browser-origin requests."""
        auth = request.headers.get("authorization", "")
        if request.headers.get("origin"):
            return JSONResponse({"error": "Browser-origin MCP requests are not allowed"}, status_code=403)
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "Bearer credential required"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        token = auth[7:]
        try:
            await asyncio.to_thread(service.authenticate, user_id, token)
        except PermissionError:
            return JSONResponse({"error": "Invalid or revoked credential"}, status_code=401)
        scope_token = request_token.set(token)
        try:
            await manager.handle_request(request.scope, request.receive, request._send)
        finally:
            request_token.reset(scope_token)

    # A raw ASGI route is required because SDK owns the response stream.
    async def ingress(scope, receive, send):
        """Bridge SDK streaming without constructing a second Starlette response."""
        from starlette.requests import Request
        request = Request(scope, receive, send)
        response = await endpoint(request)
        if response is not None:
            await response(scope, receive, send)

    class Ingress:
        """ASGI callable keeps Starlette from wrapping the SDK endpoint as a Request function."""
        async def __call__(self, scope, receive, send):
            await ingress(scope, receive, send)
    return Starlette(routes=[Route("/mcp", Ingress(), methods=["GET", "POST", "DELETE"])], lifespan=lifespan)


@dataclass
class Listener:
    """Own one prebound socket, Uvicorn server, task and immutable address configuration."""
    config: dict
    server: uvicorn.Server
    task: asyncio.Task
    socket: socket.socket


class McpServerRuntime:
    """Application-loop listener owner; startup failure is isolated to its user's server."""

    def __init__(self, service) -> None:
        """No listener or task is created before application startup."""
        self.service = service
        self.listeners: dict[str, Listener] = {}
        self.errors: dict[str, str] = {}
        self.operations: dict[str, asyncio.Task] = {}
        self.loop = None

    def status(self, user_id: str) -> dict:
        """Report actual listener readiness and active configuration, never inferred from saved flags."""
        listener = self.listeners.get(user_id)
        return {"state": "running" if listener and listener.server.started and not listener.task.done() else
                "failed" if self.errors.get(user_id) else "stopped", "error": self.errors.get(user_id, ""),
                "active_config": listener.config if listener else None}

    async def apply(self, user_id: str, config: dict) -> None:
        """Serialize address mutations per user without holding an I/O lock."""
        self.loop = asyncio.get_running_loop()
        previous = self.operations.get(user_id)
        async def apply_after_previous():
            """Publish the queue tail before waiting, so simultaneous callers cannot skip a predecessor."""
            if previous:
                await asyncio.wait_for(asyncio.shield(previous), self.service.config.mcp.shutdown_timeout_seconds * 2)
            await self._apply(user_id, config)
        task = asyncio.create_task(apply_after_previous())
        self.operations[user_id] = task
        def finished(done):
            """Release only this completed queue tail, including cancelled HTTP callers."""
            if self.operations.get(user_id) is done:
                self.operations.pop(user_id, None)
        task.add_done_callback(finished)
        try:
            await asyncio.shield(task)
        finally:
            if task.done():
                finished(task)

    async def _apply(self, user_id: str, config: dict) -> None:
        """Bind a real socket before publishing running state and retain actionable failures."""
        listener = self.listeners.get(user_id)
        if listener and config["enabled"] and all(listener.config[k] == config[k] for k in ("host", "port")):
            listener.config = dict(config)
            return
        await self.stop(user_id)
        self.errors.pop(user_id, None)
        if not config["enabled"]:
            return
        sock = socket.socket(socket.AF_INET6 if ":" in config["host"] else socket.AF_INET)
        try:
            sock.bind((config["host"], config["port"]))
            sock.listen()
            sock.setblocking(False)
            server = uvicorn.Server(uvicorn.Config(protocol_app(self.service, user_id), access_log=False,
                log_level="warning", timeout_graceful_shutdown=self.service.config.mcp.shutdown_timeout_seconds))
            async def serve():
                """Uvicorn serves without installing process-wide signal handlers."""
                await server._serve(sockets=[sock])
            task = asyncio.create_task(serve())
            self.listeners[user_id] = Listener(dict(config), server, task, sock)
            async with asyncio.timeout(self.service.config.mcp.shutdown_timeout_seconds):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("MCP listener exited before startup")
                    await asyncio.sleep(0.02)
        except Exception:
            sock.close()
            await self.stop(user_id)
            self.errors[user_id] = "启动失败：请检查监听地址、端口占用和服务日志"
            logger.warning("MCP listener startup failed | port=%s", config["port"])

    async def stop(self, user_id: str) -> None:
        """Stop accepting requests, drain calls and close the owned socket."""
        listener = self.listeners.pop(user_id, None)
        if listener:
            listener.server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(listener.task), self.service.config.mcp.shutdown_timeout_seconds * 2)
            except TimeoutError:
                listener.task.cancel()
                await asyncio.gather(listener.task, return_exceptions=True)
            finally:
                listener.socket.close()

    async def shutdown(self) -> None:
        """Release every listener before the parent FastAPI lifespan exits."""
        for operation in list(self.operations.values()):
            await asyncio.gather(operation, return_exceptions=True)
        for user_id in list(self.listeners):
            await self.stop(user_id)
