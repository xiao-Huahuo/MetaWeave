"""Real stdio/HTTP integration, persisted config, authenticated grants and resource isolation regressions."""
import asyncio
import json
import socket
import sys
import threading
from pathlib import Path
import pytest
import httpx
from agent_service.schemas.mcp import McpConnectionCreate
from agent_service.tools.mcp.client import MCPClient, MCPServerConfig
from tests.mcp_test_support import make_mcp_services


def free_port() -> int:
    """Reserve an available local test address, closing the probe socket immediately."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_stdio_persistence_secrets_snapshot_and_shutdown(tmp_path):
    """Prove initialization, call reuse, immediate revocation, user isolation and resource cleanup."""
    services = make_mcp_services(tmp_path)
    client = services.mcp_client_service
    client.start()
    try:
        client.set_enabled("alice", True)
        draft = McpConnectionCreate(name="Fixture", command=sys.executable,
            args=[str(Path(__file__).with_name("mcp_stdio_fixture.py"))], env={"SECRET_TEST": "confidential"}).model_dump()
        probe = client.test("alice", draft)
        assert probe["state"] == "connected", probe
        row = client.save("alice", draft)
        assert row["state"] == "connected", row
        assert row["env"]["SECRET_TEST"] is None
        assert "confidential" not in json.dumps(client.list("alice"))
        assert "confidential" not in json.dumps(client.export("alice"))
        assert client.list("bob")["connections"] == []
        definitions = client.tool_snapshot("alice", "readonly")
        echo = next(d for d in definitions if d.name.endswith("__echo"))
        first = json.loads(echo.function(text="中文"))
        second = json.loads(echo.function(text="again"))
        assert first["pid"] == second["pid"] and first["text"] == "中文"
        with pytest.raises(KeyError):
            client.delete("bob", row["connection_id"])
        changed = {**draft, "env": {"SECRET_TEST": None}, "disabled_tools": ["echo"]}
        updated = client.save("alice", changed, row["connection_id"], row["revision"])
        with pytest.raises(PermissionError):
            echo.function(text="revoked")
        assert updated["revision"] == row["revision"] + 1
        with pytest.raises(ValueError):
            client.save("alice", changed, row["connection_id"], row["revision"])
        client.set_enabled("alice", False)
        assert client.list("alice")["connections"][0]["state"] == "stopped"
        client.delete("alice", row["connection_id"])
        assert not client.list("alice")["connections"]
    finally:
        client.shutdown()
        assert client.runtime.thread is None
        services.database_engine.dispose()


def test_real_http_server_grants_rotation_and_library_scope(tmp_path):
    """Use real SDK traffic to verify disclosure, calls, permission denial and revoked credentials."""
    async def run():
        services = make_mcp_services(tmp_path)
        server = services.mcp_server_service
        settings = services.settings_service
        settings.ensure_user_profile(user_id="alice")
        first = settings.get_active_knowledge_library(user_id="alice")
        services.knowledge_library_service.write_file(user_id="alice", path="one.txt", content="first library")
        settings.update_knowledge_dir(user_id="alice", knowledge_dir=str(tmp_path / "second"), name="Second")
        active_before = settings.get_active_knowledge_library(user_id="alice")["library_id"]
        port = free_port()
        config = dict(enabled=True, host="127.0.0.1", port=port, tools=["list_knowledge_files", "read_file", "write_knowledge_file"])
        await server.save("alice", config)
        assert server.status("alice")["state"] == "running"
        issued = server.create_credential("alice", {"name": "Reader", "library_id": first["library_id"], "tools": ["list_knowledge_files", "read_file"]})
        token = issued["token"]
        url = server.status("alice")["url"]
        try:
            assert "first library" in server.call("alice", token, "read_file", {"path": "one.txt"})["content"]
            async with httpx.AsyncClient(trust_env=False) as http:
                assert (await http.post(url, json={})).status_code == 401
            async with MCPClient(config=MCPServerConfig(transport="http", url=url, headers={"Authorization": f"Bearer {token}"})) as client:
                assert {t.name for t in await client.list_tools()} == {"list_knowledge_files", "read_file"}
                read = await client.call_tool("read_file", {"path": "one.txt"})
                assert not read.is_error and "first library" in read.text
                denied = await client.call_tool("write_knowledge_file", {"path": "one.txt", "content": "bad"})
                assert denied.is_error
                traversal = await client.call_tool("read_file", {"path": "../test.db"})
                assert traversal.is_error
                forged = await client.call_tool("read_file", {"path": "one.txt", "user_id": "bob"})
                assert forged.is_error
            assert settings.get_active_knowledge_library(user_id="alice")["library_id"] == active_before
            assert "token_hash" not in json.dumps(server.credentials("alice"))
            rotated = server.rotate("alice", issued["credential_id"])
            with pytest.raises(PermissionError):
                server.authenticate("alice", token)
            server.authenticate("alice", rotated["token"])
            server.revoke("alice", issued["credential_id"])
            with pytest.raises(PermissionError):
                server.authenticate("alice", rotated["token"])
            assert any(row["status"] == "denied" for row in server.records("alice"))
            await server.save("alice", {**config, "enabled": False})
            assert server.status("alice")["state"] == "stopped"
        finally:
            await server.runtime.shutdown()
            services.database_engine.dispose()
    asyncio.run(run())


def test_connection_actor_concurrency_cancel_timeout_and_failure(tmp_path):
    """One failed or cancelled actor request must not block other connections or later requests."""
    services = make_mcp_services(tmp_path)
    client = services.mcp_client_service
    client.start()
    draft = McpConnectionCreate(name="Actor", command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_stdio_fixture.py"))], timeout_seconds=2).model_dump()
    try:
        async def verify():
            key = ("a", "first")
            # Concurrent duplicate initialization shares the same owner.
            await asyncio.gather(client.runtime.connect(key, draft), client.runtime.connect(key, draft))
            await client.runtime.connect(("a", "second"), draft)
            waiting = asyncio.create_task(client.runtime.call(key, "wait", {"seconds": 5}))
            await asyncio.sleep(0.1)
            other = await client.runtime.call(("a", "second"), "echo", {"text": "independent"})
            assert "independent" in other.text
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert "after cancellation" in (await client.runtime.call(key, "echo", {"text": "after cancellation"})).text
            with pytest.raises((TimeoutError, RuntimeError)):
                await client.runtime.call(key, "wait", {"seconds": 5})
            assert "after timeout" in (await client.runtime.call(key, "echo", {"text": "after timeout"})).text
            broken = await client.runtime.connect(("a", "broken"), {**draft, "command": "missing-mcp-executable"})
            assert broken["state"] == "failed"
            assert "healthy" in (await client.runtime.call(key, "echo", {"text": "healthy"})).text
            await client.runtime.stop(key)
            await client.runtime.stop(key)
        client.runtime.submit(verify(), 20)
    finally:
        client.shutdown()
        services.database_engine.dispose()


def test_concurrent_server_credentials_keep_library_context(tmp_path):
    """Concurrent real HTTP calls retain separate knowledge-library grants without global selection changes."""
    async def verify():
        services = make_mcp_services(tmp_path)
        settings, server = services.settings_service, services.mcp_server_service
        settings.ensure_user_profile(user_id="owner")
        first = settings.get_active_knowledge_library(user_id="owner")
        services.knowledge_library_service.write_file(user_id="owner", path="same.txt", content="one")
        settings.update_knowledge_dir(user_id="owner", knowledge_dir=str(tmp_path / "other"), name="Other")
        second = settings.get_active_knowledge_library(user_id="owner")
        services.knowledge_library_service.write_file(user_id="owner", path="same.txt", content="two")
        await server.save("owner", dict(enabled=True, host="127.0.0.1", port=free_port(), tools=["read_file"]))
        credentials = [server.create_credential("owner", {"name": str(index), "library_id": lib["library_id"], "tools": ["read_file"]}) for index, lib in enumerate((first, second))]
        async def read(credential):
            async with MCPClient(config=MCPServerConfig(transport="http", url=server.status("owner")["url"], headers={"Authorization": "Bearer " + credential["token"]})) as client:
                return (await client.call_tool("read_file", {"path": "same.txt"})).structured_content["content"]
        try:
            assert await asyncio.gather(*(read(c) for c in credentials)) == ["one", "two"]
            assert settings.get_active_knowledge_library(user_id="owner")["library_id"] == second["library_id"]
        finally:
            await server.runtime.shutdown()
            services.database_engine.dispose()
    asyncio.run(verify())


def test_process_connections_are_inherited_without_materializing_defaults(tmp_path):
    """Keep existing service-level MCP configuration, independent per-user overrides and deletion tombstones."""
    from sqlmodel import Session, select
    from agent_service.models.mcp import McpConnectionRecord
    services = make_mcp_services(tmp_path)
    services.config.mcp.servers = [{"server_id": "configured", "command": sys.executable, "enabled": True}]
    client = services.mcp_client_service
    client.start()
    try:
        row = client.list("alice")["connections"][0]
        assert row["inherited"] and row["revision"] == 0
        with Session(services.database_engine) as db:
            assert not db.exec(select(McpConnectionRecord)).all()
        draft = McpConnectionCreate(name="configured", command=sys.executable).model_dump()
        saved = client.save("alice", draft, row["connection_id"], 0)
        assert not saved["inherited"]
        assert client.list("bob")["connections"][0]["inherited"]
        client.delete("alice", row["connection_id"])
        assert not client.list("alice")["connections"]
        assert client.list("bob")["connections"]
        assert services.settings_service.save_mcp_settings(user_id="alice", role="server", payload={
            "enabled": False, "host": services.config.mcp.server_host, "port": services.config.mcp.server_port, "tools": [],
        })["override"] == {}
    finally:
        client.shutdown()
        services.database_engine.dispose()
