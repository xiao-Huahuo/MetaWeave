from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from app.core.database import get_session
from app.models.file_meta import FileMeta
from app.models.knowledge_base import KnowledgeBase
from app.schemas.file_meta import FileMetaRead
from app.api.deps import get_current_user
from app.models.user import User
from app.services.file_scanner import scan_directory

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


@router.post("/sync/{kb_id}")
def sync_kb_files(
    kb_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """手动触发扫描，同步知识库中的文件"""
    # 验证权限
    statement = select(KnowledgeBase).where(
        KnowledgeBase.kb_id == kb_id,
        KnowledgeBase.user_id == current_user.uid
    )
    kb = session.exec(statement).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")

    # 清理已有的文件元数据
    old_files_statement = select(FileMeta).where(FileMeta.kb_id == kb_id)
    old_files = session.exec(old_files_statement).all()
    for f in old_files:
        session.delete(f)
    session.commit()

    # 重新扫描
    scan_directory(kb_id, kb.kb_path, current_user.uid, session)

    return {"message": "同步完成"}
