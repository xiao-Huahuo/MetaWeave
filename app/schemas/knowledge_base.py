from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel
from app.models.knowledge_base import KnowledgeBaseBase


class KnowledgeBaseCreate(KnowledgeBaseBase):
    user_id: int


class KnowledgeBaseUpdate(SQLModel):
    kb_name: Optional[str] = None
    kb_path: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class KnowledgeBaseRead(KnowledgeBaseBase):
    kb_id: int
    user_id: int
    created_at: datetime
    is_active: bool
