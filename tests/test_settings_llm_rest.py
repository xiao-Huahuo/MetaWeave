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
