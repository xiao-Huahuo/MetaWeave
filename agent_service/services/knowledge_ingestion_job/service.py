"""
持久化、执行并取消单文件知识库入库任务。

功能说明:
- 每个文件形成独立数据库任务并按队列顺序执行。
- 实际灌库运行在独立进程中，取消时可以立即终止阻塞中的 OCR 或模型推理。
- 子进程只通过消息队列返回进度，主进程负责持久化和取消后的索引清理。

使用说明:
应用启动时构造服务并调用 start();退出时调用 stop()。
"""

from __future__ import annotations

import json
import multiprocessing
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.models.knowledge_ingestion_job import KnowledgeIngestionJobRecord


ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_JOB_STATUSES = {"cancelled", "finished", "skipped", "failed"}


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(timezone.utc)


def _run_ingestion_worker(user_id: str, path: str, event_queue: Any) -> None:
    """在可强制终止的子进程中重建最小知识库服务并灌库一个文件。"""

    try:
        from agent_service.core.agent_config import AgentConfig
        from agent_service.services.knowledge_graph import KnowledgeGraphService
        from agent_service.services.knowledge_library import KnowledgeLibraryService
        from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
        from agent_service.services.settings.service import SettingsService

        config = AgentConfig.load_config(ensure_models=False)
        memory_service = LongTermMemoryService(config=config)
        settings_service = SettingsService(config=config, memory_service=memory_service)
        library_service = KnowledgeLibraryService(
            config=config,
            memory_service=memory_service,
            settings_service=settings_service,
            knowledge_graph_service=KnowledgeGraphService(config=config),
        )
        result = library_service.ingest_single_file(
            user_id=user_id,
            path=path,
            progress_callback=lambda payload: event_queue.put({"type": "progress", "payload": payload}),
        )
        event_queue.put({"type": "done", "result": result.to_dict()})
    except BaseException as exc:
        event_queue.put({"type": "error", "message": str(exc)})


class KnowledgeIngestionJobService:
    """管理持久化单文件入库队列及其独立工作进程。"""

    _PIPELINES = {
        ".md": "markdown",
        ".txt": "text",
        ".json": "structured",
        ".jsonl": "structured",
        ".html": "html",
        ".htm": "html",
        ".xml": "xml",
        ".csv": "table",
        ".tsv": "table",
        ".xlsx": "spreadsheet",
        ".docx": "document",
        ".pptx": "presentation",
        ".pdf": "pdf",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".webp": "image",
        ".gif": "image",
    }

    def __init__(
        self,
        *,
        engine: Any,
        config: Any,
        knowledge_library_service: Any,
        autostart: bool = True,
    ) -> None:
        """保存依赖、创建任务表，并按配置启动固定数量的调度线程。"""

        self.engine = engine
        self.config = config
        self.limits = getattr(config, "limits", DEFAULT_BUSINESS_LIMITS)
        self.knowledge_library_service = knowledge_library_service
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._submit_lock = threading.Lock()
        self._claim_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._processes: dict[str, multiprocessing.Process] = {}
        self._reconcile_interrupted_jobs()
        if autostart:
            self.start()

    def start(self) -> None:
        """启动固定数量的后台调度线程；重复调用不会创建额外 worker。"""

        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop_event.clear()
        worker_count = max(1, int(self.limits.knowledge_job_worker_count))
        self._threads = [
            threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name=f"knowledge-ingestion-jobs-{index}",
            )
            for index in range(worker_count)
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        """停止调度器并终止仍在运行的文件任务。"""

        self._stop_event.set()
        self._wake_event.set()
        with self._process_lock:
            running_processes = list(self._processes.items())
        for job_id, process in running_processes:
            if process and process.is_alive():
                process.terminate()
                process.join(timeout=self.limits.knowledge_job_process_join_timeout_seconds)
            self._finish_cancelled(job_id=job_id, message="应用关闭，入库任务已中止")
        for thread in self._threads:
            thread.join(timeout=self.limits.knowledge_job_scheduler_join_timeout_seconds)
        self._threads = []

    def submit(self, *, user_id: str, paths: list[str]) -> list[dict[str, Any]]:
        """校验文件并将每个路径持久化为独立等待任务。"""

        root = self.knowledge_library_service.get_active_root_path(user_id=user_id)
        profile_service = getattr(self.knowledge_library_service, "settings_service", None)
        profile = profile_service.ensure_user_profile(user_id=user_id) if profile_service else {}
        library_id = str(dict(profile.get("active_knowledge_library") or {}).get("library_id") or "")
        records: list[KnowledgeIngestionJobRecord] = []
        now = _utc_now()
        for raw_path in dict.fromkeys(paths):
            normalized = str(raw_path or "").replace("\\", "/").strip("/")
            if not normalized:
                continue
            target = (root / normalized).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("path escapes knowledge root") from exc
            if not target.is_file():
                raise ValueError(f"file not found: {normalized}")
            stat = target.stat()
            records.append(KnowledgeIngestionJobRecord(
                job_id=f"ingest_{uuid4().hex}",
                user_id=user_id,
                library_id=library_id,
                path=normalized,
                name=target.name,
                pipeline=self._PIPELINES.get(target.suffix.lower(), "text"),
                size=stat.st_size,
                mtime=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                created_at=now,
                updated_at=now,
            ))
        submitted: list[KnowledgeIngestionJobRecord] = []
        with self._submit_lock, Session(self.engine) as db:
            active_records = db.exec(
                select(KnowledgeIngestionJobRecord).where(
                    KnowledgeIngestionJobRecord.user_id == user_id,
                    KnowledgeIngestionJobRecord.library_id == library_id,
                    KnowledgeIngestionJobRecord.status.in_(ACTIVE_JOB_STATUSES),
                )
            ).all()
            active_by_path = {record.path: record for record in active_records}
            for record in records:
                existing = active_by_path.get(record.path)
                if existing is not None:
                    submitted.append(existing)
                    continue
                db.add(record)
                active_by_path[record.path] = record
                submitted.append(record)
            db.commit()
            for record in submitted:
                db.refresh(record)
        self._wake_event.set()
        return [self._serialize(record) for record in submitted]

    def list_jobs(self, *, user_id: str, active_only: bool = False) -> list[dict[str, Any]]:
        """按创建时间列出用户任务，可只返回活动队列。"""

        with Session(self.engine) as db:
            statement = select(KnowledgeIngestionJobRecord).where(KnowledgeIngestionJobRecord.user_id == user_id)
            if active_only:
                statement = statement.where(KnowledgeIngestionJobRecord.status.in_(ACTIVE_JOB_STATUSES))
            records = db.exec(statement.order_by(KnowledgeIngestionJobRecord.created_at)).all()
            return [self._serialize(record) for record in records]

    def get_job(self, *, job_id: str, user_id: str) -> dict[str, Any] | None:
        """读取指定用户拥有的任务。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            return self._serialize(record) if record and record.user_id == user_id else None

    def apply_progress(self, job_id: str, payload: dict[str, Any]) -> None:
        """把工作进程的详细阶段事件合并进持久化任务。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            if record is None or record.status in TERMINAL_JOB_STATUSES:
                return
            normalized = self._normalize_progress(record.pipeline, payload)
            record.status = "running"
            record.stage = str(normalized.get("stage") or record.stage)
            record.stage_label = str(normalized.get("stage_label") or record.stage_label)
            record.stage_current = max(0, int(normalized.get("stage_current") or 0))
            record.stage_total = max(0, int(normalized.get("stage_total") or 0))
            running_max = self.limits.progress_max_percent - 0.1
            record.progress = max(record.progress, min(running_max, round(float(normalized.get("overall_progress") or 0), 1)))
            record.message = str(normalized.get("message") or record.message)
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()

    def cancel(self, *, job_id: str, user_id: str) -> dict[str, Any] | None:
        """立即取消等待任务，或强制终止当前任务的独立工作进程。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            if record is None or record.user_id != user_id:
                return None
            if record.status in TERMINAL_JOB_STATUSES:
                return self._serialize(record)
            record.cancel_requested = True
            record.status = "cancelling" if record.status == "running" else "cancelled"
            record.stage = "cancelled" if record.status == "cancelled" else "cancelling"
            record.stage_label = "已中止" if record.status == "cancelled" else "正在中止"
            record.progress = 0 if record.status == "cancelled" else record.progress
            record.finished_at = _utc_now() if record.status == "cancelled" else None
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()
            db.refresh(record)
            queued_cancel = record.status == "cancelled"
        if not queued_cancel:
            with self._process_lock:
                process = self._processes.get(job_id)
            if process and process.is_alive():
                process.terminate()
                process.join(timeout=self.limits.knowledge_job_process_join_timeout_seconds)
            self._finish_cancelled(job_id=job_id, message="用户中止灌库")
        else:
            self._cleanup_source(user_id=user_id, path=record.path)
        result = self.get_job(job_id=job_id, user_id=user_id)
        self._wake_event.set()
        return result

    def _scheduler_loop(self) -> None:
        """逐个领取任务；多个固定 worker 共同形成有界并发。"""

        while not self._stop_event.is_set():
            job = self._claim_next()
            if job is None:
                self._wake_event.wait(timeout=self.limits.knowledge_job_poll_seconds)
                self._wake_event.clear()
                continue
            self._run_claimed_job(job)

    def _claim_next(self) -> dict[str, Any] | None:
        """领取最早的等待任务并持久化 running 状态。"""

        with self._claim_lock, Session(self.engine) as db:
            record = db.exec(
                select(KnowledgeIngestionJobRecord)
                .where(KnowledgeIngestionJobRecord.status == "queued")
                .order_by(KnowledgeIngestionJobRecord.created_at)
            ).first()
            if record is None:
                return None
            record.status = "running"
            record.stage = "prepare"
            record.stage_label = "准备文件"
            record.progress = 1
            record.started_at = _utc_now()
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._serialize(record)

    def _run_claimed_job(self, job: dict[str, Any]) -> None:
        """启动单文件工作进程，转发进度并收敛最终状态。"""

        context = multiprocessing.get_context("spawn")
        event_queue = context.Queue()
        process = context.Process(
            target=_run_ingestion_worker,
            args=(job["user_id"], job["path"], event_queue),
            daemon=True,
        )
        job_id = str(job["job_id"])
        with self._process_lock:
            self._processes[job_id] = process
        try:
            process.start()
        except Exception as exc:
            with self._process_lock:
                self._processes.pop(job_id, None)
            event_queue.close()
            self._finish_failed(job_id=job_id, message=f"入库工作进程启动失败: {exc}")
            return
        if self._stop_event.is_set() or self._is_cancel_requested(job_id):
            process.terminate()
        final_event: dict[str, Any] | None = None
        while process.is_alive() and not self._stop_event.is_set():
            final_event = self._drain_worker_events(job_id=job_id, event_queue=event_queue, final=final_event)
            if self._is_cancel_requested(job_id):
                process.terminate()
                break
            time.sleep(self.limits.knowledge_job_process_poll_seconds)
        process.join(timeout=self.limits.knowledge_job_process_join_timeout_seconds)
        final_event = self._drain_worker_events(job_id=job_id, event_queue=event_queue, final=final_event)
        if final_event is None and not self._is_cancel_requested(job_id):
            try:
                event = event_queue.get(timeout=self.limits.knowledge_job_event_wait_seconds)
            except queue.Empty:
                event = None
            if event is not None:
                if event.get("type") == "progress":
                    self.apply_progress(job_id, dict(event.get("payload") or {}))
                else:
                    final_event = event
        with self._process_lock:
            self._processes.pop(job_id, None)
        if self._is_cancel_requested(job_id) or self._stop_event.is_set():
            self._finish_cancelled(job_id=job_id, message="用户中止灌库")
        elif final_event and final_event.get("type") == "done":
            self._finish_success(job_id=job_id, result=dict(final_event.get("result") or {}))
        else:
            message = str((final_event or {}).get("message") or f"入库工作进程异常退出 ({process.exitcode})")
            self._finish_failed(job_id=job_id, message=message)
        event_queue.close()

    def _drain_worker_events(self, *, job_id: str, event_queue: Any, final: dict[str, Any] | None) -> dict[str, Any] | None:
        """非阻塞消费工作进程事件并返回最后一个终态事件。"""

        latest = final
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                break
            if event.get("type") == "progress":
                self.apply_progress(job_id, dict(event.get("payload") or {}))
            else:
                latest = event
        return latest

    def _finish_success(self, *, job_id: str, result: dict[str, Any]) -> None:
        """持久化成功或业务跳过结果。"""

        status = "finished" if int(result.get("files_ingested") or 0) > 0 else "skipped"
        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            if record is None or record.status == "cancelled":
                return
            record.status = status
            record.stage = "completed"
            record.stage_label = "灌库完成" if status == "finished" else "未生成新索引"
            record.progress = 100
            record.message = str(result.get("status_message") or record.stage_label)
            record.result_json = json.dumps(result, ensure_ascii=False)
            record.finished_at = _utc_now()
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()

    def _finish_failed(self, *, job_id: str, message: str) -> None:
        """清理部分索引并持久化失败状态。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            if record is None:
                return
            if record.status == "cancelled" and record.finished_at is not None:
                return
            user_id, path = record.user_id, record.path
            record.status = "failed"
            record.stage = "failed"
            record.stage_label = "灌库失败"
            record.error = message
            record.message = message
            record.finished_at = _utc_now()
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()
        self._cleanup_source(user_id=user_id, path=path)

    def _finish_cancelled(self, *, job_id: str, message: str) -> None:
        """清理部分索引并把任务收敛为 cancelled。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            if record is None:
                return
            user_id, path = record.user_id, record.path
            record.status = "cancelled"
            record.stage = "cancelled"
            record.stage_label = "已中止"
            record.progress = 0
            record.message = message
            record.cancel_requested = True
            record.finished_at = _utc_now()
            record.updated_at = _utc_now()
            db.add(record)
            db.commit()
        self._cleanup_source(user_id=user_id, path=path)

    def _cleanup_source(self, *, user_id: str, path: str) -> None:
        """删除取消或失败任务产生的部分索引，使文件恢复未灌库状态。"""

        self.knowledge_library_service.invalidate_paths(user_id=user_id, relative_paths=[path])

    def _is_cancel_requested(self, job_id: str) -> bool:
        """查询持久化取消标记。"""

        with Session(self.engine) as db:
            record = db.get(KnowledgeIngestionJobRecord, job_id)
            return bool(record is None or record.cancel_requested or record.status == "cancelled")

    def _reconcile_interrupted_jobs(self) -> None:
        """启动时把上次进程崩溃遗留的运行任务恢复到等待队列。"""

        with Session(self.engine) as db:
            records = db.exec(
                select(KnowledgeIngestionJobRecord).where(
                    KnowledgeIngestionJobRecord.status.in_({"running", "cancelling"})
                )
            ).all()
            for record in records:
                record.status = "queued"
                record.stage = "queued"
                record.stage_label = "等待灌库"
                record.progress = 0
                record.cancel_requested = False
                record.started_at = None
                record.updated_at = _utc_now()
                db.add(record)
            if records:
                db.commit()

    @staticmethod
    def _normalize_progress(pipeline: str, payload: dict[str, Any]) -> dict[str, Any]:
        """兼容旧粗粒度事件，并优先保留管线提供的详细阶段数据。"""

        if "overall_progress" in payload:
            return payload
        phase = str(payload.get("phase") or "")
        status = str(payload.get("status") or "")
        if phase == "frontmatter":
            complete = status in {"written", "skipped", "failed"}
            return {
                **payload,
                "stage": "extract",
                "stage_label": "结构化完成" if complete else f"正在解析 {pipeline} 文件",
                "stage_current": 1 if complete else 0,
                "stage_total": 1,
                "overall_progress": 48 if complete else 5,
            }
        if phase == "ingestion":
            complete = status in {"ingested", "skipped", "failed"}
            return {
                **payload,
                "stage": "embedding" if not complete else "commit",
                "stage_label": "正在生成并写入向量" if not complete else "正在提交索引",
                "stage_current": 1 if complete else 0,
                "stage_total": 1,
                "overall_progress": 96 if complete else 55,
            }
        return payload

    @staticmethod
    def _serialize(record: KnowledgeIngestionJobRecord) -> dict[str, Any]:
        """将任务记录转换为 REST、gRPC 和前端共享字典。"""

        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "job_id": record.job_id,
            "user_id": record.user_id,
            "library_id": record.library_id,
            "path": record.path,
            "name": record.name,
            "pipeline": record.pipeline,
            "status": record.status,
            "stage": record.stage,
            "stage_label": record.stage_label,
            "progress": record.progress,
            "stage_current": record.stage_current,
            "stage_total": record.stage_total,
            "size": record.size,
            "mtime": record.mtime,
            "message": record.message,
            "error": record.error,
            "created_at": iso(record.created_at),
            "started_at": iso(record.started_at),
            "finished_at": iso(record.finished_at),
            "updated_at": iso(record.updated_at),
        }
