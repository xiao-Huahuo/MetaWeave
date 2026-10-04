"""Persist login identity, password derivation parameters and hashed credentials.

AuthService owns these tables. Passwords, access tokens and derived vault keys are
never persisted; remembered_blob contains only Electron safeStorage ciphertext.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, Field, SQLModel, Text

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.models.session import utc_now


class AccountBase(SQLModel):
    """Public account identity shared with response DTOs."""

    username: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.auth_username_max_chars, description="Normalized unique login name.")
    created_at: datetime = Field(default_factory=utc_now, description="UTC creation time encoded together with username into user_id.")
    onboarding_step: int = Field(default=DEFAULT_BUSINESS_LIMITS.auth_onboarding_first_step, description="Next initialization page; 6 means all five pages completed.")
    onboarding_completed: bool = Field(default=False, description="Whether initialization has finished.")


class Account(AccountBase, table=True):
    """Account password verifier and direct password-derived vault key parameters."""

    __tablename__ = "accounts"

    user_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_user_id_digits, description="Eight decimal digits encoded from username and created_at.")
    username: str = Field(unique=True, index=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_username_max_chars, description="NFKC and casefold normalized login name.")
    password_hash: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length, description="Base64 PBKDF2 SHA-256 verifier.")
    password_salt: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length, description="Base64 random salt for verifier and direct vault derivation.")
    password_kdf_iterations: int = Field(description="Persisted verifier iteration count.")
    encryption_kdf_iterations: int = Field(description="Persisted direct Fernet key iteration count.")
    key_fingerprint: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="SHA-256 fingerprint used to validate remembered derived keys.")
    password_version: int = Field(default=1, description="Monotonic credential version invalidating old sessions and devices.")
    updated_at: datetime = Field(default_factory=utc_now, description="UTC time of last account change.")


class AuthAccessSession(SQLModel, table=True):
    """Durable revocation metadata; the corresponding vault key stays in RAM."""

    __tablename__ = "auth_access_sessions"

    token_hash: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="SHA-256 of the random opaque bearer token.")
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_user_id_digits, description="Account owner.")
    device_id: str = Field(default="", index=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_device_id_max_chars, description="Remembered device associated with this session, if any.")
    device_credential_hash: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="Device grant version fingerprint preventing concurrent old restores.")
    password_version: int = Field(description="Account credential version at authentication.")
    expires_at: datetime = Field(index=True, description="Fixed access session expiry.")
    revoked_at: datetime | None = Field(default=None, description="Explicit logout or password change revocation time.")
    created_at: datetime = Field(default_factory=utc_now, description="UTC authentication time.")


class AuthDevice(SQLModel, table=True):
    """Fixed lifetime remembered login credential and opaque OS-encrypted material."""

    __tablename__ = "auth_devices"

    device_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_device_id_max_chars, description="Random installation identifier assigned by desktop main process.")
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.auth_user_id_digits, description="Owner account.")
    credential_hash: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="SHA-256 of a random remembered credential.")
    password_version: int = Field(description="Password version at manual authentication.")
    key_fingerprint: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="Expected fingerprint of OS-protected direct vault key.")
    remembered_blob: str = Field(default="", sa_column=Column(Text, nullable=False), description="Base64 safeStorage ciphertext; backend never decrypts it.")
    expires_at: datetime = Field(index=True, description="Exactly 30 days after the last manual authentication; restore never extends it.")
    revoked_at: datetime | None = Field(default=None, description="Explicit revocation time.")
    created_at: datetime = Field(default_factory=utc_now, description="UTC manual authentication time.")


class AuthAttempt(SQLModel, table=True):
    """Bound failed authentication attempts without storing login input."""

    __tablename__ = "auth_attempts"

    attempt_key: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length, description="Hash of normalized login or device identity.")
    attempts: int = Field(default=0, description="Reserved authentication attempts within the current window.")
    started_at: datetime = Field(description="UTC start of the fixed throttle window.")
