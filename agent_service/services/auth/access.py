"""Verify ownership of user-addressed resources before HTTP/gRPC handlers execute.

Identifiers are checked against formal metadata tables. Vault mutations retain
additional key-version checks in their own service transactions.
"""
from __future__ import annotations
from typing import Any
from sqlalchemy import select
from sqlmodel import SQLModel, Session
from agent_service.services.auth.service import AuthError

RESOURCES = {
    "session_id": ("agent_sessions", "session_id"),
    "snapshot_id": ("agent_change_snapshots", "snapshot_id"),
    "feedback_id": ("feedback", "feedback_id"),
    "form_id": ("smart_forms", "form_id"),
    "scan_id": ("scanner_records", "scan_id"),
    "job_id": ("knowledge_ingestion_jobs", "job_id"),
    "prompt_id": ("user_system_prompts", "prompt_id"),
    "memory_id": ("longterm_memory_specs", "memory_id"),
    "automation_id": ("automation_tasks", "automation_id"),
    "task_id": ("agent_queue_tasks", "task_id"),
    "connection_id": ("mcp_connections", "connection_id"),
    "credential_id": ("mcp_credentials", "credential_id"),
    "attachment_id": ("session_attachments", "attachment_id"),
    "uri": ("session_attachments", "uri"),
}

def _owner(db: Session, table_name: str, column: str, value: str) -> str | None:
    """Read only ownership columns, never sensitive payloads."""
    table = SQLModel.metadata.tables.get(table_name)
    if table is None or column not in table.c or "user_id" not in table.c:
        return None
    return db.execute(select(table.c.user_id).where(table.c[column] == value)).scalar_one_or_none()

def verify_claims(engine: Any, *, user_id: str, payload: dict[str, Any], path: str, required_resources: bool = False) -> None:
    """Reject foreign identities and resources; new IDs in creation payloads may be absent."""
    supplied = payload.get("user_id")
    if supplied is not None and str(supplied) != user_id:
        raise AuthError("Account identity mismatch", 403)
    resources = dict(RESOURCES)
    if path.startswith("/vault"):
        resources.update(item_id=("vault_items", "item_id"), asset_id=("vault_assets", "asset_id"))
    elif path.startswith("/library"):
        resources["item_id"] = ("library_items", "item_id")
    if "/settings/llm/" in path:
        resources["config_id"] = ("user_llm_config_presets", "config_id")
    elif "/settings/vlm/" in path:
        resources["config_id"] = ("user_vlm_config_presets", "config_id")
    with Session(engine) as db:
        for name, (table_name, column) in resources.items():
            value = payload.get(name)
            if not value:
                continue
            owner = _owner(db, table_name, column, str(value))
            if owner is not None and owner != user_id:
                raise AuthError("Resource not found", 404)
            if required_resources and owner is None:
                raise AuthError("Resource not found", 404)
        library = payload.get("library_id")
        if library:
            owner = _owner(db, "user_knowledge_libraries", "library_id", str(library))
            if owner != user_id:
                raise AuthError("Library not found", 404)
