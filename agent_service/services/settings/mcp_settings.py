"""MCP settings persistence and request-local knowledge-library selection; mixed into SettingsService."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from sqlmodel import Session
from agent_service.models.user_settings import UserSettingsRecord

selected_library: ContextVar[tuple[str, str] | None] = ContextVar("mcp_selected_library", default=None)


@contextmanager
def use_library(user_id: str, library_id: str) -> Iterator[None]:
    """Select an owned library only for this request, without changing the user's active library."""
    token = selected_library.set((user_id, library_id))
    try:
        yield
    finally:
        selected_library.reset(token)


class McpSettingsMixin:
    """Read effective defaults and write only explicit MCP overrides via SettingsService."""

    def get_mcp_settings(self, *, user_id: str, role: str) -> dict:
        """Return merged client/server configuration and the persisted override separately."""
        if not user_id.strip() or role not in {"client", "server"}:
            raise ValueError("Invalid MCP settings identity/role")
        defaults = self._mcp_defaults(role)
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, user_id)
            raw = json.loads(record.mcp_settings or "{}") if record else {}
        override = raw.get(role, {})
        return {"config": {**defaults, **override}, "override": override}

    def save_mcp_settings(self, *, user_id: str, role: str, payload: dict) -> dict:
        """Update a role's overrides, removing null fields to restore service defaults."""
        self.ensure_user_profile(user_id=user_id)
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, user_id)
            raw = json.loads(record.mcp_settings or "{}")
            defaults = self._mcp_defaults(role)
            raw[role] = {k: v for k, v in payload.items() if v is not None and v != defaults.get(k)}
            record.mcp_settings = json.dumps(raw, ensure_ascii=False)
            db.add(record)
            db.commit()
        return self.get_mcp_settings(user_id=user_id, role=role)
    def _mcp_defaults(self, role: str) -> dict:
        """Process defaults stay outside user records and remain centrally configurable."""
        return ({"enabled": self.config.mcp.enabled} if role == "client" else {
            "enabled": False, "host": self.config.mcp.server_host,
            "port": self.config.mcp.server_port, "tools": [],
        })
