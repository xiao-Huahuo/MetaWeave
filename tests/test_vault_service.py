"""
密码库服务测试。

功能说明:
验证统一登录解密会话、敏感字段加密存储、回收站、导入导出和账号隔离。

使用说明:
在项目根目录执行 `python -m pytest tests/test_vault_service.py`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select

from tests.db_test_utils import create_test_engine as create_engine

from agent_service.core.agent_config import AgentConfig
from agent_service.models.vault import VaultAsset, VaultItem
from agent_service.services.auth.service import AuthService
from agent_service.services.vault.service import VaultService


def make_service(tmp_path: Path) -> VaultService:
    """创建使用内存数据库和临时运行目录的密码库服务。"""

    config = AgentConfig.load_config(
        {
            "limits": {"vault_password_kdf_iterations": 100, "vault_encryption_kdf_iterations": 100},
            "storage": {
                "base_data_dir": str(tmp_path / "runtime"),
                "assets_dir": str(tmp_path / "runtime" / "assets"),
            }
        },
        load_env=False,
        load_dotenv=False,
        ensure_directories=True,
        ensure_models=False,
    )
    return VaultService(config=config, engine=create_engine("sqlite:///:memory:"))


def unlock_session(service: VaultService, user_id: str = "u1"):
    """注册统一账号并返回同密码派生的解密会话。"""

    auth = AuthService(config=service.config, engine=service.engine)
    token = auth.register(username=user_id, password="correct horse")["token"]
    return auth.verify_session(token)


def test_vault_encrypts_sensitive_payload_and_lists_after_unlock(tmp_path: Path) -> None:
    """敏感字段加密落库,解锁后可正常列表和搜索。"""

    service = make_service(tmp_path)
    session = unlock_session(service)
    created = service.create_item(
        session=session,
        item_type="login",
        fields={"name": "GitHub", "username": "octo", "password": "secret", "uri": "https://github.com"},
        tags=["dev"],
        asset_ids=[],
    )["item"]

    with Session(service.engine) as db:
        raw = db.exec(select(VaultItem)).first()
        assert raw is not None
        assert "secret" not in raw.encrypted_payload
        assert "GitHub" not in raw.encrypted_payload

    listed = service.list_items(session=session, query="secret", tag="dev")["items"]
    assert listed[0]["item_id"] == created["item_id"]
    assert "password" not in listed[0]["fields"]
    assert "password" not in listed[0]["safe_fields"]
    assert listed[0]["field_keys"] == ["name", "username", "password", "uri"]
    assert service.get_item(session=session, item_id=created["item_id"])["item"]["fields"]["password"] == "secret"


def test_vault_authenticated_account_isolation(tmp_path: Path) -> None:
    """统一账号的解密会话不能跨 user_id 读取。"""

    service = make_service(tmp_path)
    session_u1 = unlock_session(service, "u1")
    session_u2 = unlock_session(service, "u2")
    item = service.create_item(
        session=session_u1,
        item_type="secure_note",
        fields={"name": "note", "note": "hidden"},
        tags=[],
        asset_ids=[],
    )["item"]

    with pytest.raises(ValueError):
        service.get_item(session=session_u2, item_id=item["item_id"])


def test_vault_trash_restore_purge_and_export(tmp_path: Path) -> None:
    """回收站恢复、永久删除和明文导出语义完整。"""

    service = make_service(tmp_path)
    session = unlock_session(service)
    item = service.create_item(
        session=session,
        item_type="card",
        fields={"name": "Visa", "number": "4111111111111111", "security_code": "123"},
        tags=["pay"],
        asset_ids=[],
    )["item"]

    service.move_to_trash(session=session, item_ids=[item["item_id"]])
    assert service.list_items(session=session, trash=False)["items"] == []
    assert service.list_items(session=session, trash=True)["items"][0]["name"] == "Visa"

    service.restore_items(session=session, item_ids=[item["item_id"]])
    exported = service.export_items(session=session, item_ids=[item["item_id"]])
    assert exported["items"][0]["fields"]["security_code"] == "123"

    service.purge_items(session=session, item_ids=[item["item_id"]])
    assert service.list_items(session=session)["items"] == []


def test_vault_import_converts_mismatched_item_to_secure_note(tmp_path: Path) -> None:
    """字段不匹配的可识别导入项会转成安全笔记。"""

    service = make_service(tmp_path)
    session = unlock_session(service)
    result = service.import_items(session=session, raw_items=[{"item_type": "login", "title": "Broken"}])
    items = service.list_items(session=session)["items"]

    assert result["imported"] == 1
    assert result["converted_to_secure_note"] == 1
    assert items[0]["item_type"] == "secure_note"


def test_vault_no_longer_exposes_independent_credentials_or_plaintext_debug(tmp_path: Path) -> None:
    """密码库只消费统一登录会话，旧密码设置/解锁/调试入口已删除。"""

    service = make_service(tmp_path)
    for method in ("setup", "unlock", "reset_master_password", "debug_master_password", "verify_token", "lock"):
        assert not hasattr(service, method)


@pytest.mark.parametrize("operation", ["create", "update"])
def test_vault_mutation_rolls_back_item_and_tags_when_attachment_fails(tmp_path: Path, monkeypatch, operation: str) -> None:
    """A tag/asset failure must not commit ciphertext outside the password writer guard."""
    service = make_service(tmp_path)
    session = unlock_session(service)
    original = service.create_item(session=session, item_type="secure_note",
                                   fields={"name": "original", "note": "hidden"}, tags=["old"], asset_ids=[])["item"]

    def fail_attachment(**kwargs):
        """Inject the failure after tag changes but before the transaction commits."""
        raise ValueError("attachment failed")

    monkeypatch.setattr(service, "_attach_assets", fail_attachment)
    with pytest.raises(ValueError, match="attachment failed"):
        if operation == "create":
            service.create_item(session=session, item_type="secure_note",
                                fields={"name": "new", "note": "secret"}, tags=["new"], asset_ids=[])
        else:
            service.update_item(session=session, item_id=original["item_id"],
                                payload={"fields": {"name": "changed", "note": "changed"}, "tags": ["new"], "asset_ids": []})
    items = service.list_items(session=session)["items"]
    assert len(items) == 1
    assert items[0]["name"] == "original" and items[0]["tags"] == ["old"]


def test_stale_vault_session_rejects_asset_before_writing_files(tmp_path: Path) -> None:
    """A password-rotated key must not leave an unowned uploaded file on disk."""
    service = make_service(tmp_path)
    stale = unlock_session(service)
    auth = AuthService(config=service.config, engine=service.engine)
    token = auth.login(username="u1", password="correct horse")["token"]
    auth.change_password(token, "correct horse", "new correct horse")
    with pytest.raises(ValueError, match="expired"):
        service.upload_asset(session=stale, filename="photo.png", content=b"image", mime_type="image/png")
    assert not any(path.is_file() for path in service.assets_root.rglob("*"))


def create_item_with_asset(service, session):
    """Create real encrypted metadata and a tracked image file for purge failures."""
    asset = service.upload_asset(session=session, filename="photo.png", content=b"private image", mime_type="image/png")["asset"]
    path = Path(service.get_asset(session=session, asset_id=asset["asset_id"]).storage_path)
    item = service.create_item(session=session, item_type="secure_note",
        fields={"name": "private", "note": "keep intact", "asset_ids": [asset["asset_id"]]}, tags=[], asset_ids=[asset["asset_id"]])["item"]
    return item, asset, path


def test_purge_validates_every_owner_before_removing_any_file(tmp_path: Path) -> None:
    """A mixed owner batch fails as one unit and leaves earlier own images intact."""
    service = make_service(tmp_path)
    own = unlock_session(service)
    other = unlock_session(service, "other")
    item, _, path = create_item_with_asset(service, own)
    foreign = service.create_item(session=other, item_type="secure_note", fields={"name": "foreign", "note": "hidden"}, tags=[], asset_ids=[])["item"]
    with pytest.raises(ValueError, match="not found"):
        service.purge_items(session=own, item_ids=[item["item_id"], foreign["item_id"]])
    assert path.exists()
    assert service.get_item(session=own, item_id=item["item_id"])["item"]["fields"]["note"] == "keep intact"


def test_purge_sql_commit_failure_never_deletes_image_files(tmp_path: Path, monkeypatch) -> None:
    """File deletion starts only after the entire metadata transaction succeeds."""
    service = make_service(tmp_path)
    session = unlock_session(service)
    item, asset, path = create_item_with_asset(service, session)

    def fail_commit(database):
        """Inject a real transaction failure after service mutation preparation."""
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database commit failed"):
        service.purge_items(session=session, item_ids=[item["item_id"]])
    assert path.exists()
    with Session(service.engine) as db:
        assert db.get(VaultItem, item["item_id"]) is not None
        assert db.get(VaultAsset, asset["asset_id"]) is not None


def test_purge_locked_file_remains_tracked_and_startup_retries(tmp_path: Path, monkeypatch) -> None:
    """Pending cleanup is durable and never makes a deleted item's asset accessible."""
    service = make_service(tmp_path)
    session = unlock_session(service)
    item, asset, path = create_item_with_asset(service, session)

    def locked_file(storage_path):
        """Model the actual Windows open-file deletion failure."""
        raise PermissionError("file is in use")

    monkeypatch.setattr(service, "_delete_asset_file", locked_file)
    with pytest.raises(ValueError, match="cleanup"):
        service.purge_items(session=session, item_ids=[item["item_id"]])
    assert path.exists()
    with Session(service.engine) as db:
        assert db.get(VaultItem, item["item_id"]) is None
        assert db.get(VaultAsset, asset["asset_id"]) is not None
    with pytest.raises(ValueError, match="not found"):
        service.get_asset(session=session, asset_id=asset["asset_id"])
    VaultService(config=service.config, engine=service.engine)
    assert not path.exists()
    with Session(service.engine) as db:
        assert db.get(VaultAsset, asset["asset_id"]) is None
