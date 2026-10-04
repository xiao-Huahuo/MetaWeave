"""Real REST account/session/vault integration against an isolated migrated database."""
from __future__ import annotations
from datetime import timedelta
from types import SimpleNamespace
import base64
import re
from pathlib import Path
from typing import Any
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select
from agent_service.api.rest import router
from agent_service.core.agent_config import AgentConfig
from agent_service.models.account import Account, AuthDevice
from agent_service.services.auth.service import AuthService
from agent_service.services.settings.service import SettingsService
from agent_service.services.vault.service import VaultService
from agent_service.services.session.service import SessionService
from agent_service.services.message.service import MessageService
from agent_service.services.feedback.service import FeedbackService
from tests.db_test_utils import create_test_engine


def fixture(tmp_path: Path):
    """Mount production routes/services; no local model, fake login or external network."""
    config = AgentConfig.load_config({"storage": {"project_root": str(tmp_path), "base_data_dir": str(tmp_path / "runtime"), "knowledge_dir": str(tmp_path / "knowledge")}, "limits": {"vault_password_kdf_iterations": 1000, "vault_encryption_kdf_iterations": 1000}, "server": {"desktop_auth_nonce": "private-desktop-nonce"}}, load_env=False, load_dotenv=False, ensure_models=False, ensure_directories=False)
    engine = create_test_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    auth = AuthService(config=config, engine=engine)
    settings = SettingsService(config=config, memory_service=SimpleNamespace(engine=engine))
    app = FastAPI()
    app.state.services = SimpleNamespace(config=config, database_engine=engine, auth_service=auth, settings_service=settings, vault_service=VaultService(config=config, engine=engine), session_service=SessionService(config=config, engine=engine, create_tables=False), message_service=MessageService(config=config, engine=engine, create_tables=False))
    app.state.services.feedback_service = FeedbackService(engine=engine, create_tables=False)
    app.include_router(router)
    return TestClient(app), auth, settings, engine


def register(client: TestClient, name: str, *, device: str | None = None) -> dict:
    """Use the actual manual registration endpoint and return its session state."""
    body = {"username": name, "password": "correct-password"}
    headers = {}
    if device:
        body["device_id"] = device
        headers["X-Desktop-Auth"] = "private-desktop-nonce"
    result = client.post("/auth/register", json=body, headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def test_manual_login_shared_vault_and_old_auth_removed(tmp_path: Path) -> None:
    """The account password alone opens the vault; old independent entries are gone."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        state = register(client, "Account")
        assert re.fullmatch(r"[1-9][0-9]{7}", state["user_id"])
        assert state["onboarding_step"] == 2 and not state["onboarding_completed"]
        assert "remember" not in state
        assert client.get("/auth/me").json()["user_id"] == state["user_id"]
        assert client.get("/vault/status").json()["configured"] is True
        item = client.post("/vault/items", json={"item_type": "login", "fields": {"name": "example", "password": "saved-site-password"}})
        assert item.status_code == 200, item.text
        assert client.get("/vault/items").status_code == 200
        for path in ("/vault/setup", "/vault/unlock", "/vault/reset-password", "/vault/debug/master-password", "/vault/lock"):
            assert client.get(path).status_code == 404
        assert client.post("/auth/register", json={"username": "ACCOUNT", "password": "correct-password"}).status_code == 409
        assert client.post("/auth/login", json={"username": "Account", "password": "wrong-password"}).status_code == 401
        with Session(engine) as db:
            assert db.get(Account, state["user_id"]).password_hash != "correct-password"
    finally:
        auth.close(); engine.dispose()


def test_device_expiry_manual_renewal_and_private_material(tmp_path: Path) -> None:
    """Only trusted desktop sees remember material; 30-day restoration never renews."""
    client, auth, _, engine = fixture(tmp_path)
    desktop = {"X-Desktop-Auth": "private-desktop-nonce"}
    try:
        blocked = client.post("/auth/register", json={"username": "private", "password": "correct-password", "device_id": "device"})
        assert blocked.status_code == 403
        state = register(client, "private", device="device")
        remember = state["remember"]
        token_headers = {**desktop, "Authorization": "Bearer " + state["token"]}
        blob = base64.b64encode(b"opaque-os-ciphertext").decode()
        assert client.put("/auth/device/remembered", json={"device_id": "device", "sealed_payload": blob}, headers=token_headers).status_code == 200
        assert client.get("/auth/device/remembered", params={"device_id": "device"}).status_code == 403
        stored = client.get("/auth/device/remembered", params={"device_id": "device"}, headers=desktop).json()
        assert stored["sealed_payload"] == blob
        restore_body = {key: remember[key] for key in ("device_id", "credential", "vault_key", "password_version")}
        restored = client.post("/auth/restore", json=restore_body, headers=desktop)
        assert restored.status_code == 200
        assert "remember" not in restored.json()
        assert client.get("/auth/device/remembered", params={"device_id": "device"}, headers=desktop).json()["expires_at"] == stored["expires_at"]
        now = auth._now()
        auth._now = lambda: now + timedelta(days=30, seconds=1)
        assert client.post("/auth/restore", json=restore_body, headers=desktop).status_code == 401
        manual = client.post("/auth/login", json={"username": "private", "password": "correct-password", "device_id": "device"}, headers=desktop)
        assert manual.status_code == 200
        assert manual.json()["remember"]["credential"] != remember["credential"]
    finally:
        auth.close(); engine.dispose()


def test_cross_user_identity_sessions_and_safety_are_isolated(tmp_path: Path) -> None:
    """A valid session cannot choose another user or read that user's session by ID."""
    client, auth, settings, engine = fixture(tmp_path)
    try:
        first = register(client, "first")
        first_headers = {"Authorization": "Bearer " + first["token"]}
        created = client.post("/sessions", json={"user_id": first["user_id"], "session_name": "private"}, headers=first_headers)
        assert created.status_code == 200, created.text
        second = register(client, "second")
        second_headers = {"Authorization": "Bearer " + second["token"]}
        assert client.get("/sessions", params={"user_id": first["user_id"]}, headers=second_headers).status_code == 403
        assert client.get("/sessions/" + created.json()["session_id"], headers=second_headers).status_code == 404
        assert client.put("/settings/safety/config", json={"user_id": first["user_id"], "sensitive_words_enabled": False, "safety_enabled": False}, headers=first_headers).status_code == 200
        assert settings.get_safety_config(user_id=first["user_id"])["safety_enabled"] is False
        assert settings.get_safety_config(user_id=second["user_id"])["safety_enabled"] is True
        assert client.put("/settings/appearance/config", json={"user_id": first["user_id"], "theme_mode": "dark"}, headers=first_headers).status_code == 200
        assert settings.get_appearance_config(user_id=first["user_id"])["theme_mode"] == "dark"
        assert settings.get_appearance_config(user_id=second["user_id"])["theme_mode"] == "light"
    finally:
        auth.close(); engine.dispose()


def test_password_validation_never_echoes_secret_values(tmp_path: Path) -> None:
    """Authentication DTO errors must not include plaintext password inputs."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        result = client.post("/auth/register", json={"username": "bounded", "password": "xyz"})
        assert result.status_code == 422
        assert "xyz" not in result.text
        assert client.get("/vault/items", headers={"Authorization": "Bearer fabricated"}).status_code == 401
    finally:
        auth.close(); engine.dispose()


def test_query_identity_cannot_be_hidden_by_json_or_duplicate_query(tmp_path: Path) -> None:
    """Validate independent query/body sources instead of trusting the final merged dict."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        first = register(client, "first")
        second = register(client, "second")
        headers = {"Authorization": "Bearer " + second["token"]}
        result = client.request("GET", "/settings/profile", params={"user_id": first["user_id"]}, json={"user_id": second["user_id"]}, headers=headers)
        assert result.status_code == 403
        result = client.get("/settings/profile", params=[("user_id", first["user_id"]), ("user_id", second["user_id"])], headers=headers)
        assert result.status_code == 403
    finally:
        auth.close(); engine.dispose()


def test_cookie_session_rejects_other_loopback_origin(tmp_path: Path) -> None:
    """SameSite is not enough to authorize an unrelated service on another local port."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        state = register(client, "origin")
        result = client.put("/settings/memory/config", json={"user_id": state["user_id"], "long_term_memory_enabled": False}, headers={"Origin": "http://127.0.0.1:9999"})
        assert result.status_code == 403
        result = client.post("/auth/login", json={"username": "origin", "password": "correct-password"}, headers={"Origin": "http://127.0.0.1:9999"})
        assert result.status_code == 403
    finally:
        auth.close(); engine.dispose()


def test_feedback_without_user_filter_remains_account_scoped(tmp_path: Path) -> None:
    """An omitted list filter must never turn the account endpoint into a global list."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        first = register(client, "first")
        own = client.post("/feedback", json={"user_id": first["user_id"], "content": "first private feedback"})
        assert own.status_code == 200, own.text
        second = register(client, "second")
        result = client.get("/feedback")
        assert result.status_code == 200, result.text
        assert result.json()["feedback"] == []
        assert client.delete("/feedback/" + own.json()["feedback_id"]).status_code == 404
        result = client.get("/feedback", headers={"Authorization": "Bearer " + first["token"]})
        assert [row["user_id"] for row in result.json()["feedback"]] == [first["user_id"]]
        assert first["user_id"] != second["user_id"]
    finally:
        auth.close(); engine.dispose()


def test_stateless_calls_use_verified_account_and_cancel_requires_owned_session(tmp_path: Path) -> None:
    """Default test/stream calls must not create a shared fabricated user identity."""
    client, auth, _, engine = fixture(tmp_path)
    calls = []
    def run_once(**kwargs):
        calls.append(kwargs)
        return {"ok": True}
    def stream_run(**kwargs):
        calls.append(kwargs)
        yield {"event": "done"}
    client.app.state.services.agent = SimpleNamespace(run_once=run_once, stream_run=stream_run, cancel_session=lambda session_id: calls.append({"cancelled": session_id}))
    try:
        state = register(client, "stateless")
        assert client.get("/agent/test").status_code == 200
        assert client.get("/agent/stream-run", params={"prompt": "hello"}).status_code == 200
        assert [call["user_id"] for call in calls] == [state["user_id"], state["user_id"]]
        assert all(call["session_id"] not in ("test-session", "stream-run-session", "") for call in calls)
        assert client.post("/agent/cancel", json={"session_id": "missing-session"}).status_code == 404
        assert len(calls) == 2
    finally:
        auth.close(); engine.dispose()
