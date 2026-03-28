from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Dict
from app.core.database import get_session
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseRead, KnowledgeBaseUpdate
from app.api.deps import get_current_user
from app.models.user import User
from app.services.file_watcher import start_file_watcher
from app.core.logger import global_logger as logger

router = APIRouter()

watchers: Dict[int, object] = {}


@router.post("/", response_model=KnowledgeBaseRead)
def create_knowledge_base(
    kb: KnowledgeBaseCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """创建知识库"""
    kb.user_id = current_user.uid
    db_kb = KnowledgeBase.model_validate(kb)
    session.add(db_kb)
    session.commit()
    session.refresh(db_kb)
    return db_kb


@router.get("/list", response_model=List[KnowledgeBaseRead])
def get_knowledge_bases(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """获取用户的所有知识库"""
    statement = select(KnowledgeBase).where(KnowledgeBase.user_id == current_user.uid)
    kbs = session.exec(statement).all()
    return kbs


@router.put("/{kb_id}", response_model=KnowledgeBaseRead)
def update_knowledge_base(
    kb_id: int,
    kb_update: KnowledgeBaseUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """更新知识库"""
    statement = select(KnowledgeBase).where(
        KnowledgeBase.kb_id == kb_id,
        KnowledgeBase.user_id == current_user.uid
    )
    db_kb = session.exec(statement).first()
    if not db_kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    update_data = kb_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_kb, key, value)

    session.add(db_kb)
    session.commit()
    session.refresh(db_kb)
    return db_kb


@router.delete("/{kb_id}")
def delete_knowledge_base(
    kb_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """删除知识库"""
    statement = select(KnowledgeBase).where(
        KnowledgeBase.kb_id == kb_id,
        KnowledgeBase.user_id == current_user.uid
    )
    db_kb = session.exec(statement).first()
    if not db_kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    session.delete(db_kb)
    session.commit()
    return {"message": "知识库已删除"}


@router.post("/start-all-watchers")
def start_all_watchers(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """启动用户所有知识库的监听"""
    statement = select(KnowledgeBase).where(
        KnowledgeBase.user_id == current_user.uid,
        KnowledgeBase.is_active == True
    )
    kbs = session.exec(statement).all()

    started = []
    failed = []

    for kb in kbs:
        if kb.kb_id in watchers:
            continue

        try:
            observer = start_file_watcher(kb.kb_id, kb.kb_path, current_user.uid)
            watchers[kb.kb_id] = observer
            started.append({"kb_id": kb.kb_id, "kb_name": kb.kb_name, "kb_path": kb.kb_path})
        except Exception as e:
            logger.error(f"启动监听失败 {kb.kb_name}: {e}")
            failed.append({"kb_id": kb.kb_id, "kb_name": kb.kb_name, "error": str(e)})

    return {"started": started, "failed": failed}


@router.post("/stop-all-watchers")
def stop_all_watchers(current_user: User = Depends(get_current_user)):
    """停止所有监听"""
    stopped = []
    for kb_id, observer in list(watchers.items()):
        try:
            observer.stop()
            observer.join()
            del watchers[kb_id]
            stopped.append(kb_id)
        except Exception as e:
            logger.error(f"停止监听失败 kb_id={kb_id}: {e}")

    return {"stopped": stopped}
