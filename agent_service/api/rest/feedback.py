"""User feedback REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from agent_service.api.rest.deps import _require_auth_session, _require_feedback_service
from agent_service.schemas.feedback import FeedbackCreate, FeedbackListOut, FeedbackOut, FeedbackUpdate

router = APIRouter()


@router.post("/feedback")
async def add_feedback(payload: FeedbackCreate) -> FeedbackOut:
    """提交并持久化一条用户反馈。"""

    try:
        return await run_in_threadpool(_require_feedback_service().add_feedback, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/feedback")
async def list_feedback(user_id: str | None = Query(None, description="用户 ID")) -> FeedbackListOut:
    """读取当前已验证用户的反馈，省略参数也不会扩大读取范围。"""

    try:
        feedback = await run_in_threadpool(_require_feedback_service().list_feedback, user_id=_require_auth_session().user_id)
        return FeedbackListOut(feedback=feedback)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, payload: FeedbackUpdate) -> FeedbackOut:
    """修改一条已提交的用户反馈。"""

    try:
        feedback = await run_in_threadpool(
            _require_feedback_service().update_feedback,
            feedback_id=feedback_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if feedback is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    return feedback


@router.delete("/feedback/{feedback_id}")
async def delete_feedback(feedback_id: str) -> dict[str, int | bool]:
    """删除一条已提交的用户反馈。"""

    try:
        deleted = await run_in_threadpool(
            _require_feedback_service().delete_feedback,
            feedback_id=feedback_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "deleted_count": 1 if deleted else 0}
