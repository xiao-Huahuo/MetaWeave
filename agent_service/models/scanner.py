"""Scanner history database model.

Scanner records persist task state and both editable Markdown projections while
the original file and extracted assets remain under the active library's
``.mw/scan`` managed directory.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.models.session import utc_now


class ScannerRecord(SQLModel, table=True):
    """Persist one uploaded file, example, or crawled webpage scan."""

    __tablename__ = "scanner_records"

    scan_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    library_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    source_kind: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.short_type_max_length)
    source_name: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.path_max_length)
    source_path: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.path_max_length)
    source_url: str = Field(default="", sa_column=Column(Text))
    size: int = Field(default=0, ge=0)
    ocr_enabled: bool = Field(default=True)
    status: str = Field(default="queued", index=True, max_length=DEFAULT_BUSINESS_LIMITS.short_status_max_length)
    stage: str = Field(default="queued", max_length=DEFAULT_BUSINESS_LIMITS.short_type_max_length)
    stage_label: str = Field(default="等待解析", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    progress: float = Field(
        default=0.0,
        ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value,
        le=DEFAULT_BUSINESS_LIMITS.progress_max_percent,
    )
    no_ocr_markdown: str = Field(default="", sa_column=Column(Text))
    ocr_markdown: str = Field(default="", sa_column=Column(Text))
    ocr_blocks_json: str = Field(default="[]", sa_column=Column(Text))
    assets_json: str = Field(default="[]", sa_column=Column(Text))
    error: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
