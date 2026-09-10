"""Scanner REST request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS

ScannerVariant = Literal["ocr", "no_ocr"]
ScannerConflictStrategy = Literal["overwrite", "skip", "rename"]


class ScannerUrlCreate(BaseModel):
    """Create a scanner task from one public HTTP(S) webpage."""

    user_id: str = Field(min_length=1, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    url: HttpUrl
    ocr_enabled: bool = True


class ScannerDraftUpdate(BaseModel):
    """Persist one editable OCR or no-OCR Markdown draft."""

    user_id: str = Field(min_length=1, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    variant: ScannerVariant
    content: str


class ScannerSourceUpdate(BaseModel):
    """Persist editable text in the managed original source copy."""

    user_id: str = Field(min_length=1, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    content: str


class ScannerCancelRequest(BaseModel):
    """Cancel one queued or running scanner task owned by the user."""

    user_id: str = Field(min_length=1, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)


class ScannerSaveRequest(BaseModel):
    """Save the chosen scanner projection into the active knowledge root."""

    user_id: str = Field(min_length=1, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    variant: ScannerVariant
    conflict_strategy: ScannerConflictStrategy = "overwrite"


class ScannerOut(BaseModel):
    """Complete scanner history and editable projection payload."""

    scan_id: str
    user_id: str
    library_id: str
    source_kind: str
    source_name: str
    source_path: str
    source_url: str
    size: int
    ocr_enabled: bool
    status: str
    stage: str
    stage_label: str
    progress: float
    no_ocr_markdown: str
    ocr_markdown: str
    ocr_blocks: list[dict[str, Any]]
    ocr_preview_path: str = ""
    assets: list[str]
    error: str
    source_text: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class ScannerListOut(BaseModel):
    """Chronologically ordered scanner history and scheduler capacity response."""

    scans: list[ScannerOut]
    max_concurrency: int = Field(ge=1)
