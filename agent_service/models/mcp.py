"""Persistent MCP connections, credentials and redacted access records; registered by models/__init__.py."""

from datetime import datetime
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel
from agent_service.models.session import utc_now


class McpConnectionRecord(SQLModel, table=True):
    """One user-owned external connection; secret values are encrypted separately."""

    __tablename__ = "mcp_connections"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    connection_id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    name: str
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    encrypted_secrets: str = ""
    revision: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class McpCredentialRecord(SQLModel, table=True):
    """Server access identity: only the token digest is persisted, with explicit grants."""

    __tablename__ = "mcp_credentials"
    credential_id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    name: str
    token_hash: str = Field(index=True, unique=True)
    token_prefix: str
    grants: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    revoked: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class McpAccessRecord(SQLModel, table=True):
    """Durable call outcome without tool arguments, tokens or document contents."""

    __tablename__ = "mcp_access_records"
    record_id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    credential_id: str
    tool_name: str
    status: str
    duration_ms: int
    message: str = ""
    created_at: datetime = Field(default_factory=utc_now, index=True)
