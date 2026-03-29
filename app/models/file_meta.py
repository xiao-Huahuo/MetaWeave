from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


class FileMetaBase(SQLModel):
    file_path: str = Field(index=True)
    file_name: str
    file_type: str
    file_size: int
    parent_folder: str
    file_hash: str = Field(index=True)
    tags: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)


class FileMeta(FileMetaBase, table=True):
    fid: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.uid", index=True)
    kb_id: int = Field(foreign_key="knowledgebase.kb_id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    modified_at: datetime = Field(default_factory=datetime.now)
    last_indexed_at: datetime = Field(default_factory=datetime.now)
    is_deleted: bool = Field(default=False)

    # 关联知识库
    knowledge_base: Optional["KnowledgeBase"] = Relationship(back_populates="files")
