"""
知识库单文件入库任务数据库模型。

功能说明:
持久化每个文件的排队、阶段进度、取消与完成状态，使入库队列可在页面刷新后恢复。
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS

from agent_service.models.session import utc_now


class KnowledgeIngestionJobRecord(SQLModel, table=True):
    """描述一个可独立取消的单文件知识库入库任务。"""

    __tablename__ = "knowledge_ingestion_jobs"

    job_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    library_id: str = Field(default="", index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    path: str = Field(index=True)
    name: str
    pipeline: str = Field(default="text", max_length=DEFAULT_BUSINESS_LIMITS.short_type_max_length)
    status: str = Field(default="queued", index=True, max_length=DEFAULT_BUSINESS_LIMITS.timestamp_text_max_length)
    stage: str = Field(default="queued", max_length=DEFAULT_BUSINESS_LIMITS.short_type_max_length)
    stage_label: str = Field(default="等待灌库")
    progress: float = Field(default=0.0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value, le=DEFAULT_BUSINESS_LIMITS.progress_max_percent)
    stage_current: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)
    stage_total: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)
    size: int | None = None
    mtime: str | None = None
    message: str = ""
    cancel_requested: bool = Field(default=False, index=True)
    result_json: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now, index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
