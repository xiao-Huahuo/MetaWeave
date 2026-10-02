"""User-owned MCP CRUD, live management, secret-free import/export and Agent tool snapshots."""
from __future__ import annotations
import json
import re
import hashlib
from uuid import NAMESPACE_URL, uuid4, uuid5
from typing import Any
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from agent_service.models.mcp import McpConnectionRecord
from agent_service.models.session import utc_now
from agent_service.schemas.mcp import McpClientSettings, McpConnectionCreate
from agent_service.services.mcp_client.runtime import McpClientRuntime
from agent_service.services.mcp_client.secrets import ConnectionSecrets
from agent_service.tools.builtin import BuiltinToolDefinition


class McpClientService:
    """Connect settings/persistence to runtime actors without embedding protocol logic in routes."""

    def __init__(self, *, config, settings_service, engine) -> None:
        """Use the application database and deferred deployment-key/runtime initialization."""
        self.config, self.settings, self.engine = config, settings_service, engine
        self.runtime = McpClientRuntime(config)
        self.secrets = None

    def start(self) -> None:
        """Initialize cipher and owner loop as part of application lifespan."""
        self.secrets = ConnectionSecrets(self.config)
        self.runtime.start()

    def shutdown(self) -> None:
        """Release all actors and subprocesses."""
        self.runtime.shutdown()

    def _records(self, user_id: str) -> list[McpConnectionRecord]:
        """Read only this user's persisted connection records."""
        with Session(self.engine) as db:
            persisted = list(db.exec(select(McpConnectionRecord).where(McpConnectionRecord.user_id == user_id)).all())
        known_ids = {record.connection_id for record in persisted}
        records = [record for record in persisted if not record.payload.get("_removed")]
        # Preserve explicitly configured process servers without copying service defaults into user rows.
        for entry in self.config.mcp.servers:
            if not entry.get("enabled", True):
                continue
            server_id = str(entry.get("server_id") or "").strip()
            if not server_id:
                continue
            connection_id = "mcpdefault_" + uuid5(NAMESPACE_URL, user_id + ":" + server_id).hex
            if connection_id in known_ids:
                continue
            draft = McpConnectionCreate.model_validate({key: value for key, value in {
                **entry, "name": server_id, "transport": entry.get("transport", "http" if entry.get("url") else "stdio"),
            }.items() if key in McpConnectionCreate.model_fields}).model_dump()
            secret_values = {field: draft.pop(field) for field in ("env", "headers")}
            records.append(McpConnectionRecord(connection_id=connection_id, user_id=user_id, name=server_id,
                payload=draft, encrypted_secrets=self.secrets.encrypt(secret_values), revision=0))
        return records

    def _owned(self, user_id: str, connection_id: str) -> McpConnectionRecord:
        """Resolve an owned record; never reveal another user's connection."""
        with Session(self.engine) as db:
            record = db.get(McpConnectionRecord, connection_id)
            if record is not None and record.user_id == user_id and not record.payload.get("_removed"):
                return record
        record = next((row for row in self._records(user_id) if row.connection_id == connection_id), None)
        if record is None:
            raise KeyError("MCP 连接不存在")
        return record

    def _payload(self, record: McpConnectionRecord) -> dict:
        """Decrypt env/header values only at the connection boundary."""
        return {**record.payload, **self.secrets.decrypt(record.encrypted_secrets)}

    def list(self, user_id: str) -> dict:
        """Return effective config and redacted rows with separate live state."""
        settings = self.settings.get_mcp_settings(user_id=user_id, role="client")
        snapshots = self.runtime.submit(self.runtime.snapshots())
        rows = []
        for record in self._records(user_id):
            secret_values = self.secrets.decrypt(record.encrypted_secrets)
            rows.append({**record.payload, "env": {k: None for k in secret_values.get("env", {})},
                         "headers": {k: None for k in secret_values.get("headers", {})},
                         "connection_id": record.connection_id, "revision": record.revision,
                         "inherited": record.revision == 0,
                         **snapshots.get((user_id, record.connection_id), {"state": "stopped", "error": "", "tools": []})})
        return {**settings, "connections": rows}

    def save(self, user_id: str, payload: dict, connection_id: str = "", revision: int | None = None) -> dict:
        """Persist validated edits atomically, preserve null secrets, then apply to this connection."""
        draft = McpConnectionCreate.model_validate(payload).model_dump()
        old = self._owned(user_id, connection_id) if connection_id else None
        if old is not None and revision != old.revision:
            raise ValueError("配置已被修改，请刷新后重试")
        previous = self.secrets.decrypt(old.encrypted_secrets) if old else {}
        secret_values = {}
        for field in ("env", "headers"):
            secret_values[field] = {}
            for name, value in draft.pop(field).items():
                if value is None:
                    if name not in previous.get(field, {}):
                        raise ValueError(f"{field} 中的 {name} 需要填写值")
                    value = previous[field][name]
                secret_values[field][name] = value
        self.settings.ensure_user_profile(user_id=user_id)
        encrypted = self.secrets.encrypt(secret_values)
        try:
            with Session(self.engine) as db:
                if old and db.get(McpConnectionRecord, connection_id) is not None:
                    result = db.exec(update(McpConnectionRecord).where(
                        McpConnectionRecord.connection_id == connection_id,
                        McpConnectionRecord.user_id == user_id, McpConnectionRecord.revision == revision,
                    ).values(name=draft["name"], payload=draft, encrypted_secrets=encrypted,
                             revision=old.revision + 1, updated_at=utc_now()))
                    if result.rowcount != 1:
                        raise ValueError("配置已被修改，请刷新后重试")
                else:
                    connection_id = old.connection_id if old else f"mcp_{uuid4().hex}"
                    db.add(McpConnectionRecord(connection_id=connection_id, user_id=user_id,
                        name=draft["name"], payload=draft, encrypted_secrets=encrypted))
                db.commit()
        except IntegrityError:
            raise ValueError("服务名称已存在") from None
        self.apply(user_id, connection_id)
        return next(row for row in self.list(user_id)["connections"] if row["connection_id"] == connection_id)

    def apply(self, user_id: str, connection_id: str, reconnect: bool = False, cancel_event=None) -> dict:
        """Apply persisted configuration; disabled connections stop rather than appear connected."""
        record = self._owned(user_id, connection_id)
        if not self.settings.get_mcp_settings(user_id=user_id, role="client")["config"]["enabled"] or not record.payload["enabled"]:
            self.runtime.submit(self.runtime.stop((user_id, connection_id)))
            return {"state": "stopped", "error": "", "tools": []}
        payload = self._payload(record)
        return self.runtime.submit(self.runtime.connect((user_id, connection_id), payload, reconnect),
                                   payload["timeout_seconds"] + self.config.mcp.shutdown_timeout_seconds, cancel_event)

    def set_enabled(self, user_id: str, enabled: bool | None) -> dict:
        """Save a user override and reconcile each independently owned connection."""
        enabled = McpClientSettings.model_validate({"enabled": enabled}).enabled
        self.settings.save_mcp_settings(user_id=user_id, role="client", payload={"enabled": enabled})
        for record in self._records(user_id):
            self.apply(user_id, record.connection_id)
        return self.list(user_id)

    def delete(self, user_id: str, connection_id: str) -> None:
        """Remove an owned configuration and close its runtime actor."""
        self._owned(user_id, connection_id)
        self.runtime.submit(self.runtime.stop((user_id, connection_id)))
        with Session(self.engine) as db:
            record = db.get(McpConnectionRecord, connection_id)
            if connection_id.startswith("mcpdefault_"):
                # A tombstone suppresses an inherited connection only for this user; the service template remains intact.
                record = record or McpConnectionRecord(connection_id=connection_id, user_id=user_id, name="")
                record.name = "removed_" + connection_id
                record.payload = {"_removed": True}
                record.encrypted_secrets = ""
                db.add(record)
            else:
                db.delete(record)
            db.commit()

    def test(self, user_id: str, payload: dict, connection_id: str = "") -> dict:
        """Test a draft with an isolated, always-released SDK connection."""
        draft = McpConnectionCreate.model_validate(payload).model_dump()
        stored = self._payload(self._owned(user_id, connection_id)) if connection_id else {}
        for field in ("env", "headers"):
            for key, value in draft[field].items():
                if value is None:
                    if key not in stored.get(field, {}):
                        raise ValueError(f"{key} 需要填写值")
                    draft[field][key] = stored[field][key]
        key = (user_id, f"test_{uuid4().hex}")
        async def probe():
            """The same owner loop performs both test initialization and guaranteed cleanup."""
            try:
                return await self.runtime.connect(key, draft)
            finally:
                await self.runtime.stop(key)
        return self.runtime.submit(probe(), draft["timeout_seconds"] + self.config.mcp.shutdown_timeout_seconds)

    def export(self, user_id: str) -> dict:
        """Export editable configurations without credential values, live state or internal IDs."""
        rows = self.list(user_id)["connections"]
        return {"connections": [{k: v for k, v in row.items() if k in McpConnectionCreate.model_fields and k not in {"env", "headers"}} for row in rows]}

    def import_preview(self, user_id: str, value: Any) -> list[dict]:
        """Parse native connections or common mcpServers JSON and report conflicts before writes."""
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict) and "mcpServers" in value:
            value = [dict(name=name, transport="http" if entry.get("url") else "stdio", **entry)
                     for name, entry in value["mcpServers"].items()]
        elif isinstance(value, dict):
            value = value.get("connections", [value])
        if not isinstance(value, list) or not value:
            raise ValueError("配置必须包含连接列表")
        known = {r.name for r in self._records(user_id)}
        seen = set()
        result = []
        for index, entry in enumerate(value):
            try:
                entry = dict(entry)
                entry["name"] = entry.pop("server_id", entry.get("name", ""))
                draft = McpConnectionCreate.model_validate(entry).model_dump()
                duplicate = draft["name"] in seen
                seen.add(draft["name"])
                result.append({"index": index, "draft": draft, "conflict": draft["name"] in known,
                               "error": "导入文件包含重复名称" if duplicate else ""})
            except Exception:
                result.append({"index": index, "error": "配置字段无效，请检查名称、连接方式、程序或地址"})
        return result

    def tool_snapshot(self, user_id: str, access_mode: str = "sandbox", cancel_event=None) -> list[BuiltinToolDefinition]:
        """Build one immutable per-turn tool catalogue; callable rechecks live grants before use."""
        if not self.settings.get_mcp_settings(user_id=user_id, role="client")["config"]["enabled"]:
            return []
        definitions = []
        for record in self._records(user_id):
            if not record.payload["enabled"]:
                continue
            snapshot = self.apply(user_id, record.connection_id, cancel_event=cancel_event)
            for tool in snapshot["tools"]:
                if tool["name"] in record.payload["disabled_tools"]:
                    continue
                if access_mode != "full_access" and not tool["annotations"].get("readOnlyHint", False):
                    continue
                public_name = "mcp__" + hashlib.sha256((record.connection_id + tool["name"]).encode()).hexdigest()[:12] + "__" + re.sub(r"[^a-zA-Z0-9_-]", "_", tool["name"])[:40]
                def invoke(_id=record.connection_id, _revision=record.revision, _name=tool["name"], _schema=tool["input_schema"], **arguments):
                    """Reject revoked/changed grants rather than executing against a different saved config."""
                    current = self._owned(user_id, _id)
                    if current.revision != _revision or not current.payload["enabled"] or _name in current.payload["disabled_tools"] or not self.settings.get_mcp_settings(user_id=user_id, role="client")["config"]["enabled"]:
                        raise PermissionError("MCP 配置或权限已改变，请在下一轮重试")
                    from agent_service.tools.runtime_context import get_tool_runtime
                    from jsonschema import Draft202012Validator
                    Draft202012Validator(_schema).validate(arguments)
                    try:
                        cancel = get_tool_runtime().cancellation_event
                    except RuntimeError:
                        cancel = None
                    result = self.runtime.submit(self.runtime.call((user_id, _id), _name, arguments), current.payload["timeout_seconds"] + 1, cancel)
                    if result.is_error:
                        raise RuntimeError(result.text or "外部 MCP 工具返回错误")
                    if result.text:
                        return result.text
                    if result.structured_content is not None:
                        return json.dumps(result.structured_content, ensure_ascii=False)
                    return json.dumps([item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                                       for item in result.content], ensure_ascii=False)
                definitions.append(BuiltinToolDefinition(name=public_name, description=tool["description"],
                    args_schema=tool["input_schema"], function=invoke, display_name=f"{record.name} · {tool.get('title') or tool['name']}"))
        return definitions
