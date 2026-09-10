"""Shared tag-color palette persistence and transport contract tests."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from agent_service.api.grpc.agent_service_pb2_grpc import AgentServiceStub, add_AgentServiceServicer_to_server
from agent_service.api.grpc.servicer import AgentServiceServicer
from agent_service.api.rest import settings as settings_rest
from agent_service.core.agent_config import AgentConfig
from agent_service.models.user_settings import UserSettingsRecord
from agent_service.services.settings.service import SettingsService


class _MemoryServiceStub:
    """Provide one isolated relation engine for SettingsService."""

    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)


class _StubAgent:
    """Match the gRPC service shutdown contract."""

    def close(self) -> None:
        """Release no resources in the isolated contract test."""


class _StubSessionService:
    """Supply the unused session dependency required by the gRPC servicer."""


def _service() -> SettingsService:
    """Create SettingsService with deterministic default tag colors."""

    config = AgentConfig.load_config({}, load_env=False, ensure_directories=False, ensure_models=False)
    return SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]


def _struct(payload: dict[str, object]) -> Struct:
    """Convert a dictionary into the generic settings RPC payload."""

    return ParseDict(payload, Struct())


def test_tag_colors_persist_and_reset_to_service_defaults() -> None:
    """Store explicit overrides and clear them without writing defaults into the user row."""

    service = _service()
    colors = ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"]
    assert "tag_colors" in {column["name"] for column in inspect(service.engine).get_columns("user_settings")}

    saved = service.save_appearance_config(user_id="u1", tag_colors=colors, tag_colors_translucent=False)
    assert saved["tag_colors"] == colors
    assert saved["tag_colors_translucent"] is False
    assert service.ensure_user_profile(user_id="u1")["tag_colors"] == colors

    reset = service.save_appearance_config(
        user_id="u1",
        tag_colors=[],
        reset_tag_colors_translucent=True,
    )
    assert reset["tag_colors"] == service.config.appearance.tag_colors
    assert reset["tag_colors_translucent"] is True
    with Session(service.engine) as db:
        record = db.exec(select(UserSettingsRecord).where(UserSettingsRecord.user_id == "u1")).one()
        assert record.tag_colors == ""
        assert record.tag_colors_translucent is None


def test_tag_colors_require_six_hex_values() -> None:
    """Reject partial or malformed palettes at the service boundary."""

    service = _service()
    with pytest.raises(ValueError, match="exactly 6"):
        service.save_appearance_config(user_id="u1", tag_colors=["#123456"])
    with pytest.raises(ValueError, match="exactly 6"):
        service.save_appearance_config(user_id="u1", tag_colors=["#123456"] * 5 + ["invalid"])


def test_tag_colors_keep_rest_and_grpc_contracts_equivalent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist and load the same six colors through REST and generic Struct RPC."""

    service = _service()
    rest_colors = ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"]
    grpc_colors = ["#abcdef", "#bcdef0", "#cdef01", "#def012", "#ef0123", "#f01234"]
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: service)
    rest_saved = asyncio.run(settings_rest.save_appearance_config({
        "user_id": "u1",
        "tag_colors": rest_colors,
        "tag_colors_translucent": False,
    }))
    assert rest_saved["tag_colors"] == rest_colors
    assert rest_saved["tag_colors_translucent"] is False

    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_StubAgent(),  # type: ignore[arg-type]
            session_service=_StubSessionService(),  # type: ignore[arg-type]
            settings_service=service,
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = AgentServiceStub(channel)
        saved = MessageToDict(stub.SaveAppearanceConfig(_struct({
            "user_id": "u1",
            "tag_colors": grpc_colors,
            "tag_colors_translucent": False,
        }), timeout=5))
        loaded = MessageToDict(stub.GetAppearanceConfig(_struct({"user_id": "u1"}), timeout=5))
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)

    assert saved["tag_colors"] == grpc_colors
    assert saved["tag_colors_translucent"] is False
    assert loaded["tag_colors"] == grpc_colors
    assert loaded["tag_colors_translucent"] is False
