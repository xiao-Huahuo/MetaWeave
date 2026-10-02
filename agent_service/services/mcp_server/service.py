"""MCP server settings, credential identity, domain grants and durable redacted call outcomes."""
from __future__ import annotations
import hashlib
import secrets
import time
from datetime import timezone
from uuid import uuid4
from sqlmodel import Session, select
from agent_service.models.mcp import McpCredentialRecord, McpAccessRecord
from agent_service.schemas.mcp import McpCredentialCreate, McpServerSettings
from agent_service.services.mcp_server.catalog import tool_catalog, execute_business
from agent_service.services.settings.mcp_settings import use_library


class McpServerService:
    """Separate management persistence from protocol ingress and listener lifecycle."""

    def __init__(self, *, config, settings_service, engine) -> None:
        """Hold shared application dependencies; attach the listener runtime after assembly."""
        self.config, self.settings, self.engine = config, settings_service, engine
        self.runtime = None
        self.services = None

    def status(self, user_id: str) -> dict:
        """Return persisted settings, real listener state and the explicit tool catalogue."""
        settings = self.settings.get_mcp_settings(user_id=user_id, role="server")
        config = settings["config"]
        host = config["host"]
        address = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
        if ":" in address:
            address = f"[{address}]"
        return {**settings, **self.runtime.status(user_id), "url": f"http://{address}:{config['port']}/mcp",
                "catalog": tool_catalog(), "credentials": self.credentials(user_id)}

    def save_sync(self, user_id: str, payload: dict) -> dict:
        """Bridge gRPC workers to the application-owned listener loop."""
        import asyncio
        future = asyncio.run_coroutine_threadsafe(self.save(user_id, payload), self.runtime.loop)
        try:
            return future.result(self.config.mcp.shutdown_timeout_seconds * 3)
        except TimeoutError:
            future.cancel()
            raise

    async def save(self, user_id: str, payload: dict) -> dict:
        """Persist explicit overrides and reconcile a real listener; failure remains actionable."""
        draft = McpServerSettings.model_validate({**self.settings.get_mcp_settings(user_id=user_id, role="server")["config"], **payload})
        unknown = set(draft.tools) - {t["name"] for t in tool_catalog()}
        if unknown:
            raise ValueError("开放工具包含未知名称")
        self.settings.save_mcp_settings(user_id=user_id, role="server", payload=draft.model_dump())
        await self.runtime.apply(user_id, draft.model_dump())
        return self.status(user_id)

    def credentials(self, user_id: str) -> list[dict]:
        """List metadata and grants; token digests and plaintext are never returned."""
        with Session(self.engine) as db:
            records = db.exec(select(McpCredentialRecord).where(McpCredentialRecord.user_id == user_id)).all()
            return [dict(credential_id=r.credential_id, name=r.name, token_prefix=r.token_prefix,
                         grants=r.grants, revoked=r.revoked, created_at=r.created_at.isoformat()) for r in records]

    def create_credential(self, user_id: str, payload: dict) -> dict:
        """Create an explicit identity and return its random secret exactly once."""
        draft = McpCredentialCreate.model_validate(payload)
        catalog_names = {t["name"] for t in tool_catalog()}
        profile = self.settings.ensure_user_profile(user_id=user_id)
        if draft.library_id not in {l["library_id"] for l in profile["knowledge_libraries"]}:
            raise PermissionError("知识库无访问权限")
        if set(draft.tools) - catalog_names:
            raise ValueError("凭据包含未知工具")
        token = "mw_mcp_" + secrets.token_urlsafe(32)
        record = McpCredentialRecord(credential_id=f"mcpc_{uuid4().hex}", user_id=user_id,
            name=draft.name.strip(), token_hash=hashlib.sha256(token.encode()).hexdigest(),
            token_prefix=token[:14], grants={"library_id": draft.library_id, "tools": draft.tools})
        with Session(self.engine) as db:
            db.add(record)
            db.commit()
            db.refresh(record)
        return {"credential_id": record.credential_id, "token": token}

    def revoke(self, user_id: str, credential_id: str) -> None:
        """Revoke a user's identity; subsequent discovery and calls check the database again."""
        with Session(self.engine) as db:
            record = db.get(McpCredentialRecord, credential_id)
            if record is None or record.user_id != user_id:
                raise KeyError("凭据不存在")
            record.revoked = True
            db.add(record)
            db.commit()

    def rotate(self, user_id: str, credential_id: str) -> dict:
        """Atomically invalidate the old token and return the replacement once."""
        token = "mw_mcp_" + secrets.token_urlsafe(32)
        with Session(self.engine) as db:
            record = db.get(McpCredentialRecord, credential_id)
            if record is None or record.user_id != user_id or record.revoked:
                raise KeyError("有效凭据不存在")
            record.token_hash = hashlib.sha256(token.encode()).hexdigest()
            record.token_prefix = token[:14]
            db.add(record)
            db.commit()
        return {"credential_id": credential_id, "token": token}

    def authenticate(self, user_id: str, token: str) -> McpCredentialRecord:
        """Bind every request to a non-revoked token belonging to this listener's user."""
        digest = hashlib.sha256(token.encode()).hexdigest()
        with Session(self.engine) as db:
            record = db.exec(select(McpCredentialRecord).where(
                McpCredentialRecord.user_id == user_id, McpCredentialRecord.token_hash == digest,
                McpCredentialRecord.revoked == False,
            )).first()
        if record is None or not self.settings.get_mcp_settings(user_id=user_id, role="server")["config"]["enabled"]:
            raise PermissionError("MCP 凭据无效或服务已停用")
        return record

    def allowed_tools(self, record: McpCredentialRecord) -> list[dict]:
        """Intersect current server exposure with credential grants, never trust client hints."""
        exposed = set(self.settings.get_mcp_settings(user_id=record.user_id, role="server")["config"]["tools"])
        allowed = exposed & set(record.grants["tools"])
        return [t for t in tool_catalog() if t["name"] in allowed]

    def call(self, user_id: str, token: str, name: str, arguments: dict):
        """Reauthorize immediately before domain I/O and persist a redacted terminal result."""
        started = time.monotonic()
        record = self.authenticate(user_id, token)
        outcome, message = "failed", "业务调用失败"
        try:
            if name not in {t["name"] for t in self.allowed_tools(record)}:
                raise PermissionError("工具未获授权")
            with use_library(user_id, record.grants["library_id"]):
                result = execute_business(self.services, user_id, name, arguments)
            outcome, message = "success", ""
            return result
        except PermissionError:
            outcome, message = "denied", "工具或资源无访问权限"
            raise
        finally:
            with Session(self.engine) as db:
                db.add(McpAccessRecord(record_id=uuid4().hex, user_id=user_id,
                    credential_id=record.credential_id, tool_name=name, status=outcome,
                    duration_ms=int((time.monotonic() - started) * 1000), message=message))
                db.commit()

    def records(self, user_id: str) -> list[dict]:
        """Read a bounded recent history without document content or credentials."""
        with Session(self.engine) as db:
            rows = db.exec(select(McpAccessRecord).where(McpAccessRecord.user_id == user_id)
                           .order_by(McpAccessRecord.created_at.desc()).limit(self.config.mcp.access_record_limit)).all()
            return [{**r.model_dump(mode="json"), "created_at": r.created_at.replace(tzinfo=timezone.utc).isoformat()} for r in rows]
