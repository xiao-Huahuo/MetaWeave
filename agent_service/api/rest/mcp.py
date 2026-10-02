"""MCP settings management routes; services resolve exclusively from the request's application container."""
from functools import partial
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError
from agent_service.api.rest.deps import _require
from agent_service.schemas.mcp import McpClientSettings

async def require_local_management(request: Request) -> None:
    """Local settings controls cannot be used as an unauthenticated remote process/credential API."""
    from ipaddress import ip_address
    from urllib.parse import urlsplit
    peer = request.client.host if request.client else ""
    if peer != "testclient":
        try:
            if not ip_address(peer).is_loopback:
                raise ValueError()
        except ValueError:
            raise HTTPException(403, "MCP 管理只允许本机访问") from None
    origin = request.headers.get("origin")
    if origin and origin != "null":
        host = urlsplit(origin).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "MCP 管理不允许此网页来源")


router = APIRouter(prefix="/settings/mcp", tags=["MCP"], dependencies=[Depends(require_local_management)])


def _client():
    """Resolve the request-bound client service."""
    return _require("mcp_client_service", "MCP client")


def _server():
    """Resolve the request-bound server service."""
    return _require("mcp_server_service", "MCP server")


async def _run(function, *args, **kwargs):
    """Run blocking database/SDK bridges off the HTTP loop; never echo credential inputs."""
    try:
        return await run_in_threadpool(partial(function, *args, **kwargs))
    except KeyError:
        raise HTTPException(404, "资源不存在") from None
    except PermissionError:
        raise HTTPException(403, "无访问权限") from None
    except ValidationError as exc:
        fields = "; ".join((".".join(map(str, e["loc"])) or "连接配置") + ": " + e["msg"]
                           for e in exc.errors(include_input=False))
        raise HTTPException(422, f"配置字段无效：{fields}") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except TimeoutError:
        raise HTTPException(504, "MCP 操作超时") from None


@router.get("/client")
async def get_client(user_id: str = Query(min_length=1)):
    """Read effective settings, connections and live state."""
    return await _run(_client().list, user_id)


@router.put("/client")
async def save_client(body: dict, user_id: str = Query(min_length=1)):
    """Apply the user's explicit client enable override."""
    return await _run(lambda: _client().set_enabled(user_id, McpClientSettings.model_validate(body).enabled))


@router.post("/client/connections")
async def create_connection(body: dict, user_id: str = Query(min_length=1)):
    """Persist and apply a new external connection."""
    return await _run(_client().save, user_id, body)


@router.put("/client/connections/{connection_id}")
async def update_connection(connection_id: str, body: dict, user_id: str = Query(min_length=1)):
    """Apply a revision-guarded edit; null secret entries preserve stored values."""
    payload = dict(body)
    revision = payload.pop("revision", None)
    return await _run(_client().save, user_id, payload, connection_id, revision)


@router.delete("/client/connections/{connection_id}")
async def delete_connection(connection_id: str, user_id: str = Query(min_length=1)):
    """Delete configuration and release its runtime resources."""
    await _run(_client().delete, user_id, connection_id)
    return {"deleted": True}


@router.post("/client/connections/{connection_id}/reconnect")
async def reconnect(connection_id: str, user_id: str = Query(min_length=1)):
    """Retry one persisted connection without disturbing others."""
    return await _run(_client().apply, user_id, connection_id, True)


@router.post("/client/test")
async def test_connection(body: dict, user_id: str = Query(min_length=1)):
    """Initialize and discover a draft on an isolated temporary connection."""
    payload = dict(body)
    connection_id = payload.pop("connection_id", "")
    return await _run(_client().test, user_id, payload, connection_id)


@router.get("/client/export")
async def export_connections(user_id: str = Query(min_length=1)):
    """Export secret-free configuration only."""
    return await _run(_client().export, user_id)


@router.post("/client/import/preview")
async def preview_import(body: dict, user_id: str = Query(min_length=1)):
    """Validate imported JSON and report name conflicts before changing configuration."""
    return {"entries": await _run(_client().import_preview, user_id, body.get("config"))}


@router.get("/server")
async def get_server(user_id: str = Query(min_length=1)):
    """Read listener status, exposure catalogue and credential metadata."""
    return _server().status(user_id)


@router.put("/server")
async def save_server(body: dict, user_id: str = Query(min_length=1)):
    """Persist and start/stop the actual user-owned MCP listener."""
    try:
        return await _server().save(user_id, body)
    except (ValueError, ValidationError):
        raise HTTPException(422, "监听地址、端口或工具配置无效") from None


@router.post("/server/credentials")
async def create_credential(body: dict, user_id: str = Query(min_length=1)):
    """Return a new credential secret once."""
    return await _run(_server().create_credential, user_id, body)


@router.delete("/server/credentials/{credential_id}")
async def revoke_credential(credential_id: str, user_id: str = Query(min_length=1)):
    """Revoke further use of a user-owned access identity."""
    await _run(_server().revoke, user_id, credential_id)
    return {"revoked": True}


@router.post("/server/credentials/{credential_id}/rotate")
async def rotate_credential(credential_id: str, user_id: str = Query(min_length=1)):
    """Invalidate the old secret and return its replacement once."""
    return await _run(_server().rotate, user_id, credential_id)


@router.get("/server/records")
async def get_records(user_id: str = Query(min_length=1)):
    """Read durable, redacted access outcomes."""
    return {"records": await _run(_server().records, user_id)}


@router.post("/server/verify")
async def verify_server(body: dict, user_id: str = Query(min_length=1)):
    """Verify the actual listener with a provided one-time or externally retained credential."""
    from agent_service.tools.mcp.client import MCPClient, MCPServerConfig
    service = _server()
    status = service.status(user_id)
    if status["state"] != "running":
        raise HTTPException(409, "请先启动 MCP 服务器")
    token = str(body.get("token") or "")
    await _run(service.authenticate, user_id, token)
    try:
        async with MCPClient(config=MCPServerConfig(transport="http", url=status["url"],
                             headers={"Authorization": f"Bearer {token}"}, timeout_seconds=service.config.mcp.timeout_seconds)) as client:
            tools = await client.list_tools()
            safe = next((t for t in tools if t.name in {"list_knowledge_files", "list_library_tags"}), None)
            result = await client.call_tool(safe.name, {}) if safe else None
            return {"initialized": True, "tool_count": len(tools), "call_verified": result is not None and not result.is_error,
                    "message": "初始化、工具发现和只读调用通过" if result and not result.is_error else
                               "初始化和工具发现通过；当前凭据没有可无参数验证的只读工具"}
    except Exception:
        raise HTTPException(502, "真实 MCP 验证失败，请检查服务诊断和凭据") from None
