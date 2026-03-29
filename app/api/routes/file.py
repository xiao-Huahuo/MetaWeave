from fastapi import APIRouter, Depends, HTTPException
import os
from fastapi.responses import FileResponse
import mimetypes
from sqlmodel import Session, select
from typing import List
from app.core.database import get_session
from app.models.file_meta import FileMeta
from app.models.knowledge_base import KnowledgeBase
from app.schemas.file_meta import FileMetaRead
from app.api.deps import get_current_user, get_current_user_optional
from app.models.user import User
from app.services.file_scan_job import start_scan_job, get_scan_job

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
        kb_statement = select(KnowledgeBase).where(
            KnowledgeBase.kb_id == kb_id,
            KnowledgeBase.user_id == current_user.uid
        )
        kb = session.exec(kb_statement).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
        start_scan_job(kb_id, kb.kb_path, current_user.uid)
        statement = statement.where(FileMeta.kb_id == kb_id)

    files = session.exec(statement).all()
    return files


@router.get("/detail/{fid}", response_model=FileMetaRead)
def get_file_detail(
    fid: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    statement = select(FileMeta).where(
        FileMeta.fid == fid,
        FileMeta.user_id == current_user.uid,
        FileMeta.is_deleted == False
    )
    file_meta = session.exec(statement).first()
    if not file_meta:
        raise HTTPException(status_code=404, detail="文件不存在")
    return file_meta


@router.get("/raw/{fid}")
def get_file_raw(
    fid: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user_optional)
):
    statement = select(FileMeta).where(
        FileMeta.fid == fid,
        FileMeta.user_id == current_user.uid,
        FileMeta.is_deleted == False
    )
    file_meta = session.exec(statement).first()
    if not file_meta:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not os.path.exists(file_meta.file_path):
        raise HTTPException(status_code=404, detail="本地文件不存在")

    media_type, _ = mimetypes.guess_type(file_meta.file_path)
    headers = {
        "Content-Disposition": f"inline; filename=\"{file_meta.file_name}\"",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(file_meta.file_path, media_type=media_type, headers=headers)


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

    job = start_scan_job(kb_id, kb.kb_path, current_user.uid)
    return {"message": "同步已开始", "job": job}


@router.get("/scan-status/{kb_id}")
def get_scan_status(
    kb_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """获取扫描解析进度"""
    statement = select(KnowledgeBase).where(
        KnowledgeBase.kb_id == kb_id,
        KnowledgeBase.user_id == current_user.uid
    )
    kb = session.exec(statement).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
    job = get_scan_job(kb_id)
    if job.get("status") == "idle":
        job = start_scan_job(kb_id, kb.kb_path, current_user.uid)
    return job
