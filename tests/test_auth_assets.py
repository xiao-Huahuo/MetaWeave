"""Authenticated image/raw-file regressions for script isolation and account ownership.

Use real production REST routes and temporary metadata. SVG remains downloadable
and usable as an image; its document response must never execute app-origin code.
"""

from pathlib import Path

from sqlmodel import Session

from agent_service.models.attachment import SessionAttachmentRecord
from agent_service.services.session_attachment.service import SessionAttachmentService
from tests.test_auth_rest import fixture, register


SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>window.assetScriptRan=true</script><rect width="4" height="4"/></svg>'


def assert_sandboxed(response) -> None:
    """Require both CSP script denial and an opaque document origin plus no sniffing."""
    assert response.status_code == 200, response.text
    directives = {item.strip() for item in response.headers.get("content-security-policy", "").split(";")}
    assert "sandbox" in directives
    assert "script-src 'none'" in directives
    assert not any("allow-same-origin" in item or "allow-scripts" in item for item in directives)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_vault_svg_is_preserved_but_response_has_no_script_origin(tmp_path: Path) -> None:
    """The shared logged-in vault cannot promote SVG documents to app-origin scripts."""
    client, auth, _, engine = fixture(tmp_path)
    try:
        first = register(client, "first")
        uploaded = client.post("/vault/assets", files={"file": ("drawing.svg", SVG, "image/svg+xml")})
        assert uploaded.status_code == 200, uploaded.text
        asset_id = uploaded.json()["asset"]["asset_id"]
        rendered = client.get("/vault/assets/" + asset_id)
        assert_sandboxed(rendered)
        assert rendered.content == SVG
        assert rendered.headers["content-type"].startswith("image/svg+xml")
        second = register(client, "second")
        assert second["user_id"] != first["user_id"]
        assert client.get("/vault/assets/" + asset_id).status_code == 404
    finally:
        client.close()
        auth.close()
        engine.dispose()


def test_raw_attachment_svg_is_inline_but_sandboxed_and_owned(tmp_path: Path) -> None:
    """An explicitly inline raw attachment must not inherit the backend document origin."""
    client, auth, settings, engine = fixture(tmp_path)
    try:
        state = register(client, "owner")
        created = client.post("/sessions", json={"user_id": state["user_id"], "session_name": "attachment"})
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]
        app = client.app
        app.state.services.attachment_service = SessionAttachmentService(config=auth.config, settings_service=settings,
                                                                         engine=engine, create_tables=False)
        root = auth.config.storage.base_data_dir / "uploads" / state["user_id"]
        root.mkdir(parents=True, exist_ok=True)
        path = root / "drawing.svg"
        path.write_bytes(SVG)
        uri = f"session-upload://{session_id}/drawing.svg"
        with Session(engine) as db:
            db.add(SessionAttachmentRecord(attachment_id="owned-svg", user_id=state["user_id"], session_id=session_id,
                library_id="", library_name="", filename="drawing.svg", stored_name="drawing.svg",
                path=str(path), uri=uri, mime_type="image/svg+xml", size=len(SVG)))
            db.commit()
        response = client.get("/agent/attachments/raw", params={"uri": uri})
        assert_sandboxed(response)
        assert response.content == SVG and response.headers["content-disposition"].startswith("inline")
        register(client, "other")
        assert client.get("/agent/attachments/raw", params={"uri": uri}).status_code == 404
    finally:
        client.close()
        auth.close()
        engine.dispose()
