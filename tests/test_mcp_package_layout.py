"""Check the PyInstaller dependency collection used by the release spec without rebuilding unrelated model bundles."""
from pathlib import Path
from importlib.metadata import version
from PyInstaller.utils.hooks import collect_submodules


def test_release_collects_both_mcp_transports_and_server():
    """The pinned SDK and frozen module inventory include every new runtime protocol entrypoint."""
    root = Path(__file__).resolve().parents[1]
    assert f"mcp=={version('mcp')}" in (root / "agent_service/requirements.txt").read_text(encoding="utf-8")
    spec = (root / "AgentService.spec").read_text(encoding="utf-8")
    assert "collect_submodules('mcp')" in spec
    modules = set(collect_submodules("mcp"))
    assert {"mcp.client.stdio", "mcp.client.streamable_http", "mcp.server.lowlevel.server", "mcp.server.streamable_http_manager"} <= modules
