"""Regress the production middleware's private-file and streaming-session boundaries.

Services use an isolated migrated SQLite database. No listener or model is started.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from tests.test_auth_rest import fixture, register


def request_for(client, token: str, path: str) -> Request:
    """Create a real ASGI request with the fixture's authenticated application."""
    return Request({"type": "http", "method": "GET", "path": path,
                    "raw_path": path.encode(), "query_string": b"", "scheme": "http",
                    "server": ("127.0.0.1", 8002), "client": ("127.0.0.1", 12345),
                    "headers": [(b"authorization", ("Bearer " + token).encode())],
                    "app": client.app})


def test_private_file_paths_are_canonical_account_paths(tmp_path: Path) -> None:
    """Reject foreign and escaped paths before static serving and disable active content."""
    from main import _protect_business_files
    client, auth, _, engine = fixture(tmp_path)
    try:
        first = register(client, "owner")
        other = register(client, "other")
        async def check():
            async def serve(request):
                return Response("owned payload")
            for prefix in ("/knowledge/assets/", "/library/assets/", "/downloads/", "/visualizations/"):
                own = await _protect_business_files(request_for(client, first["token"], prefix + first["user_id"] + "/asset.txt"), serve)
                assert own.status_code == 200
                assert own.headers["Cache-Control"] == "no-store"
                assert own.headers["X-Content-Type-Options"] == "nosniff"
                assert own.headers["Content-Security-Policy"] == ("sandbox allow-scripts" if prefix == "/visualizations/" else "sandbox")
                for path in (prefix + other["user_id"] + "/asset.txt",
                             prefix + first["user_id"] + "/../" + other["user_id"] + "/asset.txt",
                             prefix + first["user_id"] + "/%2e%2e%2f" + other["user_id"] + "/asset.txt"):
                    denied = await _protect_business_files(request_for(client, first["token"], path), serve)
                    assert denied.status_code == 404
                unauthenticated = await _protect_business_files(request_for(client, "invalid", prefix + first["user_id"] + "/asset.txt"), serve)
                assert unauthenticated.status_code == 401
        asyncio.run(check())
    finally:
        auth.close()
        engine.dispose()


def test_revocation_stops_and_closes_inflight_private_stream(tmp_path: Path) -> None:
    """A valid first chunk cannot authorize private chunks emitted after logout."""
    from main import _protect_authenticated_streams
    client, auth, _, engine = fixture(tmp_path)
    try:
        state = register(client, "stream-owner")
        closed = []
        async def check():
            async def chunks():
                try:
                    yield b"data: before-logout\n\n"
                    auth.logout(state["token"])
                    yield b"data: private-after-logout\n\n"
                finally:
                    closed.append(True)
            async def serve(request):
                return StreamingResponse(chunks(), media_type="text/event-stream")
            response = await _protect_authenticated_streams(request_for(client, state["token"], "/agent/stream-run"), serve)
            emitted = [chunk async for chunk in response.body_iterator]
            assert emitted == [b"data: before-logout\n\n"]
            assert closed == [True]
        asyncio.run(check())
    finally:
        auth.close()
        engine.dispose()
