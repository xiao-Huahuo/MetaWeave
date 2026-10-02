"""
MCP 客户端模块。

功能说明:
本文件实现 `MCPClient` 异步协议客户端,由应用运行时持有连接。
支持本地 stdio 与远程 Streamable HTTP，统一处理以下能力:

1. 连接 stdio 型 MCP Server
2. 初始化 MCP Session
3. 拉取工具列表
4. 调用指定工具并规范化返回结果

使用说明:
典型用法如下:

```python
import asyncio

from agent_service.tools.mcp.client import MCPClient, MCPServerConfig


async def main() -> None:
    client = MCPClient(
        config=MCPServerConfig(
            command="python",
            args=["-m", "demo_mcp_server"],
        )
    )
    async with client:
        tools = await client.list_tools()
        result = await client.call_tool("example_tool", {"text": "hello"})
        print(tools)
        print(result.text)


asyncio.run(main())
```

注意:
- 本模块默认面向官方 Python MCP SDK 的 stdio client 形态。
- 如果运行环境尚未安装 `mcp` 依赖,在真正建立连接时会抛出清晰错误。
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass(slots=True)
class MCPServerConfig:
    """
    MCP Server 连接配置。

    command: 启动 MCP Server 的命令。
    args: 启动命令参数列表。
    env: 可选环境变量覆盖。
    encoding: 与 stdio 交互时使用的文本编码。
    """

    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    encoding: str = "utf-8"
    transport: str = "stdio"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout_seconds: int = 30


@dataclass(slots=True)
class MCPToolInfo:
    """
    MCP 工具元信息。

    name: 工具名称。
    description: 工具描述。
    input_schema: 工具输入 JSON Schema。
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = field(default_factory=dict)
    title: str = ""


@dataclass(slots=True)
class MCPCallResult:
    """
    MCP 工具调用结果。

    tool_name: 工具名称。
    text: 从 MCP content 中抽取出的纯文本结果。
    content: 原始 MCP content 列表,便于后续保留结构化富内容。
    structured_content: MCP 结构化结果,如果 server 有返回则保留。
    is_error: MCP 协议层标记的错误位。
    """

    tool_name: str
    text: str
    content: list[Any]
    structured_content: Any = None
    is_error: bool = False


class MCPClient:
    """
    最小可用 MCP 异步客户端。

    config: 外部 MCP Server 的连接配置。
    """

    def __init__(self, *, config: MCPServerConfig) -> None:
        """保存连接配置并初始化运行时状态。"""

        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._server_parameters: Any | None = None

    async def __aenter__(self) -> "MCPClient":
        """支持 async with 进入时自动建立连接。"""

        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """支持 async with 退出时自动关闭连接。"""

        await self.disconnect()

    async def connect(self) -> None:
        """
        建立到外部 MCP Server 的 stdio 连接并完成 session 初始化。

        如果已连接,本方法不会重复建立连接。
        """

        if self._session is not None:
            return
        sdk = self._import_mcp_sdk()
        server_parameters = sdk.StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
            encoding=self.config.encoding,
            cwd=self.config.cwd,
        )
        exit_stack = AsyncExitStack()
        try:
            if self.config.transport == "http":
                import httpx
                http_client = await exit_stack.enter_async_context(httpx.AsyncClient(
                    headers=self.config.headers, timeout=self.config.timeout_seconds,
                    trust_env=False,
                ))
                streams = await exit_stack.enter_async_context(
                    sdk.streamable_http_client(self.config.url, http_client=http_client)
                )
                read_stream, write_stream = streams[:2]
            else:
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sdk.stdio_client(server_parameters)
                )
            from datetime import timedelta
            session_kwargs = {"read_timeout_seconds": timedelta(seconds=self.config.timeout_seconds)} if getattr(sdk, "supports_timeout", False) else {}
            session = await exit_stack.enter_async_context(sdk.ClientSession(read_stream, write_stream, **session_kwargs))
            await session.initialize()
        except BaseException:
            await exit_stack.aclose()
            raise
        self._exit_stack = exit_stack
        self._session = session
        self._server_parameters = server_parameters

    async def disconnect(self) -> None:
        """关闭 MCP Session 与底层 stdio 连接。"""

        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None
        self._server_parameters = None

    async def list_tools(self) -> list[MCPToolInfo]:
        """
        拉取当前 MCP Server 暴露的工具列表。

        返回值统一转换为 `MCPToolInfo`。
        """

        session = self._require_session()
        response = await session.list_tools()
        tool_items = getattr(response, "tools", response)
        tools: list[MCPToolInfo] = []
        for tool in list(tool_items or []):
            input_schema = self._read_attribute(tool, "inputSchema", "input_schema") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}
            tools.append(
                MCPToolInfo(
                    name=str(self._read_attribute(tool, "name")),
                    description=str(self._read_attribute(tool, "description") or ""),
                    input_schema=input_schema,
                    annotations=self._annotation_dict(self._read_attribute(tool, "annotations")),
                    title=str(self._read_attribute(tool, "title") or ""),
                )
            )
        return tools

    @staticmethod
    def _annotation_dict(value: Any) -> dict[str, Any]:
        """Preserve read-only/destructive hints for Agent-side permission filtering."""
        return value.model_dump(exclude_none=True) if hasattr(value, "model_dump") else dict(value or {})

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPCallResult:
        """
        调用指定 MCP 工具并规范化结果。

        name: 工具名称。
        arguments: 工具参数。
        """

        session = self._require_session()
        response = await session.call_tool(name, arguments or {})
        content = list(self._read_attribute(response, "content") or [])
        structured_content = self._read_attribute(response, "structuredContent", "structured_content")
        is_error = bool(self._read_attribute(response, "isError", "is_error") or False)
        return MCPCallResult(
            tool_name=name,
            text=self._extract_text_content(content),
            content=content,
            structured_content=structured_content,
            is_error=is_error,
        )

    @property
    def is_connected(self) -> bool:
        """返回当前 MCP Client 是否已建立连接。"""

        return self._session is not None

    def _require_session(self) -> Any:
        """确保当前 MCP Session 已建立。"""

        if self._session is None:
            raise RuntimeError("MCPClient 尚未连接,请先调用 connect() 或使用 async with。")
        return self._session

    @staticmethod
    def _extract_text_content(content: list[Any]) -> str:
        """
        从 MCP 返回内容中提取纯文本。

        content: MCP content 列表,其中元素可能是对象也可能是字典。
        """

        text_parts: list[str] = []
        for item in content:
            item_type = MCPClient._read_attribute(item, "type")
            if item_type != "text":
                continue
            text_value = MCPClient._read_attribute(item, "text")
            if text_value:
                text_parts.append(str(text_value))
        return "\n".join(text_parts).strip()

    @staticmethod
    def _read_attribute(source: Any, *names: str) -> Any:
        """
        从对象或字典中按候选字段名读取值。

        source: 待读取对象。
        names: 允许尝试的字段名列表。
        """

        for name in names:
            if isinstance(source, dict) and name in source:
                return source[name]
            if hasattr(source, name):
                return getattr(source, name)
        return None

    @staticmethod
    def _import_mcp_sdk() -> Any:
        """
        延迟导入 MCP Python SDK。

        这样即使项目当前还没安装 `mcp`,只要不真正建立连接,模块本身仍可安全导入。
        """

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "当前环境未安装 MCP Python SDK。请先安装 `mcp` 包后再使用 MCPClient。"
            ) from exc
        return SimpleNamespace(
            ClientSession=ClientSession,
            StdioServerParameters=StdioServerParameters,
            stdio_client=stdio_client,
            streamable_http_client=streamable_http_client,
            supports_timeout=True,
        )
