"""Application authentication routes; desktop-private key material never reaches ordinary renderers.

Session cookies and bearer tokens identify one account. Device ciphertext APIs
require the per-launch desktop nonce, while all passwords use typed bounded DTOs.
"""
from __future__ import annotations

import hmac
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from agent_service.api.rest.deps import _require_auth_service, _require_settings_service
from agent_service.schemas.auth import (AuthCredentialsRequest, AuthRestoreRequest, AuthPasswordChangeRequest,
    AuthOnboardingRequest, AuthRememberedBlobRequest, AuthLogoutRequest)
from agent_service.services.auth.service import AuthError

COOKIE_NAME = "metaweave_session"


def trusted_origins(config) -> set[str]:
    """Exact app origins, not every service sharing a loopback hostname."""
    port = config.server.http_port
    return {config.server.frontend_origin, f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"}


def check_cookie_origin(request: Request) -> None:
    """Cookie-authenticated writes require the trusted app origin or a bearer proof."""
    if request.headers.get("authorization"):
        return
    if not request.cookies.get(COOKIE_NAME):
        return
    origin = request.headers.get("origin")
    if origin and origin not in trusted_origins(_require_auth_service().config):
        raise HTTPException(status_code=403, detail="Untrusted session origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not origin and (not request.client or request.client.host != "testclient"):
        raise HTTPException(status_code=403, detail="Session write requires a trusted origin")

class PrivateValidationRoute(APIRoute):
    """Suppress sensitive request values in authentication validation responses."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                details = [{k: value for k, value in error.items() if k in {"loc", "msg", "type"}} for error in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": details})
        return safe_handler

router = APIRouter(route_class=PrivateValidationRoute)

def request_token(request: Request) -> str:
    """Accept the same opaque session from the API header or the HttpOnly cookie."""
    authorization = request.headers.get("authorization", "")
    if authorization:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")
        return authorization[7:].strip()
    return request.cookies.get(COOKIE_NAME, "")

def _local_request(request: Request) -> None:
    """Passwords and OS-bound remember material belong to this local application."""
    peer = request.client.host if request.client else ""
    if peer not in {"testclient", "localhost"}:
        try:
            if not ip_address(peer).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Local authentication only") from exc
    origin = request.headers.get("origin")
    if origin:
        if origin not in trusted_origins(_require_auth_service().config):
            raise HTTPException(status_code=403, detail="Untrusted authentication origin")

def require_desktop(request: Request) -> None:
    """The nonce is held by Electron main and its child backend, never by a web page."""
    _local_request(request)
    expected = _require_auth_service().config.server.desktop_auth_nonce
    supplied = request.headers.get("x-desktop-auth", "")
    if not expected or not hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Trusted desktop required")

async def _call(function, *args, **kwargs):
    """Run bounded KDF/database work off the event loop and expose safe service errors."""
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

def _session_cookie(response: Response, payload: dict[str, Any]) -> None:
    """Keep file/preview/SSE requests authenticated on the local application origin."""
    response.set_cookie(COOKIE_NAME, payload["token"], httponly=True, samesite="strict", secure=False,
                        path="/", max_age=_require_auth_service().config.limits.auth_access_session_hours * 3600)
    response.headers["Cache-Control"] = "no-store"

async def _manual(request: Request, response: Response, body: AuthCredentialsRequest, register: bool):
    """Only manual confirmation can issue or renew a 30-day remembered device."""
    _local_request(request)
    if body.device_id:
        require_desktop(request)
    service = _require_auth_service()
    payload = await _call(service.register if register else service.login,
                          username=body.username, password=body.password, device_id=body.device_id)
    await run_in_threadpool(_require_settings_service().ensure_user_profile, user_id=payload["user_id"])
    if "remember" in payload:
        payload["remember"].update(user_id=payload["user_id"], username=payload["username"])
    _session_cookie(response, payload)
    return payload

@router.post("/auth/register")
async def register(request: Request, response: Response, body: AuthCredentialsRequest) -> dict[str, Any]:
    """Register one username/password identity and start the five-page initialization."""
    return await _manual(request, response, body, True)

@router.post("/auth/login")
async def login(request: Request, response: Response, body: AuthCredentialsRequest) -> dict[str, Any]:
    """Verify the shared login/vault password after an explicit confirmation."""
    return await _manual(request, response, body, False)

@router.post("/auth/restore")
async def restore(request: Request, response: Response, body: AuthRestoreRequest) -> dict[str, Any]:
    """Restore an OS-unsealed device without changing its original expiry."""
    require_desktop(request)
    payload = await _call(_require_auth_service().restore, **body.model_dump())
    _session_cookie(response, payload)
    return payload

@router.get("/auth/me")
async def current(request: Request, response: Response) -> dict[str, Any]:
    """Return authoritative identity and durable initialization progress."""
    response.headers["Cache-Control"] = "no-store"
    return await _call(_require_auth_service().get_status, request_token(request))

@router.post("/auth/logout")
async def logout(request: Request, response: Response, body: AuthLogoutRequest) -> dict[str, bool]:
    """Revoke the active session and remembered device before returning to login."""
    if body.device_id:
        require_desktop(request)
    result = await _call(_require_auth_service().logout, request_token(request), body.device_id)
    response.delete_cookie(COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return result

@router.post("/auth/password")
async def change_password(request: Request, response: Response, body: AuthPasswordChangeRequest) -> dict[str, bool]:
    """Atomically update the shared password and vault ciphertext, revoking old devices."""
    result = await _call(_require_auth_service().change_password, request_token(request), body.old_password, body.new_password)
    response.delete_cookie(COOKIE_NAME, path="/")
    return result

@router.put("/auth/onboarding")
async def advance_onboarding(request: Request, body: AuthOnboardingRequest) -> dict[str, Any]:
    """Advance only after the current page's real configuration has been saved."""
    return await _call(_require_auth_service().update_onboarding, request_token(request), body.step)

@router.get("/auth/device/remembered")
async def remembered(request: Request, response: Response, device_id: str) -> dict[str, Any]:
    """Return opaque OS ciphertext to the trusted desktop main process only."""
    require_desktop(request)
    payload = await _call(_require_auth_service().read_remembered_blob, device_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No remembered device")
    response.headers["Cache-Control"] = "no-store"
    payload["sealed_payload"] = payload.pop("blob", "")
    return payload

@router.put("/auth/device/remembered")
async def save_remembered(request: Request, body: AuthRememberedBlobRequest) -> dict[str, bool]:
    """Persist only OS-encrypted remembered material in the formal device table."""
    require_desktop(request)
    return await _call(_require_auth_service().write_remembered_blob, request_token(request), body.device_id, body.sealed_payload)

@router.delete("/auth/device/remembered")
async def forget_remembered(request: Request, device_id: str) -> dict[str, bool]:
    """The trusted desktop can forget a device even after its session has expired."""
    require_desktop(request)
    return await _call(_require_auth_service().delete_remembered_blob, device_id)
