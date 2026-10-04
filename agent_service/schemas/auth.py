"""Bounded REST/gRPC authentication DTOs; trusted desktop owns private key fields."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS as LIMITS


class AuthCredentialsRequest(BaseModel):
    """Manual username/password confirmation shared by registration and login."""

    username: str = Field(min_length=LIMITS.nonempty_min_length, max_length=LIMITS.auth_username_max_chars, description="Account login name; service normalizes Unicode and case.")
    password: str = Field(min_length=LIMITS.vault_password_min_chars, max_length=LIMITS.auth_password_max_chars, repr=False, description="Application password, also the vault master password.")
    device_id: str | None = Field(default=None, max_length=LIMITS.auth_device_id_max_chars, description="Trusted desktop installation identity.")


class AuthRestoreRequest(BaseModel):
    """Private OS-decrypted device credential and direct vault key for restore."""

    device_id: str = Field(min_length=LIMITS.nonempty_min_length, max_length=LIMITS.auth_device_id_max_chars, description="Trusted desktop installation identity.")
    credential: str = Field(min_length=LIMITS.nonempty_min_length, max_length=LIMITS.auth_device_id_max_chars, repr=False, description="Opaque remembered credential.")
    vault_key: str = Field(min_length=LIMITS.auth_fernet_key_chars, max_length=LIMITS.auth_fernet_key_chars, repr=False, description="Direct password-derived Fernet key; never renderer-readable.")
    password_version: int = Field(ge=LIMITS.nonempty_min_length, description="Account password version at manual authentication.")


class AuthPasswordChangeRequest(BaseModel):
    """Re-authenticate the existing password before atomically changing vault keys."""

    old_password: str = Field(min_length=LIMITS.vault_password_min_chars, max_length=LIMITS.auth_password_max_chars, repr=False, description="Current application/vault password.")
    new_password: str = Field(min_length=LIMITS.vault_password_min_chars, max_length=LIMITS.auth_password_max_chars, repr=False, description="Replacement application/vault password.")


class AuthOnboardingRequest(BaseModel):
    """Durable next initialization page after successfully saving the current page."""

    step: int = Field(ge=LIMITS.auth_onboarding_first_step, le=LIMITS.auth_onboarding_complete_step, description="Next page; step 6 completes all five initialization pages.")


class AuthRememberedBlobRequest(BaseModel):
    """Opaque Electron safeStorage ciphertext, not plaintext credentials."""

    device_id: str = Field(min_length=LIMITS.nonempty_min_length, max_length=LIMITS.auth_device_id_max_chars, description="Trusted desktop installation identity.")
    sealed_payload: str = Field(min_length=LIMITS.nonempty_min_length, max_length=((LIMITS.auth_remembered_blob_max_bytes + 2) // 3) * 4, repr=False, description="Base64 OS-encrypted remembered login payload.")


class AuthLogoutRequest(BaseModel):
    """Revoke the session and optional same-owner remembered device."""

    device_id: str | None = Field(default=None, max_length=LIMITS.auth_device_id_max_chars, description="Trusted desktop installation identity, if remembered.")
