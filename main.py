"""AgentService 的 FastAPI 进程入口。

本文件只保留第三方兼容补丁、HTTP 应用定义、中间件、路由、静态资源和直接运行
入口。业务服务、模型、gRPC 与生命周期装配位于 ``agent_service.core``。

启动方式：``uvicorn main:app --host 0.0.0.0 --port 8002``。
"""

from __future__ import annotations

# Local device revocation must run before web/model imports and without opening ports.
import sys
if __name__ == "__main__" and sys.argv[1:2] == ["--forget-device"]:
    from agent_service.services.auth.device_cli import main as forget_device_main
    raise SystemExit(forget_device_main(sys.argv[2:]))


import warnings
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

warnings.filterwarnings("ignore", message=".*allowed_objects.*")

# DeepSeek thinking mode 需要在后续请求中原样带回 reasoning_content。该兼容补丁
# 只是从原入口原样迁移，当前结构维护不改变其行为。
import langchain_openai.chat_models.base as _lc_openai_base

_original_convert_dict = _lc_openai_base._convert_dict_to_message
_original_convert_delta = _lc_openai_base._convert_delta_to_message_chunk


def _patched_convert_dict_to_message(_dict: dict, **kwargs: Any) -> Any:
    """把响应中的 reasoning_content 保存到 LangChain message。"""

    message = _original_convert_dict(_dict, **kwargs)
    reasoning = _dict.get("reasoning_content")
    if reasoning:
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        additional_kwargs["reasoning_content"] = reasoning
        message.additional_kwargs = additional_kwargs
    return message


def _patched_convert_delta_to_message_chunk(_dict: dict, default_class: Any) -> Any:
    """把流式响应中的 reasoning_content 保存到 LangChain chunk。"""

    chunk = _original_convert_delta(_dict, default_class)
    reasoning = _dict.get("reasoning_content")
    if reasoning:
        additional_kwargs = getattr(chunk, "additional_kwargs", None) or {}
        additional_kwargs["reasoning_content"] = reasoning
        chunk.additional_kwargs = additional_kwargs
    return chunk


_lc_openai_base._convert_dict_to_message = _patched_convert_dict_to_message
_lc_openai_base._convert_delta_to_message_chunk = _patched_convert_delta_to_message_chunk

_original_convert_message = _lc_openai_base._convert_message_to_dict


def _patched_convert_message_to_dict(message: Any, api: Any = "chat/completions") -> dict[str, Any]:
    """把 message 中保存的 reasoning_content 加回模型请求。"""

    result = _original_convert_message(message, api=api)
    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    reasoning = additional_kwargs.get("reasoning_content")
    if reasoning:
        result["reasoning_content"] = reasoning
    return result


_lc_openai_base._convert_message_to_dict = _patched_convert_message_to_dict

from agent_service.api.rest import router as rest_router
from agent_service.core.agent_config import AgentConfig
from agent_service.core.lifespan import agent_service_lifespan
from agent_service.services.activity.tracking import classify_activity, should_inspect_activity_request


_runtime_config = AgentConfig.load_config(ensure_directories=False, ensure_models=False)
app = FastAPI(title="Agent-Core-Service", lifespan=agent_service_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_runtime_config.server.frontend_origin, f"http://127.0.0.1:{_runtime_config.server.http_port}", f"http://localhost:{_runtime_config.server.http_port}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.middleware("http")
async def _record_daily_activity(request: Any, call_next: Any) -> Any:
    """在有意义的写操作成功后记录不含敏感内容的活动事件。"""

    body: dict[str, Any] = {}
    if (
        should_inspect_activity_request(request.method, request.url.path)
        and "application/json" in request.headers.get("content-type", "")
    ):
        try:
            payload = await request.json()
            body = payload if isinstance(payload, dict) else {}
        except ValueError:
            body = {}
    response = await call_next(request)
    event = classify_activity(request.method, request.url.path, body) if response.status_code < 400 else None
    services = getattr(request.app.state, "services", None)
    service = services.activity_service if services is not None else None
    if event is None or service is None:
        return response
    user_id = str(body.get("user_id") or request.query_params.get("user_id") or "").strip()
    if not user_id and request.url.path.startswith("/vault/"):
        try:
            from agent_service.api.rest.auth import request_token
            user_id = str(services.auth_service.verify_session(request_token(request)).user_id)
        except ValueError:
            user_id = ""
    if user_id:
        await run_in_threadpool(service.record_event, user_id=user_id, **event)
    return response


@app.middleware("http")
async def _allow_local_private_network_requests(request: Any, call_next: Any) -> Any:
    """允许 Electron/file renderer 访问本机后端的 Private Network 预检。"""

    response = await call_next(request)
    origin = request.headers.get("origin", "")
    from agent_service.api.rest.auth import trusted_origins
    if origin in trusted_origins(_runtime_config):
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


app.include_router(rest_router)

@app.middleware("http")
async def _protect_authenticated_streams(request: Any, call_next: Any) -> Any:
    """A stream must stop emitting private data once its account session is revoked."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        from agent_service.api.rest.auth import request_token
        from agent_service.services.auth.service import AuthError
        from starlette.concurrency import run_in_threadpool
        token = request_token(request)
        services = getattr(request.app.state, "services", None)
        original = response.body_iterator
        async def authenticated_stream():
            try:
                async for chunk in original:
                    try:
                        if services is None:
                            return
                        await run_in_threadpool(services.auth_service.verify_session, token)
                    except AuthError:
                        return
                    yield chunk
            finally:
                close = getattr(original, "aclose", None)
                if close is not None:
                    await close()
        response.body_iterator = authenticated_stream()
    return response


@app.middleware("http")
async def _protect_business_files(request: Any, call_next: Any) -> Any:
    """Authenticate static business assets; public frontend bundles remain accessible."""
    from starlette.responses import JSONResponse
    prefixes = ("/knowledge/assets/", "/downloads/", "/library/assets/", "/visualizations/")
    if request.url.path.startswith(prefixes):
        from agent_service.api.rest.auth import request_token
        from agent_service.services.auth.service import AuthError
        from starlette.concurrency import run_in_threadpool
        services = getattr(request.app.state, "services", None)
        if services is None:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)
        try:
            identity = await run_in_threadpool(services.auth_service.verify_session, request_token(request))
        except (AuthError, HTTPException) as exc:
            return JSONResponse({"detail": exc.detail if isinstance(exc, HTTPException) else str(exc)}, status_code=exc.status_code)
        from urllib.parse import unquote
        roots = {"/knowledge/assets/": services.config.storage.assets_dir / "knowledge", "/library/assets/": services.config.storage.assets_dir / "library", "/downloads/": services.config.storage.assets_dir / "downloads", "/visualizations/": services.config.storage.base_data_dir / "visualizations"}
        for prefix, root in roots.items():
            if request.url.path.startswith(prefix):
                relative = unquote(request.url.path[len(prefix):])
                owner_root = (root / identity.user_id).resolve()
                target = (root / relative).resolve()
                if not target.is_relative_to(owner_root):
                    return JSONResponse({"detail": "Resource not found"}, status_code=404)
                break
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Visualization scripts keep working in a unique origin, without account cookies.
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts" if request.url.path.startswith("/visualizations/") else "sandbox"
        return response
    return await call_next(request)


_knowledge_assets_dir = _runtime_config.storage.assets_dir / "knowledge"
_knowledge_assets_dir.mkdir(parents=True, exist_ok=True)
_downloads_dir = _runtime_config.storage.assets_dir / "downloads"
_downloads_dir.mkdir(parents=True, exist_ok=True)
_library_assets_dir = _runtime_config.storage.assets_dir / "library"
_library_assets_dir.mkdir(parents=True, exist_ok=True)
_visualizations_dir = _runtime_config.storage.base_data_dir / "visualizations"
_visualizations_dir.mkdir(parents=True, exist_ok=True)

from fastapi.staticfiles import StaticFiles

app.mount("/knowledge/assets", StaticFiles(directory=str(_knowledge_assets_dir)), name="knowledge_assets")
app.mount("/downloads", StaticFiles(directory=str(_downloads_dir)), name="downloads")
app.mount("/library/assets", StaticFiles(directory=str(_library_assets_dir)), name="library_assets")
app.mount("/visualizations", StaticFiles(directory=str(_visualizations_dir)), name="visualizations")


def _resolve_static_dir() -> Path | None:
    """按打包环境、开发环境顺序定位前端静态资源目录。"""

    if getattr(sys, "frozen", False):
        candidate = Path(sys._MEIPASS) / "editor" / "dist"
        if not candidate.is_dir():
            alternative = Path(sys._MEIPASS) / "dist"
            if alternative.is_dir():
                candidate = alternative
    else:
        candidate = Path(__file__).resolve().parent / "editor" / "dist"
    return candidate if candidate.is_dir() else None


_static_dir = _resolve_static_dir()
app.state.static_dir = _static_dir

if _static_dir is not None:
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def _favicon() -> FileResponse:
        """返回前端打包目录中的 favicon。"""

        return FileResponse(_static_dir / "favicon.ico")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        """对非 API 路径返回静态文件或 Vue SPA 的 index.html。"""

        from fastapi import HTTPException
        api_prefixes = ("auth", "vault", "settings", "agent", "sessions", "knowledge", "library", "scanner", "debug", "mcp", "smart-forms")
        if full_path.split("/", 1)[0] in api_prefixes:
            raise HTTPException(status_code=404, detail="Endpoint not found")
        file_path = (_static_dir / full_path).resolve()
        if not file_path.is_relative_to(_static_dir.resolve()):
            raise HTTPException(status_code=404, detail="File not found")
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_static_dir / "index.html")


if __name__ == "__main__":
    import multiprocessing

    import uvicorn

    multiprocessing.freeze_support()
    temp_config = AgentConfig.load_config(ensure_models=False)
    uvicorn.run(
        app,
        host=temp_config.server.http_host,
        port=temp_config.server.http_port,
        timeout_keep_alive=temp_config.server.uvicorn_timeout_keep_alive,
    )
