from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel
from app.models.file_meta import FileMetaBase


class FileMetaCreate(FileMetaBase):
    user_id: int


class FileMetaUpdate(SQLModel):
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    parent_folder: Optional[str] = None
    file_content: Optional[str] = None
    file_mtime: Optional[float] = None
    content_status: Optional[str] = None
    content_error: Optional[str] = None
    content_extracted_at: Optional[datetime] = None
    tags: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    modified_at: Optional[datetime] = None


class FileMetaRead(FileMetaBase):
    fid: int
    user_id: int
    created_at: datetime
    modified_at: datetime
    last_indexed_at: datetime
    is_deleted: bool
