"""gRPC contract tests for large, small, and vision-model settings.

These tests run a loopback gRPC server with the real SettingsService and an isolated in-memory
database. No remote model endpoint is contacted.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import grpc
from sqlalchemy.pool import StaticPool

from agent_service.api.grpc.agent_service_pb2 import (
    LLMConfigRequest,
    LLMConfigResponse,
    LLMConfigSaveRequest,
)
from agent_service.api.grpc.agent_service_pb2_grpc import (
    AgentServiceStub,
    add_AgentServiceServicer_to_server,
)
from agent_service.api.grpc.servicer import AgentServiceServicer
from agent_service.core.agent_config import AgentConfig
from agent_service.services.settings.service import SettingsService
from tests.db_test_utils import create_test_engine


class _MemoryServiceStub:
    """Expose the isolated engine expected by SettingsService."""

    def __init__(self) -> None:
        self.engine = create_test_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )


class _AgentStub:
    """Provide only configuration and shutdown members required by the gRPC servicer."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def close(self) -> None:
        """The test owns no Agent runtime resources."""


def _settings_service() -> SettingsService:
    """Build a real settings service without filesystem or model initialization."""

    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    return SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]


def test_llm_grpc_round_trip_includes_effective_vision_fields() -> None:
    """The generated protocol and handler must preserve all visual endpoint fields."""

    settings_service = _settings_service()
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_AgentStub(settings_service.config),  # type: ignore[arg-type]
            session_service=SimpleNamespace(),  # type: ignore[arg-type]
            settings_service=settings_service,
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = AgentServiceStub(channel)
        saved = stub.SaveLLMConfig(
            LLMConfigSaveRequest(
                user_id="grpc-vision",
                vision_api_key="vision-key",
                vision_base_url="https://vision.example/v1",
                vision_model_name="vision-model",
            ),
            timeout=5,
        )
        loaded = stub.GetLLMConfig(LLMConfigRequest(user_id="grpc-vision"), timeout=5)
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)

    assert isinstance(saved, LLMConfigResponse)
    assert saved.vision_api_key == "vision-key"
    assert saved.effective_vision_api_key == "vision-key"
    assert saved.effective_vision_model_source == "explicit"
    assert loaded.vision_base_url == "https://vision.example/v1"
    assert loaded.effective_vision_model_name == "vision-model"


def test_llm_grpc_rejects_cross_endpoint_key_inheritance() -> None:
    """A gRPC caller must receive INVALID_ARGUMENT for a visual endpoint without its own key."""

    settings_service = _settings_service()
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_AgentStub(settings_service.config),  # type: ignore[arg-type]
            session_service=SimpleNamespace(),  # type: ignore[arg-type]
            settings_service=settings_service,
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = AgentServiceStub(channel)
        try:
            stub.SaveLLMConfig(
                LLMConfigSaveRequest(
                    user_id="grpc-unsafe",
                    api_key="large-key",
                    base_url="https://large.example/v1",
                    model_name="large-model",
                    vision_base_url="https://vision.example/v1",
                    vision_model_name="vision-model",
                ),
                timeout=5,
            )
        except grpc.RpcError as exc:
            assert exc.code() is grpc.StatusCode.INVALID_ARGUMENT
            assert "vision_api_key" in exc.details()
        else:
            raise AssertionError("cross-endpoint key inheritance must be rejected")
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)
