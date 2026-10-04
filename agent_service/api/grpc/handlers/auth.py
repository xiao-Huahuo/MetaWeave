"""Global account RPCs and one authentication boundary shared by every business RPC.

Manual account RPCs are loopback-only. Device restore/private vault remember keys
remain restricted to Electron REST calls. Context variables scope each unary or
streaming call and are reset on success, failure, cancellation and generator close.
"""

from __future__ import annotations

from functools import wraps
from ipaddress import ip_address
from typing import Any

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from pydantic import ValidationError

from agent_service.schemas.auth import AuthCredentialsRequest, AuthOnboardingRequest, AuthPasswordChangeRequest
from agent_service.services.auth.access import verify_claims
from agent_service.services.auth.context import current_identity
from agent_service.services.auth.service import AuthError, AuthSession
from agent_service.services.settings.mcp_settings import selected_library

AUTH_METHODS = {"AuthRegister", "AuthLogin", "AuthCurrent", "AuthLogout", "AuthChangePassword", "AuthAdvanceOnboarding"}
PUBLIC_AUTH_METHODS = {"AuthRegister", "AuthLogin"}
STATUS_CODES = {401: grpc.StatusCode.UNAUTHENTICATED, 403: grpc.StatusCode.PERMISSION_DENIED,
                404: grpc.StatusCode.NOT_FOUND, 409: grpc.StatusCode.ABORTED,
                422: grpc.StatusCode.INVALID_ARGUMENT, 429: grpc.StatusCode.RESOURCE_EXHAUSTED,
                503: grpc.StatusCode.UNAVAILABLE}


class AuthGrpcHandlerMixin:
    """Authenticate all descriptors at dispatch and provide local account operations."""

    def _install_rpc_auth(self) -> None:
        """Wrap inherited handlers once so direct calls and transport dispatch share guards."""
        from agent_service.api.grpc.agent_service_pb2 import DESCRIPTOR
        for method in DESCRIPTOR.services_by_name["AgentService"].methods:
            handler = getattr(self, method.name)
            guarded = self._guard_stream(method.name, handler) if method.server_streaming else self._guard_unary(method.name, handler)
            setattr(self, method.name, guarded)

    def _require_auth_service(self, context):
        """Never permit unsigned business calls when application auth is unavailable."""
        if self._auth_service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "AuthService not available")
        return self._auth_service

    @staticmethod
    def _grpc_bearer(context, payload: dict[str, Any]) -> str:
        """Prefer standard authorization metadata; support existing Struct token payloads."""
        metadata = dict(context.invocation_metadata() or ())
        authorization = metadata.get("authorization", "")
        if authorization:
            if not authorization.lower().startswith("bearer "):
                raise AuthError("Invalid authorization scheme")
            return authorization[7:].strip()
        return str(payload.get("token") or "")

    @staticmethod
    def _require_local_auth(context) -> None:
        """Allow password-bearing auth operations only over a loopback gRPC peer."""
        peer = context.peer()
        try:
            if peer.startswith("ipv4:"):
                host = peer[5:].rsplit(":", 1)[0]
            elif peer.startswith("ipv6:"):
                host = peer[5:].rsplit(":", 1)[0].strip("[]")
            else:
                raise ValueError("unknown peer")
            if not ip_address(host).is_loopback:
                raise ValueError("nonlocal peer")
        except ValueError as exc:
            raise AuthError("Local authentication only", 403) from exc

    @staticmethod
    def _grpc_path(method: str) -> str:
        """Reuse HTTP resource ownership rules for matching business domains."""
        if method.startswith("Vault"):
            return "/vault"
        if "LLMConfigPreset" in method:
            return "/settings/llm/configs"
        if "VlmConfigPreset" in method:
            return "/settings/vlm/configs"
        return "/grpc/" + method

    def _authenticate_rpc(self, method: str, request, context) -> tuple[AuthSession | None, str, Any]:
        """Validate claims before handlers see authoritative account identity."""
        payload = MessageToDict(request, preserving_proto_field_name=True)
        if method in AUTH_METHODS:
            self._require_local_auth(context)
        if method in PUBLIC_AUTH_METHODS:
            self._require_auth_service(context)
            return None, "", None
        service = self._require_auth_service(context)
        token = self._grpc_bearer(context, payload)
        session = service.verify_session(token)
        if payload.get("user_id") == "":
            payload.pop("user_id")
        if method == "CancelSession" and not payload.get("session_id"):
            raise AuthError("Session not found", 404)
        verify_claims(service.engine, user_id=session.user_id, payload=payload, path=self._grpc_path(method),
                      required_resources=method == "CancelSession")
        self._verify_child_claims(method, payload, session.user_id)
        if isinstance(request, Struct):
            request["user_id"] = session.user_id
        elif "user_id" in request.DESCRIPTOR.fields_by_name:
            request.user_id = session.user_id
        library = (session.user_id, str(payload["library_id"])) if payload.get("library_id") else None
        return session, token, library

    def _verify_child_claims(self, method: str, payload: dict[str, Any], user_id: str) -> None:
        """Authorize in-memory child runtimes whose controls carry no session_id."""
        if method not in {"StopChildAgent", "UpdateChildAgent", "ListChildAgents"}:
            return
        manager = getattr(self._agent, "child_agent_manager", None)
        run_id = str(payload.get("run_id") or "")
        if run_id:
            record = manager.get(run_id) if manager is not None else None
            if record is None or record.contract.user_id != user_id:
                raise AuthError("Resource not found", 404)
        parent = str(payload.get("parent_run_id") or "")
        if parent:
            records = manager.list_children(parent) if manager is not None else []
            if any(record.contract.user_id != user_id for record in records):
                raise AuthError("Resource not found", 404)

    def _guard_unary(self, method: str, handler):
        """Keep account/library context owned by one synchronous unary invocation."""
        @wraps(handler)
        def guarded(request, context):
            identity_token = library_token = None
            try:
                session, _, library = self._authenticate_rpc(method, request, context)
                identity_token = current_identity.set(session)
                library_token = selected_library.set(library)
                return handler(request, context)
            except AuthError as error:
                context.abort(STATUS_CODES.get(error.status_code, grpc.StatusCode.UNKNOWN), str(error))
            finally:
                if library_token is not None:
                    selected_library.reset(library_token)
                if identity_token is not None:
                    current_identity.reset(identity_token)
        return guarded

    def _guard_stream(self, method: str, handler):
        """Validate each emitted event and release the inner generator on abort/close."""
        @wraps(handler)
        def guarded(request, context):
            identity_token = library_token = None
            stream = None
            try:
                session, token, library = self._authenticate_rpc(method, request, context)
                identity_token = current_identity.set(session)
                library_token = selected_library.set(library)
                stream = handler(request, context)
                for event in stream:
                    if not context.is_active():
                        context.abort(grpc.StatusCode.CANCELLED, "RPC cancelled")
                    self._require_auth_service(context).verify_session(token)
                    yield event
            except AuthError as error:
                context.abort(STATUS_CODES.get(error.status_code, grpc.StatusCode.UNKNOWN), str(error))
            finally:
                try:
                    if stream is not None and hasattr(stream, "close"):
                        stream.close()
                finally:
                    if library_token is not None:
                        selected_library.reset(library_token)
                    if identity_token is not None:
                        current_identity.reset(identity_token)
        return guarded

    @staticmethod
    def _grpc_auth_session(context) -> AuthSession:
        """Expose the validated call identity to vault and account handlers."""
        session = current_identity.get()
        if session is None:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Login required")
        return session

    @staticmethod
    def _auth_dto(schema, payload):
        """Bound password inputs without exposing validation input values."""
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise AuthError("Invalid authentication request", 422) from exc

    def _manual_auth(self, request, context, *, register: bool) -> Struct:
        """Manual confirmation issues only a public short session through gRPC."""
        body = self._auth_dto(AuthCredentialsRequest, MessageToDict(request))
        if body.device_id is not None:
            raise AuthError("Remembered device grants require the trusted desktop", 403)
        service = self._require_auth_service(context)
        result = (service.register if register else service.login)(username=body.username, password=body.password)
        self._require_settings_service(context).ensure_user_profile(user_id=result["user_id"])
        return ParseDict(result, Struct())

    def AuthRegister(self, request: Struct, context) -> Struct:  # noqa: N802
        """Register the shared application/vault password over local gRPC."""
        return self._manual_auth(request, context, register=True)

    def AuthLogin(self, request: Struct, context) -> Struct:  # noqa: N802
        """Confirm the shared password without exposing private remember material."""
        return self._manual_auth(request, context, register=False)

    def AuthCurrent(self, request: Struct, context) -> Struct:  # noqa: N802
        """Return authoritative identity and initialization state."""
        token = self._grpc_bearer(context, MessageToDict(request))
        return ParseDict(self._require_auth_service(context).get_status(token), Struct())

    def AuthLogout(self, request: Struct, context) -> Struct:  # noqa: N802
        """Revoke the active account session and its associated remembered grant."""
        payload = MessageToDict(request)
        if payload.get("device_id"):
            raise AuthError("Explicit device operations require the trusted desktop", 403)
        return ParseDict(self._require_auth_service(context).logout(self._grpc_bearer(context, payload)), Struct())

    def AuthChangePassword(self, request: Struct, context) -> Struct:  # noqa: N802
        """Atomically rotate the shared password and invalidate every old grant."""
        payload = MessageToDict(request)
        body = self._auth_dto(AuthPasswordChangeRequest, payload)
        result = self._require_auth_service(context).change_password(self._grpc_bearer(context, payload), body.old_password, body.new_password)
        return ParseDict(result, Struct())

    def AuthAdvanceOnboarding(self, request: Struct, context) -> Struct:  # noqa: N802
        """Persist ordered progress only after a client saves the current page."""
        payload = MessageToDict(request)
        body = self._auth_dto(AuthOnboardingRequest, payload)
        result = self._require_auth_service(context).update_onboarding(self._grpc_bearer(context, payload), body.step)
        return ParseDict(result, Struct())
