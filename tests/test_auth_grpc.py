"""Serial authenticated gRPC regressions using one worker and temporary databases.

Every transport fixture closes its channel, server and executor. Business account
identities come from real registration; no hardcoded user IDs or fake credentials.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import grpc
import pytest
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from agent_service.api.grpc import agent_service_pb2 as messages
from agent_service.api.grpc.agent_service_pb2_grpc import AgentServiceStub, add_AgentServiceServicer_to_server
from agent_service.api.grpc.servicer import AgentServiceServicer
from agent_service.services.auth.context import current_identity
from agent_service.services.session.service import SessionService
from agent_service.services.settings.service import SettingsService
from tests.test_auth_service import make_services


def struct(payload: dict) -> Struct:
    """Build real protobuf Struct requests from application DTO mappings."""
    return ParseDict(payload, Struct())


def metadata(state: dict) -> tuple:
    """Use the actual opaque token issued by AuthService."""
    return (("authorization", "Bearer " + state["token"]),)


@pytest.fixture
def transport(tmp_path):
    """Own one local authenticated gRPC listener for the duration of each check."""
    auth, vault = make_services(tmp_path)
    settings = SettingsService(config=auth.config, memory_service=SimpleNamespace(engine=auth.engine))
    sessions = SessionService(config=auth.config, engine=auth.engine)
    agent = SimpleNamespace(config=auth.config, close=lambda: None)
    servicer = AgentServiceServicer(agent=agent, session_service=sessions, settings_service=settings,
                                   vault_service=vault, auth_service=auth)
    executor = ThreadPoolExecutor(max_workers=1)
    server = grpc.server(executor)
    channel = None
    try:
        add_AgentServiceServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        assert port > 0
        server.start()
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        grpc.channel_ready_future(channel).result(timeout=5)
        yield SimpleNamespace(auth=auth, vault=vault, settings=settings, sessions=sessions,
                              servicer=servicer, stub=AgentServiceStub(channel))
    finally:
        if channel is not None:
            channel.close()
        server.stop(0).wait(timeout=5)
        executor.shutdown(wait=True, cancel_futures=True)
        auth.close()
        auth.engine.dispose()


def register(env, username: str = "alice") -> dict:
    """Create one account over the real loopback transport."""
    return MessageToDict(env.stub.AuthRegister(struct({"username": username, "password": "correct horse"}), timeout=5))


def test_protocol_removes_old_vault_credentials_and_has_concrete_handlers() -> None:
    """No obsolete credential RPC or unimplemented business placeholder survives."""
    from agent_service.api.grpc.agent_service_pb2_grpc import AgentServiceServicer as GeneratedBase
    methods = messages.DESCRIPTOR.services_by_name["AgentService"].methods
    names = {method.name for method in methods}
    assert {"AuthRegister", "AuthLogin", "AuthCurrent", "AuthLogout", "AuthChangePassword", "AuthAdvanceOnboarding"} <= names
    assert not names.intersection({"VaultSetup", "VaultUnlock", "VaultResetPassword", "VaultLock", "VaultDebugMasterPassword"})
    assert all(getattr(AgentServiceServicer, name) is not getattr(GeneratedBase, name) for name in names)
    profile = messages.UserProfileResponse.DESCRIPTOR.fields_by_name
    assert [(profile[name].number) for name in ("theme_mode", "safety_enabled", "sensitive_words_enabled")] == [12, 13, 14]


def test_registration_login_and_initialization_use_public_shared_account(transport) -> None:
    """Manual auth has a real normalized identity, no private remember key and ordered progress."""
    env = transport
    state = register(env, "Ａlice")
    assert state["username"] == "alice" and len(state["user_id"]) == 8
    assert "remember" not in state and "vault_key" not in str(state)
    loaded = MessageToDict(env.stub.AuthCurrent(struct({}), metadata=metadata(state), timeout=5))
    assert loaded["onboarding_step"] == 2
    progress = MessageToDict(env.stub.AuthAdvanceOnboarding(struct({"step": 3}), metadata=metadata(state), timeout=5))
    assert progress["onboarding_step"] == 3
    with pytest.raises(grpc.RpcError) as error:
        env.stub.AuthAdvanceOnboarding(struct({"step": 5}), metadata=metadata(state), timeout=5)
    assert error.value.code() == grpc.StatusCode.ABORTED
    logged_in = MessageToDict(env.stub.AuthLogin(struct({"username": "ALICE", "password": "correct horse"}), timeout=5))
    assert logged_in["user_id"] == state["user_id"] and logged_in["onboarding_step"] == 3
    with pytest.raises(grpc.RpcError) as error:
        env.stub.AuthLogin(struct({"username": "alice", "password": "correct horse", "device_id": "desktop-1"}), timeout=5)
    assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED


def test_unsigned_or_foreign_business_claims_are_rejected(transport) -> None:
    """Metadata identity applies to typed requests and resource-only requests alike."""
    env = transport
    alice, bob = register(env), register(env, "bob")
    with pytest.raises(grpc.RpcError) as error:
        env.stub.EnsureUserProfile(messages.UserProfileRequest(), timeout=5)
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    with pytest.raises(grpc.RpcError) as error:
        env.stub.EnsureUserProfile(messages.UserProfileRequest(user_id=bob["user_id"]), metadata=metadata(alice), timeout=5)
    assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
    session = env.stub.CreateSession(messages.SessionCreateRequest(session_name="Owned"), metadata=metadata(alice), timeout=5)
    assert session.user_id == alice["user_id"]
    with pytest.raises(grpc.RpcError) as error:
        env.stub.GetSession(messages.SessionIdRequest(session_id=session.session_id), metadata=metadata(bob), timeout=5)
    assert error.value.code() == grpc.StatusCode.NOT_FOUND
    owned = env.stub.GetSession(messages.SessionIdRequest(session_id=session.session_id), metadata=metadata(alice), timeout=5)
    assert owned.session_id == session.session_id


def test_vault_uses_global_login_and_password_rotation_rejects_old_tokens(transport) -> None:
    """A gRPC vault item decrypts with the same account password after rotation."""
    env = transport
    state = register(env)
    item = MessageToDict(env.stub.VaultCreateItem(struct({"item_type": "secure_note",
        "fields": {"name": "private", "note": "preserved"}}), metadata=metadata(state), timeout=5))["item"]
    env.stub.AuthChangePassword(struct({"old_password": "correct horse", "new_password": "replacement horse"}), metadata=metadata(state), timeout=5)
    with pytest.raises(grpc.RpcError) as error:
        env.stub.VaultStatus(struct({}), metadata=metadata(state), timeout=5)
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    new = MessageToDict(env.stub.AuthLogin(struct({"username": "alice", "password": "replacement horse"}), timeout=5))
    revealed = MessageToDict(env.stub.VaultGetItem(struct({"item_id": item["item_id"], "token": new["token"]}), timeout=5))
    assert revealed["item"]["fields"]["note"] == "preserved"
    env.stub.AuthLogout(struct({}), metadata=metadata(new), timeout=5)
    with pytest.raises(grpc.RpcError):
        env.stub.AuthCurrent(struct({}), metadata=metadata(new), timeout=5)


def test_safety_theme_and_memory_preferences_persist_over_grpc(transport) -> None:
    """Typed profile and Struct preference writes expose the real stored settings."""
    env = transport
    state = register(env)
    env.stub.SaveAppearanceConfig(struct({"theme_mode": "dark"}), metadata=metadata(state), timeout=5)
    env.stub.SaveSafetyConfig(struct({"safety_enabled": False, "sensitive_words_enabled": False}), metadata=metadata(state), timeout=5)
    env.stub.SaveMemoryConfig(struct({"long_term_memory_enabled": False}), metadata=metadata(state), timeout=5)
    profile = env.stub.EnsureUserProfile(messages.UserProfileRequest(), metadata=metadata(state), timeout=5)
    assert profile.theme_mode == "dark" and not profile.safety_enabled and not profile.sensitive_words_enabled
    loaded = MessageToDict(env.stub.GetMemoryConfig(struct({}), metadata=metadata(state), timeout=5))
    assert loaded["long_term_memory_enabled"] is False
    assert env.settings.get_safety_config(user_id=state["user_id"])["safety_enabled"] is False


class RpcAbort(Exception):
    """Capture the standard status of a direct guard-level unit check."""
    def __init__(self, status, detail):
        self.status = status
        super().__init__(detail)


class UnitContext:
    """Supply one immutable RPC identity and controllable active/cancelled state."""
    def __init__(self, token: str, *, peer: str = "ipv4:127.0.0.1:12345"):
        self.token, self.remote_peer = token, peer
        self.active = True

    def invocation_metadata(self):
        """Return the same standard bearer metadata used by live clients."""
        return (("authorization", "Bearer " + self.token),)

    def peer(self):
        """Expose the peer used by local-password guards."""
        return self.remote_peer

    def is_active(self):
        """Allow controlled cancellation while iterating a stream."""
        return self.active

    def abort(self, status, detail):
        """Match gRPC's terminal exception behavior without opening another listener."""
        raise RpcAbort(status, detail)


@pytest.mark.parametrize("finish", ["logout", "cancel", "close"])
def test_stream_revocation_cancellation_and_close_release_context(transport, finish: str) -> None:
    """A stream cannot emit after revocation and always closes its inner iterator."""
    env = transport
    state = register(env)
    context = UnitContext(state["token"])
    closed = []

    def events(request, rpc_context):
        """Stand in for a model iterator whose lifecycle must be released by the guard."""
        try:
            yield "first"
            yield "second"
        finally:
            closed.append(True)

    stream = env.servicer._guard_stream("StreamRun", events)(messages.RunRequest(), context)
    assert next(stream) == "first"
    assert current_identity.get().user_id == state["user_id"]
    if finish == "close":
        stream.close()
    else:
        if finish == "logout":
            env.auth.logout(state["token"])
            expected = grpc.StatusCode.UNAUTHENTICATED
        else:
            context.active = False
            expected = grpc.StatusCode.CANCELLED
        with pytest.raises(RpcAbort) as error:
            next(stream)
        assert error.value.status == expected
    assert closed == [True] and current_identity.get() is None


def test_remote_auth_and_authless_registration_fail_closed(transport) -> None:
    """Loopback passwords and startup authentication cannot be bypassed by helpers."""
    env = transport
    with pytest.raises(RpcAbort) as error:
        env.servicer.AuthLogin(struct({"username": "alice", "password": "correct horse"}), UnitContext("", peer="ipv4:203.0.113.1:12345"))
    assert error.value.status == grpc.StatusCode.PERMISSION_DENIED
    helper = AgentServiceServicer(agent=SimpleNamespace(close=lambda: None), session_service=SimpleNamespace())
    with pytest.raises(ValueError, match="AuthService"):
        add_AgentServiceServicer_to_server(helper, SimpleNamespace())


def test_cancel_session_requires_an_existing_owned_chat(transport) -> None:
    """Unknown/empty/foreign session IDs never reach the runtime cancellation hook."""
    env = transport
    owner, other = register(env), register(env, "other")
    calls = []
    env.servicer._agent.cancel_session = calls.append
    session = env.stub.CreateSession(messages.SessionCreateRequest(session_name="cancellable"), metadata=metadata(owner), timeout=5)
    for session_id, state in (("", owner), ("not-persisted", owner), (session.session_id, other)):
        with pytest.raises(grpc.RpcError) as error:
            env.stub.CancelSession(messages.CancelRequest(session_id=session_id), metadata=metadata(state), timeout=5)
        assert error.value.code() == grpc.StatusCode.NOT_FOUND
    assert calls == []
    result = env.stub.CancelSession(messages.CancelRequest(session_id=session.session_id), metadata=metadata(owner), timeout=5)
    assert result.ok and calls == [session.session_id]
