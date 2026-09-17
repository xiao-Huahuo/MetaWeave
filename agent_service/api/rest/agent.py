"""
Agent 流式对话与观测端点。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Iterator

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from agent_service.api.recall_details import build_recall_details_payload
from agent_service.api.rest.deps import (
    _require_agent,
    _require_attachment_service,
    _require_dsh_executor,
    _require_message_service,
    _require_session_service,
    _require_settings_service,
)
from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.services.editor_context.service import editor_context_service
from agent_service.services.task_suggestion.service import TaskSuggestionService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.put("/agent/editor-context/current-document")
async def update_current_document_context(body: dict[str, Any]) -> dict[str, Any]:
    """
    更新 editor 前端当前正在观看的文档基本信息。

    该端点只保存瞬时 UI 上下文,不读取或写入文档正文。
    """

    info = editor_context_service.set_current_document(body)
    return {"ok": True, "document": info.to_dict()}


@router.get("/agent/editor-context/current-document")
async def get_current_document_context(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """
    读取 editor 前端最近上报的当前文档基本信息。

    主要用于调试;Agent 正式使用同一状态的内置工具读取。
    """

    info = editor_context_service.get_current_document(user_id)
    return {"document": info.to_dict() if info else None}


@router.get("/agent/tools")
async def agent_tools() -> JSONResponse:
    """
    获取当前 Agent 最终注册表中的所有工具基础信息。

    返回值直接来自 AgentCore 初始化后的工具注册表,用于观测面板展示运行时能力。
    """
    return JSONResponse(
        _require_agent().list_registered_tools(),
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.post("/agent/attachments/upload")
async def upload_agent_attachment(
    user_id: str = Form(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    session_id: str = Form(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """并行友好地保存会话附件；不在上传请求中执行解析、OCR 或视觉调用。"""

    content = await file.read()
    attachment = await run_in_threadpool(
        _require_attachment_service().upload_file,
        user_id=user_id,
        session_id=session_id,
        filename=file.filename or "upload.bin",
        content=content,
        mime_type=file.content_type or "",
    )
    return {"ok": True, "attachment": attachment}


@router.get("/agent/attachments/raw")
async def get_agent_attachment_raw(
    uri: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
) -> FileResponse:
    """按完整 session-upload URI 返回对应附件原文件。"""

    try:
        path, mime_type, filename = _require_attachment_service().get_attachment_file_by_uri(uri=uri)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=mime_type or None,
        filename=filename,
        content_disposition_type="inline",
    )


@router.delete("/agent/attachments/{attachment_id}")
async def delete_agent_attachment(
    attachment_id: str,
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
) -> dict[str, Any]:
    """Delete a session attachment and its runtime files."""

    deleted = _require_attachment_service().delete_attachment(
        user_id=user_id,
        session_id=session_id,
        attachment_id=attachment_id,
    )
    return {"ok": deleted, "deleted": deleted, "attachment_id": attachment_id}


@router.get("/agent/attachments/{attachment_id}")
async def get_agent_attachment(
    attachment_id: str,
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
) -> dict[str, Any]:
    """返回单个会话附件的上传或按需解析状态。"""

    try:
        attachment = _require_attachment_service().get_attachment(
            user_id=user_id,
            session_id=session_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "attachment": attachment}


@router.options("/agent/tools")
async def agent_tools_options() -> Response:
    """允许工具注册表跨源 fallback 请求的浏览器预检通过。"""

    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


def _to_sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """将 dict 事件迭代器包装为 SSE 格式字符串,每 3s 发送心跳注释防止连接超时。"""

    _queue: queue.Queue[tuple[str, Any] | None] = queue.Queue()
    _stopped = threading.Event()

    def _pump_events() -> None:
        try:
            for payload in events:
                _queue.put(("data", payload))
            _queue.put(("done", None))
        except GeneratorExit:
            pass
        finally:
            _stopped.set()

    def _pump_heartbeats() -> None:
        while not _stopped.wait(timeout=DEFAULT_BUSINESS_LIMITS.agent_sse_heartbeat_seconds):
            try:
                _queue.put_nowait(("heartbeat", None))  # type: ignore[arg-type]
            except queue.Full:
                pass

    _event_thread = threading.Thread(target=_pump_events, daemon=True)
    _heartbeat_thread = threading.Thread(target=_pump_heartbeats, daemon=True)
    _event_thread.start()
    _heartbeat_thread.start()

    try:
        while True:
            try:
                item = _queue.get(timeout=DEFAULT_BUSINESS_LIMITS.agent_sse_queue_poll_seconds)
            except queue.Empty:
                if _stopped.is_set():
                    break
                continue
            if item is None:
                continue
            kind, payload = item
            if kind == "done":
                break
            if kind == "heartbeat":
                yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    except GeneratorExit:
        _stopped.set()
        raise


# ------------------------------------------------------------------
# 流式对话
# ------------------------------------------------------------------


def _build_agent_stream_response(
    *,
    prompt: str,
    user_id: str,
    session_id: str,
    reference: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    message_metadata: dict[str, Any] | None = None,
    agent_mode: str | None = None,
    agent_access_mode: str | None = None,
) -> StreamingResponse:
    """创建带会话上下文的 Agent SSE 响应。"""

    agent = _require_agent()
    try:
        _ws_cfg = _require_settings_service().get_web_search_config(user_id=user_id)
        ws_max_results = (
            _ws_cfg.get(
                "web_search_max_results",
                DEFAULT_BUSINESS_LIMITS.default_web_search_max_results,
            )
            or DEFAULT_BUSINESS_LIMITS.default_web_search_max_results
        )
    except Exception:
        ws_max_results = DEFAULT_BUSINESS_LIMITS.default_web_search_max_results

    def _event_generator():
        try:
            yield from _to_sse(
                agent.stream_session_prompt(
                    prompt=prompt,
                    user_id=user_id,
                    session_id=session_id,
                    reference=reference,
                    attachments=attachments,
                    user_message_metadata=message_metadata,
                    agent_mode=agent_mode or "auto",
                    agent_access_mode=agent_access_mode or "sandbox",
                    web_search_max_results=ws_max_results,
                )
            )
        except Exception:
            logger.exception("SSE 流式对话异常 | user=%s session=%s", user_id, session_id)
            yield f"data: {json.dumps({'error': 'internal server error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/agent/stream")
async def agent_stream(
    prompt: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户输入"),
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="会话 ID"),
    reference: str | None = Query(default=None, description="用户引用的文本"),
    agent_mode: str = Query(default="auto", description="Agent Loop 模式: auto/simple/react/plan"),
    agent_access_mode: str = Query(default="sandbox", description="Agent 权限模式: readonly/sandbox/full_access"),
) -> StreamingResponse:
    """
    SSE 流式对话接口(带 session 上下文)。

    事件流格式: data: <json>\\n\\n, 以 data: [DONE]\\n\\n 结束。
    """
    return _build_agent_stream_response(
        prompt=prompt,
        user_id=user_id,
        session_id=session_id,
        reference=reference,
        agent_mode=agent_mode,
        agent_access_mode=agent_access_mode,
    )


@router.post("/agent/stream")
async def agent_stream_post(
    prompt: str = Body(..., embed=True, min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    user_id: str = Body(..., embed=True, min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    session_id: str = Body(..., embed=True, min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    reference: str | None = Body(default=None, embed=True),
    attachments: list[dict[str, Any]] | None = Body(default=None, embed=True),
    message_metadata: dict[str, Any] | None = Body(default=None, embed=True),
    agent_mode: str = Body(default="auto", embed=True),
    agent_access_mode: str = Body(default="sandbox", embed=True),
) -> StreamingResponse:
    """通过 JSON body 发起 SSE 对话,避免长引用受 URL 长度限制。"""

    return _build_agent_stream_response(
        prompt=prompt,
        user_id=user_id,
        session_id=session_id,
        reference=reference,
        attachments=attachments,
        message_metadata=message_metadata,
        agent_mode=agent_mode,
        agent_access_mode=agent_access_mode,
    )


@router.get("/agent/stream-run")
async def agent_stream_run(
    prompt: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户输入"),
    user_id: str = Query(default="stream-run-user", description="用户 ID"),
    session_id: str = Query(default="stream-run-session", description="会话 ID"),
) -> StreamingResponse:
    """
    无状态 SSE 流式对话(无上下文,无持久化)。
    """
    agent = _require_agent()

    def _event_generator():
        try:
            yield from _to_sse(
                agent.stream_run(
                    prompt=prompt,
                    user_id=user_id,
                    session_id=session_id,
                )
            )
        except Exception:
            logger.exception("SSE 无状态流式异常 | user=%s session=%s", user_id, session_id)
            yield f"data: {json.dumps({'error': 'internal server error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ------------------------------------------------------------------
# 非流式调用
# ------------------------------------------------------------------


@router.post("/agent/run-once")
async def agent_run_once(
    prompt: str = Body(..., embed=True),
    user_id: str = Body(..., embed=True),
    session_id: str = Body(..., embed=True),
) -> dict[str, Any]:
    """
    无状态单次非流式调用,无长期记忆/知识库召回。
    """
    agent = _require_agent()
    return agent.run_once(prompt=prompt, user_id=user_id, session_id=session_id)


@router.post("/agent/run")
async def agent_run_session(
    prompt: str = Body(..., embed=True),
    user_id: str = Body(..., embed=True),
    session_id: str = Body(..., embed=True),
) -> dict[str, Any]:
    """
    带 session 上下文的非流式调用,返回完整结构化结果。
    """
    agent = _require_agent()
    return agent.run_session_prompt(prompt=prompt, user_id=user_id, session_id=session_id)


# ------------------------------------------------------------------
# 取消执行
# ------------------------------------------------------------------


@router.post("/agent/cancel")
async def agent_cancel(
    session_id: str = Body(..., embed=True),
) -> dict[str, Any]:
    """
    取消指定 session 正在执行的图,中断后部分输出自动保存。
    """
    agent = _require_agent()
    agent.cancel_session(session_id)
    return {"ok": True}


@router.get("/agent/children")
async def agent_children(
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="主 Agent 会话 ID"),
) -> dict[str, Any]:
    """读取指定会话内子 Agent 的目标、权限、状态和结果。"""

    agent = _require_agent()
    return {"session_id": session_id, "children": agent.list_child_agents_for_session(session_id)}


@router.post("/agent/children/{run_id}/stop")
async def stop_child_agent(run_id: str) -> dict[str, Any]:
    """向指定子 Agent 发送停止信号。"""

    agent = _require_agent()
    return {"run_id": run_id, "ok": agent.stop_child_agent(run_id)}


@router.post("/agent/children/{run_id}/update")
async def update_child_agent(run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """向指定子 Agent 下一次安全检查点投递上下文更新。"""

    agent = _require_agent()
    agent.update_child_agent(run_id, body)
    return {"run_id": run_id, "ok": True}


@router.post("/agent/children/{run_id}/claim-wakeup")
async def claim_child_agent_wakeup(
    run_id: str,
    user_id: str = Body(..., embed=True),
    session_id: str = Body(..., embed=True),
) -> dict[str, Any]:
    """原子领取子 Agent 当前 Turn 的自动唤醒，阻止多窗口重复触发。"""

    try:
        claimed = _require_agent().claim_child_agent_completion_wakeup(
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
        )
        return {"run_id": run_id, "claimed": claimed}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/agent/children/{run_id}/dsh-web")
async def get_child_agent_dsh_web(
    run_id: str,
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="主 Agent 会话 ID"),
) -> dict[str, str]:
    """返回当前用户 DSH子 Agent对应的同进程只读 Web地址。"""

    try:
        session = _require_session_service().get_session(session_id)
        if session is None or session.user_id != user_id:
            raise PermissionError("不能查看其他用户的 DSH 子 Agent")
        child = next(
            (item for item in _require_agent().list_child_agents_for_session(session_id) if item.get("run_id") == run_id),
            None,
        )
        if child is None:
            raise KeyError("DSH 子 Agent不存在")
        # DSH 启动期间 ``ensure_web`` 会等待执行器发布本地 Web 地址；必须放到
        # 服务线程池，避免该等待占住 FastAPI 事件循环并拖死子 Agent 状态轮询。
        url = await run_in_threadpool(
            _require_dsh_executor().ensure_web,
            child={**child, "session_id": session_id},
            user_id=user_id,
        )
        return {"run_id": run_id, "url": url}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ------------------------------------------------------------------
# 观测 / trace 事件
# ------------------------------------------------------------------


@router.get("/agent/events")
async def agent_events(
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="会话 ID"),
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """
    获取指定会话的最新执行 trace 事件,供前端观测面板使用。

    从消息表中提取带有 node 信息的 metadata_json,按时间序排列。
    """
    ms = _require_message_service()
    messages = ms.list_session_messages(
        user_id=user_id,
        session_id=session_id,
        limit=DEFAULT_BUSINESS_LIMITS.api_large_list_limit,
    )

    events: list[dict[str, Any]] = []
    for m in messages:
        meta = m.metadata_json or {}
        node_name = meta.get("node", "")
        if not node_name:
            continue
        event = {
            "message_id": m.message_id,
            "role": m.role,
            "node": node_name,
                "content": (
                    m.content[:DEFAULT_BUSINESS_LIMITS.agent_event_content_preview_chars]
                    if m.role in ("assistant", "tool", "system")
                    else ""
                ),
            "tool_calls": m.tool_calls_json,
            "created_at": m.created_at.isoformat(),
            "metadata": meta,
        }
        events.append(event)

    return {
        "session_id": session_id,
        "user_id": user_id,
        "event_count": len(events),
        "events": events,
    }


@router.get("/agent/recall-details")
async def agent_recall_details(
    session_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="会话 ID"),
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """
    获取指定会话最近一次真实召回快照,供 Obs 面板展示 ReRank 前后条目。

    数据来源是 ContextBuilder 构建的 system message metadata,其中包含真实的
    pre_rerank / post_rerank 明细,而不是前端二次推断的索引摘要。
    """

    return build_recall_details_payload(
        agent=_require_agent(),
        message_service=_require_message_service(),
        user_id=user_id,
        session_id=session_id,
    )


@router.post("/agent/task-suggestions")
async def agent_task_suggestions(
    user_id: str = Body(..., embed=True, min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    session_id: str = Body(..., embed=True, min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
) -> dict[str, Any]:
    """Generate three likely next user tasks from the current session context."""

    logger.info("生成 Agent 任务推荐 | user=%s session=%s", user_id, session_id)
    service = TaskSuggestionService(
        agent=_require_agent(),
        message_service=_require_message_service(),
    )
    payload = service.generate_suggestions(user_id=user_id, session_id=session_id)
    logger.info(
        "Agent 任务推荐生成完成 | user=%s session=%s count=%s",
        user_id,
        session_id,
        len(payload.get("suggestions", [])),
    )
    return payload
