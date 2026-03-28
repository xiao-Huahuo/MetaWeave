from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List
from app.core.database import get_session
from app.models.file_meta import FileMeta
from app.schemas.file_meta import FileMetaRead
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/list", response_model=List[FileMetaRead])
def get_file_list(
    kb_id: int = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """获取文件列表,可按知识库筛选"""
    statement = select(FileMeta).where(
        FileMeta.user_id == current_user.uid,
        FileMeta.is_deleted == False
    )

    if kb_id:
        statement = statement.where(FileMeta.kb_id == kb_id)

    files = session.exec(statement).all()
    return files
