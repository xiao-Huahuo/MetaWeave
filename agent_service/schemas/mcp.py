"""Validated MCP management DTOs, shared by REST/gRPC and runtime configuration."""

from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator


class McpConnectionCreate(BaseModel):
    """External server configuration; null secret values preserve stored credentials."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    transport: Literal["stdio", "http"] = "stdio"
    enabled: bool = True
    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: str = ""
    url: str = ""
    env: dict[str, str | None] = Field(default_factory=dict)
    headers: dict[str, str | None] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    disabled_tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_transport(self) -> "McpConnectionCreate":
        """Reject incomplete transports, URL credentials and invalid header/environment names."""
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("服务名称不能为空")
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("本地进程需要程序路径或名称")
        if self.transport == "http":
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("需要不含用户名或密码的 HTTP/HTTPS 地址")
        for key, value in {**self.env, **self.headers}.items():
            if not key.strip() or any(c in key for c in "\r\n=") or (value and any(c in value for c in "\r\n")):
                raise ValueError("环境变量和请求头名称及值不能包含换行")
        return self


class McpConnectionUpdate(McpConnectionCreate):
    """Full editable replacement guarded by optimistic revision."""
    revision: int = Field(ge=0)


class McpConnectionOut(McpConnectionCreate):
    """Secret-free connection snapshot with live, independently reported runtime state."""
    connection_id: str
    revision: int
    inherited: bool = False
    state: str = "stopped"
    error: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list)


class McpServerSettings(BaseModel):
    """Per-user listener and exposed tool selection; credentials provide narrower grants."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8766, ge=1024, le=65535)
    tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_host(self) -> "McpServerSettings":
        """Accept listener IP addresses, never an arbitrary URL or path."""
        from ipaddress import ip_address
        ip_address(self.host)
        return self


class McpCredentialCreate(BaseModel):
    """Explicit tools and owned library grant for an external identity."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    tools: list[str] = Field(min_length=1)
    library_id: str = Field(min_length=1)


class McpClientSettings(BaseModel):
    """Nullable user override; null restores the service default."""
    enabled: bool | None = None
