"""REST contract tests for typed large, small, and vision-model settings."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from agent_service.api.rest import settings as settings_rest
from agent_service.core.agent_config import AgentConfig
from agent_service.services.settings.service import SettingsService
from tests.db_test_utils import create_test_engine


class _MemoryServiceStub:
    """Expose an isolated database engine to SettingsService."""

    def __init__(self) -> None:
        self.engine = create_test_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )


def _settings_service() -> SettingsService:
    """Build the real service without initializing local models or directories."""

    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    return SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]


def _client(monkeypatch: Any) -> TestClient:
    """Mount the production router against the isolated settings service."""

    service = _settings_service()
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: service)
    app = FastAPI()
    app.include_router(settings_rest.router)
    return TestClient(app)


def test_llm_rest_uses_typed_request_and_response_contract(monkeypatch: Any) -> None:
    """OpenAPI and runtime responses must expose raw and effective visual fields."""

    client = _client(monkeypatch)

    response = client.put(
        "/settings/llm/config",
        json={
            "user_id": "rest-vision",
            "api_key": "large-key",
            "base_url": "https://api.deepseek.com/v1",
            "model_name": "deepseek-chat",
            "vision_model_name": "deepseek-flash",
        },
    )
    operation = client.get("/openapi.json").json()["paths"]["/settings/llm/config"]["put"]

    assert response.status_code == 200
    assert response.json()["vision_model_name"] == "deepseek-flash"
    assert response.json()["effective_vision_api_key"] == "large-key"
    assert response.json()["effective_vision_model_source"] == "explicit"
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/LLMConfigSaveRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/LLMConfigResponse"
    )


def test_llm_rest_rejects_unsafe_vision_endpoint_and_negative_capacity(monkeypatch: Any) -> None:
    """Pydantic and service validation must both surface as HTTP 422 responses."""

    client = _client(monkeypatch)

    unsafe_endpoint = client.put(
        "/settings/llm/config",
        json={
            "user_id": "rest-unsafe",
            "api_key": "large-key",
            "base_url": "https://large.example/v1",
            "model_name": "large-model",
            "vision_base_url": "https://vision.example/v1",
            "vision_model_name": "vision-model",
        },
    )
    negative_capacity = client.put(
        "/settings/llm/config",
        json={"user_id": "rest-invalid", "model_max_output_tokens": -1},
    )

    assert unsafe_endpoint.status_code == 422
    assert "vision_api_key" in unsafe_endpoint.json()["detail"]
    assert negative_capacity.status_code == 422


def test_llm_rest_disables_dsh_after_backbone_change(monkeypatch: Any) -> None:
    """The production LLM endpoint persists DSH disabling in the same save."""
    from types import SimpleNamespace

    service = _settings_service()
    installs: list[bool] = []
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: service)
    monkeypatch.setattr(settings_rest, "_require_dsh_runtime_manager", lambda: SimpleNamespace(start_install=lambda: installs.append(True)))
    app = FastAPI()
    app.include_router(settings_rest.router)
    with TestClient(app) as client:
        model = {"user_id": "dsh-rest", "api_key": "key", "base_url": "https://example.test/v1", "model_name": "deepseek-chat"}
        assert client.put("/settings/llm/config", json=model).status_code == 200
        enabled = client.put("/settings/profile/ingestion", json={"user_id": "dsh-rest", "dsh_coding_agent_enabled": True})
        assert enabled.json()["dsh_coding_agent_enabled"] is True
        assert len(installs) == 1
        assert client.put("/settings/llm/config", json={"user_id": "dsh-rest", "model_name": "gpt-test"}).status_code == 200
        assert client.get("/settings/profile/ingestion", params={"user_id": "dsh-rest"}).json()["dsh_coding_agent_enabled"] is False
        denied = client.put("/settings/profile/ingestion", json={"user_id": "dsh-rest", "dsh_coding_agent_enabled": True})
        assert denied.json()["dsh_coding_agent_enabled"] is False
        assert len(installs) == 1


def test_onboarding_defaults_return_absolute_path_without_creating_user(monkeypatch: Any, tmp_path: Any) -> None:
    """Pre-login defaults must use backend configuration and never initialize profiles."""
    from sqlmodel import Session, select
    from agent_service.models.user_settings import UserSettingsRecord
    service = _settings_service()
    service.config.storage.knowledge_dir = tmp_path / "knowledge"
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: service)
    app = FastAPI()
    app.include_router(settings_rest.router)
    with TestClient(app) as client:
        response = client.get("/settings/onboarding/defaults")
    assert response.status_code == 200
    assert response.json() == {"knowledge_dir": str((tmp_path / "knowledge").resolve())}
    with Session(service.engine) as db:
        assert db.exec(select(UserSettingsRecord)).all() == []
    assert not (tmp_path / "knowledge").exists()
