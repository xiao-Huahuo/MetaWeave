from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List


class KnowledgeBaseBase(SQLModel):
    kb_name: str = Field(index=True)
    kb_path: str
    description: Optional[str] = Field(default=None)


class KnowledgeBase(KnowledgeBaseBase, table=True):
    kb_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.uid", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = Field(default=True)

    # 关联文件
    files: List["FileMeta"] = Relationship(back_populates="knowledge_base")
