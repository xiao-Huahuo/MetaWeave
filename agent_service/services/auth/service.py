"""Authenticate one account password for application access and the Fernet vault.

The application owns one AuthService and closes it through lifespan. Database
records contain credential hashes/revocations; derived keys exist only in its
bounded-lifetime in-memory sessions. Only manual register/login issue a new
30-day device credential. Trusted desktop routes transport remember material.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.account import Account, AuthAccessSession, AuthAttempt, AuthDevice
from agent_service.models.vault import VaultItem


class AuthError(ValueError):
    """Transport-neutral authentication error with an HTTP-compatible status."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        """Keep safe public error text without attaching credential input."""
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AuthSession:
    """Validated account identity and short-lived private vault decryption key."""

    user_id: str
    username: str
    fernet_key: str = field(repr=False)
    password_version: int
    expires_at: datetime
    device_id: str = ""


class AuthService:
    """Own account persistence, credential validation and in-memory key lifetime."""

    def __init__(self, *, config: AgentConfig, engine: Any) -> None:
        """Receive the shared engine; never create tables or a separate pool."""
        self.config = config
        self.engine = engine
        self._sessions: dict[str, AuthSession] = {}
        # This lock protects only RAM snapshots; database/KDF work stays outside.
        self._session_lock = Lock()
        self._closed = False
        self._dummy_salt = secrets.token_bytes(config.limits.vault_salt_bytes)

    def register(self, *, username: str, password: str, device_id: str | None = None) -> dict[str, Any]:
        """Create a normalized account and encode its eight-digit stable identity."""
        name = self._normalize_username(username)
        self._validate_password(password)
        device = self._normalize_device_id(device_id)
        self._reserve_attempt("register:" + name)
        salt = secrets.token_bytes(self.config.limits.vault_salt_bytes)
        verifier = self._password_hash(password, salt, self.config.limits.vault_password_kdf_iterations)
        key = self._fernet_key(password, salt, self.config.limits.vault_encryption_kdf_iterations)
        now = self._now()
        for offset in range(self.config.limits.auth_registration_collision_retries):
            created_at = now + timedelta(microseconds=offset)
            account = Account(
                user_id=self.encode_user_id(name, created_at), username=name,
                created_at=created_at, updated_at=created_at,
                password_hash=verifier, password_salt=self._b64(salt),
                password_kdf_iterations=self.config.limits.vault_password_kdf_iterations,
                encryption_kdf_iterations=self.config.limits.vault_encryption_kdf_iterations,
                key_fingerprint=self._hash(key),
            )
            with Session(self.engine) as db:
                try:
                    db.add(account)
                    db.commit()
                    db.refresh(account)
                except IntegrityError as exc:
                    db.rollback()
                    duplicate = db.exec(select(Account).where(Account.username == name)).first()
                    if duplicate is not None:
                        raise AuthError("username is unavailable", 409) from exc
                    continue
            self._clear_attempt("register:" + name)
            return self._issue(account=account, key=key, device_id=device, remember=bool(device))
        raise AuthError("unable to allocate account identity; retry registration", 503)

    def login(self, *, username: str, password: str, device_id: str | None = None) -> dict[str, Any]:
        """Verify the password and explicitly start a new remembered lifetime."""
        name = self._normalize_username(username)
        self._validate_password(password)
        device = self._normalize_device_id(device_id)
        self._reserve_attempt("login:" + name)
        with Session(self.engine) as db:
            account = db.exec(select(Account).where(Account.username == name)).first()
        salt = self._decode_salt(account.password_salt) if account else self._dummy_salt
        iterations = account.password_kdf_iterations if account else self.config.limits.vault_password_kdf_iterations
        candidate = self._password_hash(password, salt, iterations)
        if account is None or not hmac.compare_digest(candidate, account.password_hash):
            raise AuthError("invalid username or password")
        key = self._fernet_key(password, salt, account.encryption_kdf_iterations)
        self._clear_attempt("login:" + name)
        return self._issue(account=account, key=key, device_id=device, remember=bool(device))

    def restore(self, *, device_id: str, credential: str, vault_key: str, password_version: int) -> dict[str, Any]:
        """Restore a valid remembered grant without changing its fixed expiry."""
        device_id = self._normalize_device_id(device_id)
        self._validate_secret(credential)
        self._validate_key(vault_key)
        self._reserve_attempt("device:" + device_id)
        with Session(self.engine) as db:
            device = db.get(AuthDevice, device_id)
            account = db.get(Account, device.user_id) if device else None
        now = self._now()
        if (device is None or account is None or device.revoked_at is not None
                or self._aware(device.expires_at) <= now
                or device.password_version != password_version
                or account.password_version != password_version
                or not hmac.compare_digest(device.credential_hash, self._hash(credential))
                or not hmac.compare_digest(account.key_fingerprint, self._hash(vault_key))
                or not hmac.compare_digest(device.key_fingerprint, account.key_fingerprint)):
            raise AuthError("remembered login is invalid or expired; confirm with your password")
        self._clear_attempt("device:" + device_id)
        return self._issue(account=account, key=vault_key, device_id=device_id,
                           remember=False, expected_credential_hash=device.credential_hash)

    def verify_session(self, token: str) -> AuthSession:
        """Validate RAM key lifetime and durable account/device revocation."""
        raw = self._raw_token(token)
        token_hash = self._hash(raw)
        with self._session_lock:
            session = self._sessions.get(token_hash)
        now = self._now()
        if session is None or session.expires_at <= now:
            with self._session_lock:
                self._sessions.pop(token_hash, None)
            raise AuthError("login session is invalid or expired")
        with Session(self.engine) as db:
            record = db.get(AuthAccessSession, token_hash)
            account = db.get(Account, session.user_id)
            device = db.get(AuthDevice, session.device_id) if session.device_id else None
        if (record is None or record.revoked_at is not None or self._aware(record.expires_at) <= now
                or account is None or account.password_version != session.password_version
                or record.password_version != session.password_version
                or (session.device_id and (device is None or device.revoked_at is not None
                    or device.password_version != session.password_version
                    or not hmac.compare_digest(device.credential_hash, record.device_credential_hash)))):
            with self._session_lock:
                self._sessions.pop(token_hash, None)
            raise AuthError("login session is invalid or expired")
        return session

    def logout(self, token: str, device_id: str | None = None) -> dict[str, bool]:
        """Revoke the active access session and its remembered device grant."""
        session = self.verify_session(token)
        device_id = self._normalize_device_id(device_id) or session.device_id
        now = self._now()
        with Session(self.engine) as db:
            db.exec(update(AuthAccessSession).where(AuthAccessSession.token_hash == self._hash(self._raw_token(token)))
                    .values(revoked_at=now))
            if device_id:
                device = db.get(AuthDevice, device_id)
                if device is not None and device.user_id != session.user_id:
                    raise AuthError("remembered device is not owned by this account", 403)
                if device is not None:
                    device.revoked_at = now
                    device.remembered_blob = ""
                    db.add(device)
                    db.exec(update(AuthAccessSession).where(AuthAccessSession.device_id == device_id).values(revoked_at=now))
            db.commit()
        with self._session_lock:
            self._sessions = {key: value for key, value in self._sessions.items()
                              if key != self._hash(self._raw_token(token)) and not (device_id and value.device_id == device_id)}
        return {"ok": True}

    def change_password(self, token: str, old_password: str, new_password: str) -> dict[str, bool]:
        """Re-encrypt every live/trash vault item atomically and revoke all grants."""
        session = self.verify_session(token)
        self._validate_password(old_password)
        self._validate_password(new_password)
        self._reserve_attempt("password:" + session.user_id)
        with Session(self.engine) as db:
            account = db.get(Account, session.user_id)
            if account is None or account.password_version != session.password_version:
                raise AuthError("login session is invalid or expired")
            old_salt = self._decode_salt(account.password_salt)
            if not hmac.compare_digest(account.password_hash, self._password_hash(old_password, old_salt, account.password_kdf_iterations)):
                raise AuthError("invalid username or password")
            old_key = self._fernet_key(old_password, old_salt, account.encryption_kdf_iterations)
            new_salt = secrets.token_bytes(self.config.limits.vault_salt_bytes)
            new_key = self._fernet_key(new_password, new_salt, self.config.limits.vault_encryption_kdf_iterations)
            source, target = Fernet(old_key.encode("ascii")), Fernet(new_key.encode("ascii"))
            now = self._now()
            # Reserve the version before reading items. The SQL conditional write
            # serializes concurrent changes without holding a Python lock over I/O.
            changed = db.exec(update(Account).where(Account.user_id == session.user_id)
                              .where(Account.password_version == session.password_version)
                              .values(password_version=session.password_version + 1))
            if changed.rowcount != 1:
                raise AuthError("password changed concurrently; log in again", 409)
            try:
                for item in db.exec(select(VaultItem).where(VaultItem.user_id == session.user_id)).all():
                    item.encrypted_payload = target.encrypt(source.decrypt(item.encrypted_payload.encode("ascii"))).decode("ascii")
                    item.updated_at = now
                    db.add(item)
            except (InvalidToken, UnicodeError) as exc:
                raise AuthError("vault data could not be re-encrypted; password was not changed", 409) from exc
            account.password_hash = self._password_hash(new_password, new_salt, self.config.limits.vault_password_kdf_iterations)
            account.password_salt = self._b64(new_salt)
            account.password_kdf_iterations = self.config.limits.vault_password_kdf_iterations
            account.encryption_kdf_iterations = self.config.limits.vault_encryption_kdf_iterations
            account.key_fingerprint = self._hash(new_key)
            account.password_version = session.password_version + 1
            account.updated_at = now
            db.add(account)
            db.exec(update(AuthAccessSession).where(AuthAccessSession.user_id == session.user_id).values(revoked_at=now))
            db.exec(update(AuthDevice).where(AuthDevice.user_id == session.user_id).values(revoked_at=now, remembered_blob=""))
            db.commit()
        self._clear_attempt("password:" + session.user_id)
        with self._session_lock:
            self._sessions = {key: value for key, value in self._sessions.items() if value.user_id != session.user_id}
        return {"ok": True}

    def get_status(self, token: str) -> dict[str, Any]:
        """Read current identity and durable initialization progress."""
        session = self.verify_session(token)
        with Session(self.engine) as db:
            account = db.get(Account, session.user_id)
            return self._account_payload(account)

    def update_onboarding(self, token: str, step: int) -> dict[str, Any]:
        """Advance initialization one saved page at a time; retries are idempotent."""
        session = self.verify_session(token)
        if isinstance(step, bool) or step not in range(2, 7):
            raise AuthError("onboarding step must be between 2 and 6", 422)
        with Session(self.engine) as db:
            account = db.get(Account, session.user_id)
            if account is None or step not in {account.onboarding_step, account.onboarding_step + 1}:
                raise AuthError("initialization pages must be saved in order", 409)
            changed = db.exec(update(Account).where(Account.user_id == session.user_id)
                              .where(Account.onboarding_step == account.onboarding_step)
                              .values(onboarding_step=step, onboarding_completed=step == 6, updated_at=self._now()))
            if changed.rowcount != 1:
                raise AuthError("initialization changed concurrently; reload progress", 409)
            db.commit()
            db.refresh(account)
            return self._account_payload(account)

    def write_remembered_blob(self, token: str, device_id: str, blob: str) -> dict[str, bool]:
        """Persist only bounded base64 OS ciphertext for the session's own device."""
        session = self.verify_session(token)
        device_id = self._normalize_device_id(device_id)
        try:
            content = base64.b64decode(blob, validate=True)
        except (ValueError, UnicodeError) as exc:
            raise AuthError("remembered payload must be base64 ciphertext", 422) from exc
        if not content or len(content) > self.config.limits.auth_remembered_blob_max_bytes:
            raise AuthError("remembered payload size is invalid", 422)
        with Session(self.engine) as db:
            device = db.get(AuthDevice, device_id)
            access = db.get(AuthAccessSession, self._hash(self._raw_token(token)))
            if (device is None or device_id != session.device_id or device.user_id != session.user_id
                    or device.revoked_at is not None or self._aware(device.expires_at) <= self._now()
                    or device.password_version != session.password_version or access is None):
                raise AuthError("remembered device is invalid or expired")
            stored = db.exec(update(AuthDevice).where(AuthDevice.device_id == device_id)
                             .where(AuthDevice.credential_hash == access.device_credential_hash)
                             .where(AuthDevice.password_version == session.password_version)
                             .where(AuthDevice.revoked_at == None)  # noqa: E711
                             .values(remembered_blob=blob))
            if stored.rowcount != 1:
                raise AuthError("remembered login changed; confirm with your password")
            db.commit()
        return {"ok": True}

    def read_remembered_blob(self, device_id: str) -> dict[str, Any] | None:
        """Trusted desktop reads ciphertext and username; expiry removes key material."""
        device_id = self._normalize_device_id(device_id)
        with Session(self.engine) as db:
            device = db.get(AuthDevice, device_id)
            account = db.get(Account, device.user_id) if device else None
            if (device is None or account is None or device.revoked_at is not None
                    or device.password_version != account.password_version):
                return None
            expired = self._aware(device.expires_at) <= self._now()
            if expired and device.remembered_blob:
                # A startup read must not erase a concurrently renewed grant.
                db.exec(update(AuthDevice).where(AuthDevice.device_id == device_id)
                        .where(AuthDevice.credential_hash == device.credential_hash)
                        .where(AuthDevice.expires_at <= self._now()).values(remembered_blob="")
                        .execution_options(synchronize_session=False))
                db.commit()
                db.refresh(device)
                account = db.get(Account, device.user_id)
                if account is None or device.revoked_at is not None or device.password_version != account.password_version:
                    return None
                expired = self._aware(device.expires_at) <= self._now()
            return {"device_id": device_id, "username": account.username,
                    "expires_at": self._aware(device.expires_at).isoformat(),
                    "password_version": device.password_version,
                    "blob": device.remembered_blob, "expired": expired}

    def delete_remembered_blob(self, device_id: str) -> dict[str, bool]:
        """Trusted desktop deletes a local grant even when its access session expired."""
        device_id = self._normalize_device_id(device_id)
        now = self._now()
        with Session(self.engine) as db:
            device = db.get(AuthDevice, device_id)
            if device:
                device.remembered_blob = ""
                device.revoked_at = now
                db.add(device)
                db.exec(update(AuthAccessSession).where(AuthAccessSession.device_id == device_id).values(revoked_at=now))
                db.commit()
        with self._session_lock:
            self._sessions = {key: value for key, value in self._sessions.items() if value.device_id != device_id}
        return {"ok": True}

    def close(self) -> None:
        """Destroy all in-memory vault keys; database remembered grants survive exit."""
        with self._session_lock:
            self._closed = True
            self._sessions.clear()

    def _issue(self, *, account: Account, key: str, device_id: str, remember: bool,
               expected_credential_hash: str = "") -> dict[str, Any]:
        """Commit a revocable opaque session after rechecking credential version."""
        now = self._now()
        expires_at = now + timedelta(hours=self.config.limits.auth_access_session_hours)
        token = secrets.token_urlsafe(self.config.limits.auth_token_bytes)
        token_hash = self._hash(token)
        remembered: dict[str, Any] | None = None
        with Session(self.engine) as db:
            db.exec(delete(AuthAccessSession).where(AuthAccessSession.expires_at <= now))
            current = db.get(Account, account.user_id)
            if current is None or current.password_version != account.password_version:
                raise AuthError("credentials changed; confirm with your password")
            device = db.get(AuthDevice, device_id) if device_id else None
            if remember:
                credential = secrets.token_urlsafe(self.config.limits.auth_token_bytes)
                device_expiry = now + timedelta(days=self.config.limits.auth_remember_days)
                db.exec(update(AuthAccessSession).where(AuthAccessSession.device_id == device_id).values(revoked_at=now))
                values = {"device_id": device_id, "user_id": current.user_id,
                          "credential_hash": self._hash(credential), "password_version": current.password_version,
                          "key_fingerprint": current.key_fingerprint, "remembered_blob": "",
                          "expires_at": device_expiry, "revoked_at": None, "created_at": now}
                # Native SQLite upsert makes simultaneous first manual logins on
                # one installation deterministic instead of failing a PK insert.
                db.exec(sqlite_insert(AuthDevice).values(**values).on_conflict_do_update(
                    index_elements=[AuthDevice.device_id], set_=values))
                db.expire_all()
                device = db.get(AuthDevice, device_id)
                remembered = {"device_id": device_id, "credential": credential,
                              "vault_key": key, "password_version": current.password_version,
                              "expires_at": device_expiry.isoformat()}
            elif device_id and (device is None or device.revoked_at is not None
                    or self._aware(device.expires_at) <= now or device.user_id != current.user_id
                    or not hmac.compare_digest(device.credential_hash, expected_credential_hash)):
                raise AuthError("remembered login is invalid or expired")
            db.add(AuthAccessSession(token_hash=token_hash, user_id=current.user_id,
                                     device_id=device_id, password_version=current.password_version,
                                     device_credential_hash=device.credential_hash if device else "",
                                     expires_at=expires_at, created_at=now))
            db.commit()
            db.refresh(current)
            result = self._account_payload(current)
            session = AuthSession(current.user_id, current.username, key, current.password_version, expires_at, device_id)
        with self._session_lock:
            if self._closed:
                raise AuthError("authentication service is shutting down", 503)
            self._sessions = {digest: value for digest, value in self._sessions.items() if value.expires_at > now}
            self._sessions[token_hash] = session
        result.update(token=token, expires_at=expires_at.isoformat())
        if remembered:
            result["remember"] = remembered
        return result

    def _reserve_attempt(self, identity: str) -> None:
        """Atomically reserve a bounded attempt before expensive derivation work."""
        digest, now = self._hash(identity), self._now()
        cutoff = now - timedelta(seconds=self.config.limits.auth_failure_window_seconds)
        with Session(self.engine) as db:
            db.exec(delete(AuthAttempt).where(AuthAttempt.started_at <= cutoff))
            db.commit()
            attempt = db.get(AuthAttempt, digest)
            if attempt is None:
                try:
                    db.add(AuthAttempt(attempt_key=digest, attempts=0, started_at=now))
                    db.commit()
                except IntegrityError:
                    db.rollback()
            reserved = db.exec(update(AuthAttempt).where(AuthAttempt.attempt_key == digest)
                               .where(AuthAttempt.attempts < self.config.limits.auth_failure_limit)
                               .values(attempts=AuthAttempt.attempts + 1))
            db.commit()
            if reserved.rowcount != 1:
                raise AuthError("too many login attempts; try again later", 429)

    def _clear_attempt(self, identity: str) -> None:
        """Successful authentication clears only its own throttle bucket."""
        with Session(self.engine) as db:
            db.exec(delete(AuthAttempt).where(AuthAttempt.attempt_key == self._hash(identity)))
            db.commit()

    def _normalize_username(self, username: str) -> str:
        """Normalize names identically for registration, login and ID derivation."""
        if not isinstance(username, str):
            raise AuthError("username is required", 422)
        name = unicodedata.normalize("NFKC", username).strip().casefold()
        if not name or len(name) > self.config.limits.auth_username_max_chars or any(unicodedata.category(char).startswith("C") for char in name):
            raise AuthError("username length or characters are invalid", 422)
        return name

    def _validate_password(self, password: str) -> None:
        """Apply one bounded password policy for application and vault access."""
        if (not isinstance(password, str) or not self.config.limits.vault_password_min_chars <= len(password)
                <= self.config.limits.auth_password_max_chars):
            raise AuthError("password length is invalid", 422)

    def _normalize_device_id(self, device_id: str | None) -> str:
        """Validate opaque main-process installation identifiers without trimming."""
        if device_id is None:
            return ""
        if (not isinstance(device_id, str) or not device_id or len(device_id) > self.config.limits.auth_device_id_max_chars
                or any(not (char.isascii() and (char.isalnum() or char in "-_")) for char in device_id)):
            raise AuthError("device identity is invalid", 422)
        return device_id

    def _validate_secret(self, value: str) -> None:
        """Bound untrusted opaque tokens before hashing or lookup."""
        if not isinstance(value, str) or not value or len(value) > self.config.limits.auth_device_id_max_chars:
            raise AuthError("login credential is invalid")

    def _raw_token(self, token: str) -> str:
        """Accept a bare opaque token or its Authorization header form."""
        if not isinstance(token, str):
            raise AuthError("login session is invalid or expired")
        raw = token.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        self._validate_secret(raw)
        return raw

    @staticmethod
    def _validate_key(key: str) -> None:
        """Reject malformed direct Fernet keys before remembered restore."""
        try:
            if not isinstance(key, str) or len(key) != 44:
                raise ValueError("invalid key size")
            Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise AuthError("remembered login key is invalid") from exc

    @staticmethod
    def encode_user_id(username: str, created_at: datetime) -> str:
        """Map normalized name plus persisted UTC microseconds to eight digits."""
        timestamp = AuthService._aware(created_at).isoformat(timespec="microseconds")
        material = f"{username}|{timestamp}".encode("utf-8")
        return str(10_000_000 + int.from_bytes(hashlib.sha256(material).digest(), "big") % 90_000_000)

    @staticmethod
    def _account_payload(account: Account) -> dict[str, Any]:
        """Expose account fields with no verifier or decryption material."""
        return {"user_id": account.user_id, "username": account.username,
                "created_at": AuthService._aware(account.created_at).isoformat(),
                "onboarding_step": account.onboarding_step, "onboarding_completed": account.onboarding_completed}

    @staticmethod
    def _password_hash(password: str, salt: bytes, iterations: int) -> str:
        """PBKDF2-SHA256 verifier with iterations stored beside the account."""
        return AuthService._b64(hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations))

    def _fernet_key(self, password: str, salt: bytes, iterations: int) -> str:
        """Keep the existing direct salt+:fernet PBKDF2 encryption format."""
        return self._b64(hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt + b":fernet",
                                            iterations, dklen=self.config.limits.vault_encryption_key_bytes))

    @staticmethod
    def _decode_salt(value: str) -> bytes:
        """Decode persisted derivation salt."""
        return base64.urlsafe_b64decode(value.encode("ascii"))

    @staticmethod
    def _b64(value: bytes) -> str:
        """Encode derivation bytes without locale-dependent conversion."""
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _hash(value: str) -> str:
        """Fingerprint high-entropy tokens and keys using the standard library."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _aware(value: datetime) -> datetime:
        """Restore UTC timezone for SQLite DateTime values loaded as naive."""
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _now() -> datetime:
        """Use UTC instants for all credential lifetime comparisons."""
        return datetime.now(timezone.utc)
