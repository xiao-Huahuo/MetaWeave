"""Real SDK stdio server fixture for connection/discovery/call/cancellation tests; never used by production."""
import asyncio
import os
from mcp.server.fastmcp import FastMCP

server = FastMCP("MCP integration fixture")


@server.tool(annotations={"readOnlyHint": True})
def echo(text: str) -> dict:
    """Return a request value and server process identity to prove persistent connection reuse."""
    return {"text": text, "pid": os.getpid()}


@server.tool(annotations={"readOnlyHint": True})
async def wait(seconds: float) -> dict:
    """Controlled delay to verify timeout/cancellation without hanging a test."""
    await asyncio.sleep(seconds)
    return {"finished": True}


if __name__ == "__main__":
    server.run(transport="stdio")
