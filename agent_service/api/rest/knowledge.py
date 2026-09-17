"""用户知识库 REST 端点。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue
import re
import threading
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - fallback only used when optional dependency is absent.
    FileSystemEvent = Any  # type: ignore[misc, assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None  # type: ignore[assignment]

from agent_service.api.rest.deps import (
    _require_knowledge_graph_service,
    _require_knowledge_graph_queue_service,
    _require_knowledge_library_service,
    _require_latex_service,
    _require_knowledge_ingestion_job_service,
    _require_activity_service,
    _require_retrieval_service,
    _require_settings_service,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/knowledge/ingestion/jobs")
async def create_knowledge_ingestion_jobs(body: dict[str, Any]) -> dict[str, Any]:
    """为一组知识库文件创建可持久化、可独立中止的入库任务。"""

    user_id = str(body.get("user_id") or "").strip()
    paths = body.get("paths")
    if not user_id or not isinstance(paths, list) or not paths:
        raise HTTPException(status_code=422, detail="user_id and non-empty paths are required")
    try:
        jobs = await run_in_threadpool(
            _require_knowledge_ingestion_job_service().submit,
            user_id=user_id,
            paths=[str(path) for path in paths],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"jobs": jobs}


@router.get("/knowledge/ingestion/jobs")
async def list_knowledge_ingestion_jobs(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    active_only: bool = Query(False, description="是否只返回等待、运行和中止中的任务"),
) -> dict[str, Any]:
    """列出用户持久化入库任务，供队列页面轮询恢复。"""

    jobs = await run_in_threadpool(
        _require_knowledge_ingestion_job_service().list_jobs,
        user_id=user_id,
        active_only=active_only,
    )
    return {"jobs": jobs}


@router.post("/knowledge/ingestion/jobs/{job_id}/cancel")
async def cancel_knowledge_ingestion_job(job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """立即中止一个等待中或运行中的单文件入库任务。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    job = await run_in_threadpool(
        _require_knowledge_ingestion_job_service().cancel,
        job_id=job_id,
        user_id=user_id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="ingestion job not found")
    return job


class _KnowledgeFileEventHandler(FileSystemEventHandler):
    """
    watchdog 文件事件桥接器。

    root: 当前监听的知识库根目录。
    loop: FastAPI 当前事件循环。
    queue: 跨线程投递给 SSE 生成器的事件队列。
    """

    def __init__(
        self,
        *,
        root: Path,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[str],
        service: Any,
        user_id: str,
    ) -> None:
        """保存 watcher 事件投递所需上下文。"""

        self.root = root
        self.loop = loop
        self.queue = queue
        self.service = service
        self.user_id = user_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        """将 watchdog 线程中的文件变化投递到 asyncio 队列。"""

        if event.event_type in {"opened", "closed_no_write"}:
            return
        raw_paths = [
            str(getattr(event, "src_path", "") or ""),
            str(getattr(event, "dest_path", "") or ""),
        ]
        relative_paths: list[str] = []
        for raw_path in raw_paths:
            if not raw_path:
                continue
            with contextlib.suppress(ValueError):
                relative_path = Path(raw_path).resolve().relative_to(self.root).as_posix()
                if relative_path:
                    relative_paths.append(relative_path)
        if not relative_paths:
            return
        try:
            self.service.invalidate_paths(
                user_id=self.user_id,
                relative_paths=list(dict.fromkeys(relative_paths)),
            )
        except Exception:
            logger.exception(
                "外部文件变化索引失效失败 | user=%s paths=%s",
                self.user_id,
                relative_paths,
            )
        relative_path = relative_paths[-1]
        self.loop.call_soon_threadsafe(self.queue.put_nowait, relative_path)


@router.get("/knowledge/files")
async def list_knowledge_files(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """列出当前 active 知识库的递归文件树。"""

    svc = _require_knowledge_library_service()
    try:
        tree = await run_in_threadpool(svc.list_files, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tree": tree}


@router.get("/knowledge/files/content")
async def get_knowledge_file_content(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="知识库内相对路径"),
) -> dict[str, Any]:
    """读取当前 active 知识库中的文本文件。"""

    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.read_file, user_id=user_id, path=path)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="file is not valid UTF-8 text") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/files/preview")
async def preview_knowledge_file(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="知识库内相对路径"),
) -> dict[str, Any]:
    """读取当前 active 知识库中文件的多模态预览数据。"""

    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.preview_file, user_id=user_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/files/pdf-page")
async def preview_knowledge_pdf_page(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="知识库内 PDF 相对路径"),
    page: int = Query(..., ge=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="从 1 开始的 PDF 页码"),
) -> FileResponse:
    """按需栅格化并返回 Preview1 当前需要显示的 PDF 页面。"""

    svc = _require_knowledge_library_service()
    try:
        file_path, media_type = await run_in_threadpool(
            svc.render_pdf_page,
            user_id=user_id,
            path=path,
            page=page,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(file_path, media_type=media_type, content_disposition_type="inline")


@router.post("/knowledge/latex/compile")
async def compile_latex_file(body: dict[str, Any]) -> dict[str, Any]:
    """保存完成后编译知识库 `.tex`，返回日志、错误位置和现有 PDF 预览数据。"""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    try:
        return await run_in_threadpool(
            _require_latex_service().compile_file,
            user_id=user_id,
            path=path,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/files/raw")
async def raw_knowledge_file(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="知识库内相对路径"),
    download: bool = Query(False, description="是否以附件方式下载"),
) -> FileResponse:
    """返回当前 active 知识库中文件的原始字节流,用于 PDF 等 iframe 预览。"""

    svc = _require_knowledge_library_service()
    try:
        file_path, media_type = await run_in_threadpool(
            svc.resolve_file_for_raw_response,
            user_id=user_id,
            path=path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/knowledge/assets/{path:path}")
async def knowledge_preview_asset(path: str) -> FileResponse:
    """返回 PDF 等多模态预览阶段导出的临时图片资产。"""

    svc = _require_knowledge_library_service()
    try:
        file_path, media_type = await run_in_threadpool(
            svc.resolve_knowledge_asset_for_response,
            path=path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type="inline",
    )


@router.post("/knowledge/files/content")
async def write_knowledge_file(body: dict[str, Any]) -> dict[str, Any]:
    """
    保存当前 active 知识库中的文本文件。

    保存只写入磁盘并触发文件树刷新;不会执行灌库。
    """

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    content = str(body.get("content") or "")
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.write_file, user_id=user_id, path=path, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge/files/file")
async def create_knowledge_file(body: dict[str, Any]) -> dict[str, Any]:
    """在当前 active 知识库中新建文本文件。"""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    content = str(body.get("content") or "")
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.create_file, user_id=user_id, path=path, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge/files/folder")
async def create_knowledge_folder(body: dict[str, Any]) -> dict[str, Any]:
    """在当前 active 知识库中新建文件夹。"""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.create_folder, user_id=user_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/knowledge/files")
async def delete_knowledge_path(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="知识库内相对路径"),
) -> dict[str, Any]:
    """删除当前 active 知识库中的文件或文件夹。"""

    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.delete_path, user_id=user_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"无权限删除: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除文件时发生系统错误: {exc}") from exc


@router.get("/knowledge/files/trash")
async def list_knowledge_trash(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="鐢ㄦ埛 ID")) -> dict[str, Any]:
    """List files moved into the current active knowledge-library trash."""

    svc = _require_knowledge_library_service()
    try:
        entries = await run_in_threadpool(svc.list_deleted_paths, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"entries": entries}


@router.post("/knowledge/files/trash/{trash_id}/restore")
async def restore_knowledge_trash_entry(trash_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Restore one file or directory from the current active knowledge-library trash."""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.restore_deleted_path, user_id=user_id, trash_id=trash_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"restore failed: {exc}") from exc


@router.delete("/knowledge/files/trash/{trash_id}")
async def delete_knowledge_trash_entry(
    trash_id: str,
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="鐢ㄦ埛 ID"),
) -> dict[str, Any]:
    """Permanently delete one entry from the current active knowledge-library trash."""

    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(svc.delete_trash_entry, user_id=user_id, trash_id=trash_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"permanent delete failed: {exc}") from exc


@router.post("/knowledge/files/copy")
async def copy_knowledge_path(body: dict[str, Any]) -> dict[str, Any]:
    """复制当前 active 知识库中的文件/文件夹。"""

    user_id = str(body.get("user_id") or "").strip()
    source_path = str(body.get("source_path") or "").strip()
    target_path = str(body.get("target_path") or "").strip()
    if not user_id or not source_path or not target_path:
        raise HTTPException(status_code=422, detail="user_id, source_path and target_path are required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(
            svc.copy_path,
            user_id=user_id,
            source_path=source_path,
            target_path=target_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge/files/rename")
async def rename_knowledge_path(body: dict[str, Any]) -> dict[str, Any]:
    """移动或重命名当前 active 知识库中的文件/文件夹。"""

    user_id = str(body.get("user_id") or "").strip()
    source_path = str(body.get("source_path") or "").strip()
    target_path = str(body.get("target_path") or "").strip()
    if not user_id or not source_path or not target_path:
        raise HTTPException(status_code=422, detail="user_id, source_path and target_path are required")
    svc = _require_knowledge_library_service()
    try:
        return await run_in_threadpool(
            svc.rename_path,
            user_id=user_id,
            source_path=source_path,
            target_path=target_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge/rebuild")
async def rebuild_knowledge(body: dict[str, Any]) -> dict[str, Any]:
    """
    重新扫描用户知识库并灌入向量库。

    body: user_id 必填,knowledge_dir 可选;传入 knowledge_dir 时会同步更新用户设置。
    """

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    knowledge_dir = body.get("knowledge_dir")
    svc = _require_knowledge_library_service()
    try:
        result = await run_in_threadpool(
            svc.rebuild_user_knowledge,
            user_id=user_id,
            knowledge_dir=str(knowledge_dir) if knowledge_dir else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/knowledge/rebuild/stream")
async def rebuild_knowledge_stream(body: dict[str, Any]) -> StreamingResponse:
    """Stream rebuild progress events while the blocking ingestion job runs."""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    knowledge_dir = body.get("knowledge_dir")
    svc = _require_knowledge_library_service()

    def run_job(progress_callback: Any) -> dict[str, Any]:
        result = svc.rebuild_user_knowledge(
            user_id=user_id,
            knowledge_dir=str(knowledge_dir) if knowledge_dir else None,
            progress_callback=progress_callback,
        )
        return result.to_dict()

    return StreamingResponse(_run_progress_job_stream(run_job), media_type="text/event-stream")


@router.post("/knowledge/files/upload")
async def upload_knowledge_file(
    user_id: Annotated[str, Form(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")],
    file: Annotated[UploadFile, File(description="知识库文件")],
    relative_dir: Annotated[str, Form(description="知识库内目标子目录")] = "",
    auto_ingest: Annotated[bool | None, Form(description="是否上传后自动灌库;为空时使用用户设置")] = None,
    conflict_strategy: Annotated[str, Form(description="同名冲突策略: overwrite / skip / rename")] = "overwrite",
) -> dict[str, Any]:
    """
    上传文件到用户知识库目录。默认只落盘,不灌库。

    user_id: 用户 ID。
    file: 上传文件。
    relative_dir: 可选目标子目录,必须位于用户知识库根目录内。
    auto_ingest: 为 true 时只灌库本次上传的单个文件;为空时读取用户设置。
    conflict_strategy: 同名文件处理策略。
    """

    svc = _require_knowledge_library_service()
    content = await file.read()
    try:
        uploaded_path = await run_in_threadpool(
            svc.write_uploaded_file,
            user_id=user_id,
            filename=file.filename or "",
            content=content,
            relative_dir=relative_dir,
            conflict_strategy=conflict_strategy,
        )
        should_ingest = bool(auto_ingest) if auto_ingest is not None else await run_in_threadpool(
            svc.should_auto_ingest_on_upload,
            user_id=user_id,
        )
        if should_ingest:
            result = await run_in_threadpool(
                svc.ingest_single_file,
                user_id=user_id,
                path=uploaded_path.relative_to(svc.get_active_root_path(user_id=user_id)).as_posix(),
            )
        else:
            result = await run_in_threadpool(
                svc.build_upload_only_result,
                user_id=user_id,
                uploaded_path=str(uploaded_path),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    relative_path = uploaded_path.relative_to(svc.get_active_root_path(user_id=user_id)).as_posix()
    await run_in_threadpool(
        _require_activity_service().record_event,
        user_id=user_id,
        module="documents",
        action="file_imported",
        score=1,
        object_id=relative_path,
        title="上传文件",
    )
    if should_ingest:
        await run_in_threadpool(
            _require_activity_service().record_event,
            user_id=user_id,
            module="knowledge",
            action="knowledge_ingested",
            score=1,
            object_id=relative_path,
            title="完成知识入库",
            dedupe_minutes=DEFAULT_BUSINESS_LIMITS.knowledge_activity_dedupe_minutes,
        )
    return result.to_dict()


@router.post("/knowledge/files/ingest")
async def ingest_knowledge_file(body: dict[str, Any]) -> dict[str, Any]:
    """只灌库当前 active 知识库中的单个文件。"""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()
    try:
        result = await run_in_threadpool(svc.ingest_single_file, user_id=user_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/knowledge/files/ingest/stream")
async def ingest_knowledge_file_stream(body: dict[str, Any]) -> StreamingResponse:
    """Stream single-file ingestion progress events."""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()

    def run_job(progress_callback: Any) -> dict[str, Any]:
        result = svc.ingest_single_file(user_id=user_id, path=path, progress_callback=progress_callback)
        return result.to_dict()

    return StreamingResponse(_run_progress_job_stream(run_job), media_type="text/event-stream")


@router.post("/knowledge/files/ingest-path")
async def ingest_knowledge_path(body: dict[str, Any]) -> dict[str, Any]:
    """灌库文件或文件夹:文件直接灌库,文件夹递归灌入其下所有支持的文件。"""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()
    try:
        result = await run_in_threadpool(svc.ingest_path, user_id=user_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/knowledge/files/ingest-path/stream")
async def ingest_knowledge_path_stream(body: dict[str, Any]) -> StreamingResponse:
    """Stream file-or-folder ingestion progress events."""

    user_id = str(body.get("user_id") or "").strip()
    path = str(body.get("path") or "").strip()
    if not user_id or not path:
        raise HTTPException(status_code=422, detail="user_id and path are required")
    svc = _require_knowledge_library_service()

    def run_job(progress_callback: Any) -> dict[str, Any]:
        result = svc.ingest_path(user_id=user_id, path=path, progress_callback=progress_callback)
        return result.to_dict()

    return StreamingResponse(_run_progress_job_stream(run_job), media_type="text/event-stream")


@router.get("/knowledge/search")
async def search_knowledge(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    query: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="搜索关键词"),
    fulltext: bool = Query(default=True, description="是否启用全文内容搜索"),
    semantic: bool = Query(default=False, description="是否启用语义搜索"),
) -> dict[str, Any]:
    """
    知识库联合搜索：文件名匹配 + (可选)全文内容匹配 + (可选)语义搜索。
    """

    lib_svc = _require_knowledge_library_service()
    retrieval_svc = _require_retrieval_service()
    top_k = retrieval_svc.config.memory.knowledge_search_semantic_top_k
    from os import path as _os_path
    library_root = str(await run_in_threadpool(lib_svc.get_active_root_path, user_id=user_id))

    def _is_in_library(uri: str) -> bool:
        """检查 source_uri 是否属于当前 active 知识库,防止串库。"""
        if not uri:
            return False
        try:
            normalized_uri = _os_path.normcase(_os_path.normpath(uri))
            normalized_root = _os_path.normcase(_os_path.normpath(library_root))
            return normalized_uri.startswith(normalized_root + _os_path.sep) or normalized_uri == normalized_root
        except (ValueError, TypeError):
            return False

    async def _filename_search() -> list[dict[str, str]]:
        tree = await run_in_threadpool(lib_svc.list_files, user_id=user_id)

        def _search_nodes(nodes: list[dict], results: list[dict]) -> None:
            for node in nodes:
                name = str(node.get("name", "") or "")
                if query.lower() in name.lower():
                    results.append({"path": str(node.get("path", "") or ""), "name": name})
                children = node.get("children")
                if isinstance(children, list):
                    _search_nodes(children, results)

        results: list[dict] = []
        _search_nodes(tree, results)
        return results

    async def _fulltext_search() -> list[dict[str, Any]]:
        indexed = await run_in_threadpool(
            retrieval_svc.memory_service.search_knowledge_content,
            query=query,
            user_id=user_id,
        )
        disk_matches = await run_in_threadpool(
            lib_svc.search_file_contents,
            user_id=user_id,
            query=query,
        )
        seen_paths: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in [*indexed, *disk_matches]:
            uri = str(item.get("source_uri") or "")
            if not _is_in_library(uri):
                continue
            normalized_uri = _os_path.normcase(_os_path.normpath(uri))
            if normalized_uri in seen_paths:
                continue
            seen_paths.add(normalized_uri)
            deduped.append(item)
        return deduped

    async def _semantic_search() -> list[dict[str, Any]]:
        items = await run_in_threadpool(
            retrieval_svc.retrieve_knowledge,
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
        from agent_service.services.memory.retrieval_service import MemoryRetrievalService
        seen_names: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            uri = str(item.memory.source_uri or "")
            if not _is_in_library(uri):
                continue
            name = _os_path.basename(uri)
            if name in seen_names:
                continue
            seen_names.add(name)
            deduped.append(MemoryRetrievalService.serialize_retrieved_memory(item))
        return deduped

    filename_task = _filename_search()
    fulltext_task = _fulltext_search() if fulltext else None
    semantic_task = _semantic_search() if semantic else None

    filename_results = await filename_task
    fulltext_results = await fulltext_task if fulltext_task else []
    semantic_results = await semantic_task if semantic_task else []
    return {
        "filename_results": filename_results,
        "fulltext_results": fulltext_results,
        "semantic_results": semantic_results,
    }


@router.get("/knowledge/graph")
async def get_knowledge_graph(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
    limit: int | None = Query(
        default=None,
        ge=DEFAULT_BUSINESS_LIMITS.graph_min_node_limit,
        le=DEFAULT_BUSINESS_LIMITS.graph_max_node_limit,
        description="返回节点上限,不传则使用用户配置",
    ),
) -> dict[str, Any]:
    """返回当前 active 知识库的知识图谱点边数据。"""

    settings_svc = _require_settings_service()
    graph_svc = _require_knowledge_graph_service()
    try:
        profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        if limit is None:
            limit = profile.get(
                "graph_node_limit",
                DEFAULT_BUSINESS_LIMITS.graph_default_node_limit,
            )
        return await run_in_threadpool(
            graph_svc.get_graph,
            user_id=str(profile["user_id"]),
            library_id=str(active_library["library_id"]),
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/knowledge/graph/nodes/{node_id}")
async def delete_knowledge_graph_entity(
    node_id: str,
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """Delete one entity node and all of its incident graph edges."""

    settings_svc = _require_settings_service()
    graph_svc = _require_knowledge_graph_service()
    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    try:
        result = await run_in_threadpool(
            graph_svc.delete_entity_node,
            user_id=str(profile["user_id"]),
            library_id=str(active_library["library_id"]),
            node_id=node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.post("/knowledge/graph/nodes/{node_id}/clear")
async def clear_knowledge_graph_document(node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Delete one document's contributed entity graph while retaining the document node."""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    settings_svc = _require_settings_service()
    graph_svc = _require_knowledge_graph_service()
    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    try:
        result = await run_in_threadpool(
            graph_svc.clear_document_children,
            user_id=str(profile["user_id"]),
            library_id=str(active_library["library_id"]),
            node_id=node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **result}


from agent_service.services.knowledge_graph import (
    KnowledgeGraphService,
    get_dedup_progress,
    _set_dedup_progress,
    get_graph_extraction_progress,
)


@router.post("/knowledge/graph/rebuild")
async def rebuild_knowledge_graph(body: dict[str, Any]) -> dict[str, Any]:
    """
    在后台启动语义知识图谱重建。
    使用统一 ingestion_hash 和章节缓存增量处理，已抽取且未变更的内容自动跳过。
    """
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    settings_svc = _require_settings_service()
    config = settings_svc.config if hasattr(settings_svc, "config") else None
    if config is None:
        from agent_service.core.agent_config import AgentConfig
        config = AgentConfig.load_config(ensure_models=False)

    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    normalized_user_id = str(profile["user_id"])
    library_id = str(active_library["library_id"])
    target_source_path: Path | None = None
    target_is_dir = False
    force_value = body.get("force", False)
    if not isinstance(force_value, bool):
        raise HTTPException(status_code=422, detail="force must be a boolean")
    force = force_value
    target_path = str(body.get("path") or "").replace("\\", "/").strip().strip("/")
    if target_path:
        knowledge_root = Path(str(active_library["knowledge_dir"])).resolve(strict=False)
        candidate_path = (knowledge_root / target_path).resolve(strict=False)
        try:
            candidate_path.relative_to(knowledge_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="path escapes knowledge root") from exc
        if not candidate_path.exists():
            raise HTTPException(status_code=404, detail="target path not found")
        target_source_path = candidate_path
        target_is_dir = candidate_path.is_dir()

    knowledge_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
    frontmatter_dir = knowledge_root / ".mw" / "frontmatter"

    user_llm_config = settings_svc.get_llm_config(user_id=normalized_user_id)

    return _require_knowledge_graph_queue_service().submit(
        config=config,
        user_id=normalized_user_id,
        library_id=library_id,
        frontmatter_dir=frontmatter_dir,
        user_llm_config=user_llm_config,
        target_source_path=target_source_path,
        target_is_dir=target_is_dir,
        target_display_path=target_path,
        force=force,
    )


@router.get("/knowledge/graph/rebuild/status")
async def get_graph_rebuild_status(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """返回当前图谱抽取进度。"""
    settings_svc = _require_settings_service()
    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    normalized_user_id = str(profile["user_id"])
    library_id = str(active_library["library_id"])
    progress = get_graph_extraction_progress(normalized_user_id, library_id)
    result_str = progress.get("result", "")
    result_data = json.loads(result_str) if result_str else None
    docs_raw = progress.get("docs")
    docs = docs_raw if isinstance(docs_raw, list) else []
    return {
        "status": progress.get("status", "idle"),
        "total": progress.get("total", 0),
        "current": progress.get("current", 0),
        "message": progress.get("message", ""),
        "result": result_data,
        "docs": docs,
    }


@router.post("/knowledge/graph/rebuild/cancel")
async def cancel_knowledge_graph_rebuild(body: dict[str, Any]) -> dict[str, Any]:
    """中止当前知识库内一个等待中或运行中的图谱任务。"""

    user_id = str(body.get("user_id") or "").strip()
    target_path = str(body.get("path") or "").replace("\\", "/").strip().strip("/")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    if ".." in target_path.split("/"):
        raise HTTPException(status_code=422, detail="path escapes knowledge root")
    profile = await run_in_threadpool(_require_settings_service().ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    result = _require_knowledge_graph_queue_service().cancel(
        user_id=str(profile["user_id"]),
        library_id=str(active_library["library_id"]),
        identity=target_path or "__all__",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="graph task not found")
    return result


@router.post("/knowledge/graph/dedup")
async def dedup_knowledge_graph(body: dict[str, Any]) -> dict[str, Any]:
    """
    在全量知识库范围内对语义实体进行去重。
    将语义相似的实体合并为同一节点，保留置信度最高的实体。
    在后台线程执行,前端轮询 /knowledge/graph/dedup/status 获取进度。
    """
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    settings_svc = _require_settings_service()
    graph_svc = _require_knowledge_graph_service()
    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    normalized_user_id = str(profile["user_id"])
    library_id = str(active_library["library_id"])

    current_progress = get_dedup_progress(normalized_user_id, library_id)
    if current_progress.get("status") == "running":
        return {"status": "already_running", "message": "全库去重已在执行中"}

    _set_dedup_progress(normalized_user_id, library_id, "pending", 0, 0, "排队中…", 0)
    user_llm_config = settings_svc.get_llm_config(user_id=normalized_user_id)

    def _run_dedup() -> None:
        try:
            graph_svc.full_dedup_library(
                user_id=normalized_user_id,
                library_id=library_id,
                llm_config=user_llm_config,
            )
        except Exception:
            logger.exception("全库去重失败")
            _set_dedup_progress(normalized_user_id, library_id, "failed", 0, 0, "去重失败,请查看后端日志", 0)

    thread = threading.Thread(target=_run_dedup, daemon=True)
    thread.start()
    return {"status": "started", "message": "全库去重已在后台启动"}


@router.get("/knowledge/graph/dedup/status")
async def get_dedup_status(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """返回全库去重进度。"""
    settings_svc = _require_settings_service()
    profile = await run_in_threadpool(settings_svc.ensure_user_profile, user_id=user_id)
    active_library = dict(profile["active_knowledge_library"])
    normalized_user_id = str(profile["user_id"])
    library_id = str(active_library["library_id"])
    progress = get_dedup_progress(normalized_user_id, library_id)
    return {
        "status": progress.get("status", "idle"),
        "total": progress.get("total", 0),
        "current": progress.get("current", 0),
        "message": progress.get("message", ""),
        "merged_count": progress.get("merged_count", 0),
    }


@router.get("/knowledge/files/events")
async def stream_knowledge_file_events(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> StreamingResponse:
    """
    推送当前 active 知识库文件变化事件。

    事件只用于前端刷新文件树;不会触发向量灌库。
    """

    svc = _require_knowledge_library_service()

    async def event_stream():
        if Observer is not None:
            async for event in _watchdog_event_stream(svc=svc, user_id=user_id):
                yield event
            return
        async for event in _polling_event_stream(svc=svc, user_id=user_id):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _watchdog_event_stream(*, svc: Any, user_id: str):
    """
    使用 watchdog 监听知识库文件变化并生成 SSE。

    user_id: 用户 ID。
    """

    root = await run_in_threadpool(svc.get_active_root_path, user_id=user_id)
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    observer = Observer()
    observer.schedule(
        _KnowledgeFileEventHandler(
            root=root,
            loop=loop,
            queue=queue,
            service=svc,
            user_id=user_id,
        ),
        str(root),
        recursive=True,
    )
    observer.start()
    yield _sse("ready", {"type": "ready"})
    try:
        while True:
            try:
                path = await asyncio.wait_for(
                    queue.get(),
                    timeout=DEFAULT_BUSINESS_LIMITS.knowledge_file_wait_timeout_seconds,
                )
            except asyncio.TimeoutError:
                yield _sse("heartbeat", {"type": "heartbeat"})
                continue
            await asyncio.sleep(DEFAULT_BUSINESS_LIMITS.knowledge_file_debounce_seconds)
            while not queue.empty():
                path = queue.get_nowait()
            yield _sse("tree_dirty", {"type": "tree_dirty", "path": path})
    finally:
        observer.stop()
        await run_in_threadpool(observer.join, 2)


async def _polling_event_stream(*, svc: Any, user_id: str):
    """
    watchdog 不可用时的签名轮询 fallback。

    user_id: 用户 ID。
    """

    previous_signature = await run_in_threadpool(svc.build_tree_signature, user_id=user_id)
    yield _sse("ready", {"type": "ready"})
    while True:
        await asyncio.sleep(1.5)
        current_signature = await run_in_threadpool(svc.build_tree_signature, user_id=user_id)
        if current_signature == previous_signature:
            continue
        changed_paths = sorted(
            path
            for path in set(previous_signature) | set(current_signature)
            if previous_signature.get(path) != current_signature.get(path)
        )
        if changed_paths:
            await run_in_threadpool(
                svc.invalidate_paths,
                user_id=user_id,
                relative_paths=changed_paths,
            )
        previous_signature = current_signature
        yield _sse("tree_dirty", {"type": "tree_dirty", "path": ""})


async def _run_progress_job_stream(run_job: Any):
    """Run a blocking job in a thread and stream progress callback payloads."""

    progress_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def emit(payload: dict[str, Any]) -> None:
        progress_queue.put({"type": "progress", **payload})

    def worker() -> None:
        try:
            result = run_job(emit)
            progress_queue.put({"type": "done", "result": result})
        except Exception as exc:
            progress_queue.put({"type": "error", "message": str(exc)})
        finally:
            progress_queue.put(None)

    threading.Thread(target=worker, daemon=True).start()
    yield _sse("progress", {"type": "started"})
    while True:
        payload = await asyncio.to_thread(progress_queue.get)
        if payload is None:
            break
        event_name = str(payload.get("type") or "progress")
        yield _sse(event_name, payload)


def _sse(event: str, payload: dict[str, Any]) -> str:
    """序列化 Server-Sent Events 消息。"""

    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
