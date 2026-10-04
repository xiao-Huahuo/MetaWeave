"""Serial low-memory regressions for identity, fixed login grants and vault rotation.

Run with python -m pytest tests/test_auth_service.py. Temporary databases use low
KDF iteration overrides for bounded test runtime; production persists its full
configured derivation counts for each account.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, current_thread
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.account import Account, AuthAccessSession, AuthDevice
from agent_service.models.user_settings import UserSettingsRecord
from agent_service.models.vault import VaultItem
from agent_service.services.auth.service import AuthError, AuthService
from agent_service.services.settings.service import SettingsService
from agent_service.services.vault.service import VaultService
from tests.db_test_utils import create_test_engine


def make_services(tmp_path: Path) -> tuple[AuthService, VaultService]:
    """Create one shared file database without model loading or live listeners."""
    config = AgentConfig.load_config({
        "storage": {"base_data_dir": str(tmp_path / "runtime"), "assets_dir": str(tmp_path / "runtime" / "assets"),
                    "knowledge_dir": str(tmp_path / "knowledge")},
        "limits": {"vault_password_kdf_iterations": 100, "vault_encryption_kdf_iterations": 100},
    }, load_env=False, load_dotenv=False, ensure_models=False)
    engine = create_test_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    return AuthService(config=config, engine=engine), VaultService(config=config, engine=engine)


def restore_kwargs(result: dict) -> dict:
    """Select private restore material while excluding the public expiry field."""
    return {key: result["remember"][key] for key in ("device_id", "credential", "vault_key", "password_version")}


def test_normalized_identity_is_eight_digits_and_settings_owns_profile(tmp_path: Path) -> None:
    """Persist normalized name+time encoding, one password and no plaintext key."""
    auth, _ = make_services(tmp_path)
    result = auth.register(username="  Ａlice  ", password="correct horse", device_id="desktop-1")
    assert result["username"] == "alice"
    assert len(result["user_id"]) == 8 and result["user_id"].isdigit()
    assert result["onboarding_step"] == 2 and not result["onboarding_completed"]
    with Session(auth.engine) as db:
        account = db.get(Account, result["user_id"])
        assert account is not None
        assert account.user_id == auth.encode_user_id(account.username, account.created_at)
        assert db.get(UserSettingsRecord, account.user_id) is None
        stored = str(account.model_dump())
        assert "correct horse" not in stored and result["remember"]["vault_key"] not in stored
        device = db.get(AuthDevice, "desktop-1")
        assert result["remember"]["credential"] not in str(device.model_dump())
        access = db.exec(select(AuthAccessSession)).one()
        assert access.token_hash != result["token"]
    settings = SettingsService(config=auth.config, memory_service=SimpleNamespace(engine=auth.engine))
    assert settings.ensure_user_profile(user_id=result["user_id"])["user_id"] == result["user_id"]
    with Session(auth.engine) as db:
        assert db.get(UserSettingsRecord, result["user_id"]) is not None
    assert auth.login(username="ALICE", password="correct horse")["user_id"] == result["user_id"]
    with pytest.raises(AuthError) as duplicate:
        auth.register(username="alice", password="correct horse")
    assert duplicate.value.status_code == 409


def test_unknown_login_has_same_error_and_failed_attempts_are_throttled(tmp_path: Path) -> None:
    """Reject unknown/wrong passwords uniformly and reserve bounded attempts."""
    auth, _ = make_services(tmp_path)
    auth.register(username="alice", password="correct horse")
    errors = []
    for username in ("alice", "unknown"):
        with pytest.raises(AuthError) as error:
            auth.login(username=username, password="incorrect horse")
        errors.append((str(error.value), error.value.status_code))
    assert errors[0] == errors[1] == ("invalid username or password", 401)
    for _ in range(auth.config.limits.auth_failure_limit - 1):
        with pytest.raises(AuthError) as error:
            auth.login(username="unknown", password="incorrect horse")
        assert error.value.status_code == 401
    with pytest.raises(AuthError) as error:
        auth.login(username="unknown", password="incorrect horse")
    assert error.value.status_code == 429


def test_device_restores_after_restart_without_renewing_thirty_days(tmp_path: Path, monkeypatch) -> None:
    """Restart loses access keys but OS-protected remembered material restores them."""
    auth, _ = make_services(tmp_path)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    result = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    expiry = datetime.fromisoformat(result["remember"]["expires_at"])
    assert expiry == now + timedelta(days=30)
    blob = base64.b64encode(b"opaque-os-ciphertext").decode("ascii")
    auth.write_remembered_blob(result["token"], "desktop-1", blob)
    auth.close()
    restarted = AuthService(config=auth.config, engine=auth.engine)
    now += timedelta(days=29)
    monkeypatch.setattr(restarted, "_now", lambda: now)
    assert restarted.read_remembered_blob("desktop-1")["blob"] == blob
    with pytest.raises(AuthError):
        restarted.verify_session(result["token"])
    restored = restarted.restore(**restore_kwargs(result))
    assert "remember" not in restored
    assert restarted.verify_session(restored["token"]).user_id == result["user_id"]
    assert datetime.fromisoformat(restarted.read_remembered_blob("desktop-1")["expires_at"]) == expiry
    now += timedelta(days=1)
    with pytest.raises(AuthError):
        restarted.restore(**restore_kwargs(result))
    expired = restarted.read_remembered_blob("desktop-1")
    assert expired["expired"] and expired["username"] == "alice" and expired["blob"] == ""
    manual = restarted.login(username="alice", password="correct horse", device_id="desktop-1")
    assert datetime.fromisoformat(manual["remember"]["expires_at"]) == now + timedelta(days=30)
    with pytest.raises(AuthError):
        restarted.restore(**restore_kwargs(result))


def test_device_restore_rejects_wrong_key_version_and_credential(tmp_path: Path) -> None:
    """All remembered secret parts bind to one account, device and password version."""
    auth, _ = make_services(tmp_path)
    first = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    second = auth.register(username="bob", password="correct horse", device_id="desktop-2")
    for field, value in (("credential", second["remember"]["credential"]),
                         ("vault_key", second["remember"]["vault_key"]),
                         ("password_version", 2)):
        invalid = {**restore_kwargs(first), field: value}
        with pytest.raises(AuthError):
            auth.restore(**invalid)


def test_logout_and_expired_session_device_delete_revoke_every_grant(tmp_path: Path, monkeypatch) -> None:
    """Explicit exit revokes the device; normal close only clears RAM keys."""
    auth, _ = make_services(tmp_path)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    registered = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    restored = auth.restore(**restore_kwargs(registered))
    auth.logout(restored["token"])
    for token in (registered["token"], restored["token"]):
        with pytest.raises(AuthError):
            auth.verify_session(token)
    assert auth.read_remembered_blob("desktop-1") is None
    with pytest.raises(AuthError):
        auth.restore(**restore_kwargs(registered))
    manual = auth.login(username="alice", password="correct horse", device_id="desktop-1")
    now += timedelta(hours=8)
    with pytest.raises(AuthError):
        auth.verify_session(manual["token"])
    assert auth.delete_remembered_blob("desktop-1")["ok"]
    with pytest.raises(AuthError):
        auth.restore(**restore_kwargs(manual))


def test_same_device_manual_login_invalidates_previous_sessions(tmp_path: Path) -> None:
    """A replaced credential cannot leave an old automatic session usable."""
    auth, _ = make_services(tmp_path)
    original = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    restored = auth.restore(**restore_kwargs(original))
    manual = auth.login(username="alice", password="correct horse", device_id="desktop-1")
    assert auth.verify_session(manual["token"])
    with pytest.raises(AuthError):
        auth.verify_session(restored["token"])
    with pytest.raises(AuthError):
        auth.restore(**restore_kwargs(original))


def test_password_change_reencrypts_trash_and_revokes_old_sessions(tmp_path: Path) -> None:
    """The login password directly decrypts every vault item, including trash."""
    auth, vault = make_services(tmp_path)
    old = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    session = auth.verify_session(old["token"])
    ids = []
    for name in ("live", "trash"):
        ids.append(vault.create_item(session=session, item_type="secure_note",
                                    fields={"name": name, "note": "sensitive ✓"}, tags=[], asset_ids=[])["item"]["item_id"])
    vault.move_to_trash(session=session, item_ids=[ids[1]])
    with Session(auth.engine) as db:
        before = {item.item_id: item.encrypted_payload for item in db.exec(select(VaultItem)).all()}
    assert auth.change_password(old["token"], "correct horse", "new correct horse")["ok"]
    with pytest.raises(AuthError):
        auth.verify_session(old["token"])
    with pytest.raises(AuthError):
        auth.restore(**restore_kwargs(old))
    with pytest.raises(AuthError):
        auth.login(username="alice", password="correct horse")
    new = auth.login(username="alice", password="new correct horse")
    current = auth.verify_session(new["token"])
    assert all(vault.get_item(session=current, item_id=item_id)["item"]["fields"]["note"] == "sensitive ✓" for item_id in ids)
    with Session(auth.engine) as db:
        assert all(item.encrypted_payload != before[item.item_id] for item in db.exec(select(VaultItem)).all())
    with pytest.raises(ValueError, match="expired"):
        vault.create_item(session=session, item_type="secure_note", fields={"name": "stale", "note": "old key"}, tags=[], asset_ids=[])


def test_password_change_rolls_back_on_corrupt_vault_payload(tmp_path: Path) -> None:
    """An undecryptable item leaves verifier, versions and existing ciphertext intact."""
    auth, vault = make_services(tmp_path)
    old = auth.register(username="alice", password="correct horse")
    session = auth.verify_session(old["token"])
    item = vault.create_item(session=session, item_type="secure_note", fields={"name": "safe", "note": "hidden"}, tags=[], asset_ids=[])["item"]
    with Session(auth.engine) as db:
        valid_cipher = db.get(VaultItem, item["item_id"]).encrypted_payload
        db.add(VaultItem(item_id="corrupt", user_id=session.user_id, item_type="secure_note", encrypted_payload="corrupt"))
        db.commit()
    with pytest.raises(AuthError, match="was not changed"):
        auth.change_password(old["token"], "correct horse", "new correct horse")
    with Session(auth.engine) as db:
        assert db.get(Account, session.user_id).password_version == 1
        assert db.get(VaultItem, item["item_id"]).encrypted_payload == valid_cipher
    assert auth.verify_session(old["token"])
    assert auth.login(username="alice", password="correct horse")


def test_onboarding_progress_resumes_and_cannot_skip_pages(tmp_path: Path) -> None:
    """Persist one ordered five-page workflow and keep completion stable on retry."""
    auth, _ = make_services(tmp_path)
    original = auth.register(username="alice", password="correct horse")
    with pytest.raises(AuthError):
        auth.update_onboarding(original["token"], 5)
    assert auth.update_onboarding(original["token"], 3)["onboarding_step"] == 3
    auth.close()
    restarted = AuthService(config=auth.config, engine=auth.engine)
    token = restarted.login(username="alice", password="correct horse")["token"]
    assert restarted.get_status(token)["onboarding_step"] == 3
    for step in (4, 5, 6, 6):
        assert restarted.update_onboarding(token, step)["onboarding_step"] == step
    assert restarted.get_status(token)["onboarding_completed"]


def test_concurrent_registration_resolves_id_collision_using_persisted_time(tmp_path: Path, monkeypatch) -> None:
    """Database uniqueness resolves real concurrent collisions without random IDs."""
    auth, _ = make_services(tmp_path)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    original_encode = auth.encode_user_id
    monkeypatch.setattr(auth, "encode_user_id", lambda name, created: "12345678" if created == now else original_encode(name, created))
    original_hash = auth._password_hash
    barrier = Barrier(2)

    def synchronized_hash(password, salt, iterations):
        """Force both registrations to reach the same creation instant."""
        barrier.wait(timeout=5)
        return original_hash(password, salt, iterations)

    monkeypatch.setattr(auth, "_password_hash", synchronized_hash)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda name: auth.register(username=name, password="correct horse"), ("alice", "bob")))
    assert len({item["user_id"] for item in results}) == 2
    with Session(auth.engine) as db:
        accounts = db.exec(select(Account)).all()
        assert len(accounts) == 2
        assert {auth._aware(item.created_at) for item in accounts} == {now, now + timedelta(microseconds=1)}
        assert all(item.user_id == auth.encode_user_id(item.username, auth._aware(item.created_at)) for item in accounts)


def test_concurrent_password_changes_have_one_atomic_winner(tmp_path: Path, monkeypatch) -> None:
    """Version compare-and-swap rejects the losing rotation without corrupting vault data."""
    auth, vault = make_services(tmp_path)
    registered = auth.register(username="alice", password="correct horse")
    item = vault.create_item(session=auth.verify_session(registered["token"]), item_type="secure_note",
                             fields={"name": "private", "note": "intact"}, tags=[], asset_ids=[])["item"]
    original_hash = auth._password_hash
    barrier = Barrier(2)

    def synchronize_old_verification(password, salt, iterations):
        """Both changes validate the same current version before reserving the writer slot."""
        if password == "correct horse":
            barrier.wait(timeout=5)
        return original_hash(password, salt, iterations)

    monkeypatch.setattr(auth, "_password_hash", synchronize_old_verification)

    def rotate(password):
        """Return the terminal state of each competing mutation."""
        try:
            auth.change_password(registered["token"], "correct horse", password)
            return password, 200
        except AuthError as error:
            return password, error.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(rotate, ("first replacement", "second replacement")))
    assert sorted(status for _, status in outcomes) == [200, 409]
    winner = next(password for password, status in outcomes if status == 200)
    logged_in = auth.login(username="alice", password=winner)
    assert vault.get_item(session=auth.verify_session(logged_in["token"]), item_id=item["item_id"])["item"]["fields"]["note"] == "intact"
    with Session(auth.engine) as db:
        assert db.get(Account, registered["user_id"]).password_version == 2


def test_expired_startup_read_cannot_erase_concurrently_renewed_blob(tmp_path: Path, monkeypatch) -> None:
    """Expiry cleanup targets the old grant while explicit confirmation renews it."""
    auth, _ = make_services(tmp_path)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    registered = auth.register(username="alice", password="correct horse", device_id="desktop-1")
    auth.write_remembered_blob(registered["token"], "desktop-1", base64.b64encode(b"old-ciphertext").decode("ascii"))
    now += timedelta(days=30)
    expired_clear_ready, renewal_finished = Event(), Event()

    def pause_expired_clear(connection, cursor, statement, parameters, context, executemany):
        """Hold only the test cursor boundary before the old cleanup SQL executes."""
        if current_thread().name.startswith("expiry-cleanup") and statement.startswith("UPDATE auth_devices SET remembered_blob"):
            expired_clear_ready.set()
            assert renewal_finished.wait(timeout=5)

    event.listen(auth.engine, "before_cursor_execute", pause_expired_clear)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="expiry-cleanup") as worker:
            pending = worker.submit(auth.read_remembered_blob, "desktop-1")
            try:
                assert expired_clear_ready.wait(timeout=5)
                renewed = auth.login(username="alice", password="correct horse", device_id="desktop-1")
                new_blob = base64.b64encode(b"new-ciphertext").decode("ascii")
                auth.write_remembered_blob(renewed["token"], "desktop-1", new_blob)
            finally:
                renewal_finished.set()
            read = pending.result(timeout=5)
        assert not read["expired"] and read["blob"] == new_blob
        assert auth.read_remembered_blob("desktop-1")["blob"] == new_blob
    finally:
        event.remove(auth.engine, "before_cursor_execute", pause_expired_clear)
