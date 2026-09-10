"""Persistent scanner task, projection, and export service.

The service owns its bounded executor, stores originals below the active
library's ``.mw/scan`` directory, reuses the ingestion Markdown projection
stage, and persists user-editable drafts in SQLite.
"""

from __future__ import annotations

import io
import ipaddress
import json
import logging
import mimetypes
import multiprocessing
import re
import shutil
import socket
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import create_database_engine_from_url
from agent_service.models.scanner import ScannerRecord
from agent_service.models.favorite import FavoriteRecord
from agent_service.schemas.scanner import ScannerConflictStrategy, ScannerOut, ScannerVariant
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.services.settings.service import SettingsService
from agent_service.services.scanner.web_parser import HtmlMarkdownParser

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".html", ".htm", ".xml", ".tex", ".py", ".js", ".ts", ".css", ".yaml", ".yml"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^\n)]*\)")
WINDOWS_ACCESS_VIOLATION_EXIT_CODE = 0xC0000005


def _run_scanner_worker(database_url: str, config: AgentConfig, scan_id: str, context: dict[str, Any], safe_mode: bool) -> None:
    """Run one scan in a process that the parent scheduler can terminate safely."""

    if safe_mode:
        config.ocr.input_max_side_pixels = config.ocr.recovery_input_max_side_pixels
    engine = create_database_engine_from_url(database_url)
    worker = ScannerService(
        engine=engine,
        config=config,
        settings_service=None,
        knowledge_library_service=None,
        autostart=False,
        reconcile=False,
    )
    try:
        worker._process(scan_id, context)
    finally:
        engine.dispose()


class ScannerService:
    """Own scanner persistence, one bounded process queue, and managed artifacts."""

    def __init__(
        self,
        *,
        engine: Engine,
        config: AgentConfig,
        settings_service: SettingsService | None,
        knowledge_library_service: KnowledgeLibraryService | None,
        autostart: bool = True,
        reconcile: bool = True,
    ) -> None:
        """Bind services, recover interrupted records, and start one scheduler."""

        self.engine = engine
        self.config = config
        self.settings_service = settings_service
        self.knowledge_library_service = knowledge_library_service
        self._stop_event = Event()
        self._wake_event = Event()
        self._lock = Lock()
        self._scheduler_thread: Thread | None = None
        self._processes: dict[str, multiprocessing.Process] = {}
        self._safe_mode_scans: set[str] = set()
        self._closed = False
        if reconcile:
            self._reconcile_interrupted_records()
        if autostart:
            self.start()

    def start(self) -> None:
        """Start the single queue dispatcher with configured process capacity."""

        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                return
            if self._closed:
                raise RuntimeError("scanner service is stopped")
            self._stop_event.clear()
            self._scheduler_thread = Thread(target=self._scheduler_loop, daemon=True, name="scanner-scheduler")
            thread = self._scheduler_thread
        thread.start()

    def stop(self) -> None:
        """Reject new tasks, stop dispatching, and terminate owned processes."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._scheduler_thread
        self._stop_event.set()
        self._wake_event.set()
        if thread is not None:
            thread.join(timeout=self.config.limits.scanner_scheduler_join_timeout_seconds)
        with self._lock:
            running = list(self._processes.items())
            self._processes.clear()
        for scan_id, process in running:
            self._terminate_process(process)
            self._requeue_interrupted(scan_id)

    def create_file(self, *, user_id: str, filename: str, content: bytes, ocr_enabled: bool, source_kind: str = "file") -> ScannerOut:
        """Persist one managed source copy and enqueue its Markdown projection."""

        normalized_user = self._required(user_id, "user_id")
        safe_name = Path(filename).name.strip()
        if not safe_name:
            raise ValueError("filename is required")
        if len(content) > self.config.limits.scanner_source_max_bytes:
            raise ValueError("file exceeds scanner size limit")
        context = self._context(normalized_user)
        scan_id = f"scan_{uuid4().hex}"
        scan_root = self._scan_root(context=context, scan_id=scan_id)
        source_path = scan_root / "source" / safe_name
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)
        relative_path = source_path.relative_to(context["root"]).as_posix()
        record = ScannerRecord(
            scan_id=scan_id,
            user_id=context["user_id"],
            library_id=context["library_id"],
            source_kind=source_kind,
            source_name=safe_name,
            source_path=relative_path,
            size=len(content),
            ocr_enabled=ocr_enabled,
        )
        with Session(self.engine) as db:
            db.add(record)
            db.commit()
            db.refresh(record)
        self._submit(scan_id)
        return self._to_out(record, context=context, include_content=False)

    def create_url(self, *, user_id: str, url: str, ocr_enabled: bool) -> ScannerOut:
        """Persist a queued public webpage task and enqueue crawling."""

        normalized_user = self._required(user_id, "user_id")
        self._validate_public_url(url)
        context = self._context(normalized_user)
        scan_id = f"scan_{uuid4().hex}"
        source_name = (urlparse(url).hostname or "webpage") + ".html"
        record = ScannerRecord(
            scan_id=scan_id,
            user_id=context["user_id"],
            library_id=context["library_id"],
            source_kind="url",
            source_name=source_name,
            source_url=url,
            ocr_enabled=ocr_enabled,
        )
        with Session(self.engine) as db:
            db.add(record)
            db.commit()
            db.refresh(record)
        self._submit(scan_id)
        return self._to_out(record, context=context)

    def list_scans(self, *, user_id: str) -> list[ScannerOut]:
        """List current-library scanner records newest first."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            records = db.exec(
                select(ScannerRecord)
                .where(ScannerRecord.user_id == context["user_id"])
                .where(ScannerRecord.library_id == context["library_id"])
                .order_by(ScannerRecord.created_at.desc())
            ).all()
            return [self._to_out(record, context=context, include_content=False) for record in records]

    def get_scan(self, *, user_id: str, scan_id: str) -> ScannerOut:
        """Return one scanner record within the current user and library scope."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            return self._to_out(record, context=context)

    def update_draft(self, *, user_id: str, scan_id: str, variant: ScannerVariant, content: str) -> ScannerOut:
        """Persist one editable scanner Markdown variant in SQLite."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            if variant == "ocr":
                if not record.ocr_enabled:
                    raise ValueError("OCR variant is unavailable for this scan")
                record.ocr_markdown = content
            else:
                record.no_ocr_markdown = content
            record.updated_at = self._now()
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._to_out(record, context=context)

    def update_source_text(self, *, user_id: str, scan_id: str, content: str) -> ScannerOut:
        """Write UTF-8 text into a managed text source without reparsing drafts."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            source = self._source_absolute(record=record, context=context)
            if source.suffix.lower() not in TEXT_SUFFIXES:
                raise ValueError("source is not an editable text file")
            source.write_text(content, encoding="utf-8")
            record.size = source.stat().st_size
            record.updated_at = self._now()
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._to_out(record, context=context)

    def delete_scan(self, *, user_id: str, scan_id: str) -> bool:
        """Delete a terminal history record and its isolated managed directory."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            if record.status in {"queued", "running"}:
                raise ValueError("cannot delete a running scan")
            scan_root = self._scan_root(context=context, scan_id=scan_id)
            favorite = db.exec(
                select(FavoriteRecord)
                .where(FavoriteRecord.user_id == context["user_id"])
                .where(FavoriteRecord.library_id == context["library_id"])
                .where(FavoriteRecord.target_type == "scanner")
                .where(FavoriteRecord.target_id == scan_id)
            ).first()
            if favorite is not None:
                db.delete(favorite)
            db.delete(record)
            db.commit()
        if scan_root.is_dir():
            shutil.rmtree(scan_root)
        return True

    def cancel(self, *, user_id: str, scan_id: str) -> ScannerOut:
        """Cancel a queued task or hard-stop only its isolated worker process."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            if record.status not in {"queued", "running", "cancelling"}:
                return self._to_out(record, context=context)
            running = record.status in {"running", "cancelling"}
            record.status = "cancelling" if running else "cancelled"
            record.stage = "cancelling" if running else "cancelled"
            record.stage_label = "正在终止" if running else "已终止"
            record.updated_at = self._now()
            if not running:
                record.finished_at = self._now()
            db.add(record)
            db.commit()
        if running:
            with self._lock:
                process = self._processes.get(scan_id)
            if process is not None:
                self._terminate_process(process)
                with self._lock:
                    if self._processes.get(scan_id) is process:
                        self._processes.pop(scan_id, None)
            self._finish_cancelled(scan_id)
        with self._lock:
            self._safe_mode_scans.discard(scan_id)
        self._wake_event.set()
        return self.get_scan(user_id=user_id, scan_id=scan_id)

    def save_to_knowledge(
        self,
        *,
        user_id: str,
        scan_id: str,
        variant: ScannerVariant,
        conflict_strategy: ScannerConflictStrategy,
    ) -> dict[str, Any]:
        """Write a chosen projection and its referenced assets into the knowledge root."""

        if self.settings_service is None or self.knowledge_library_service is None:
            raise RuntimeError("scanner worker cannot save knowledge projections")
        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            markdown = self._variant_content(record, variant)
            filename = f"{Path(record.source_name).stem}.md"
            assets = self._asset_paths(record=record, context=context) if variant == "no_ocr" else []
        existing_target = context["root"] / filename
        if conflict_strategy == "skip" and existing_target.exists():
            return {"ok": True, "path": filename, "assets": [], "skipped": True}
        profile = self.settings_service.ensure_user_profile(user_id=context["user_id"])
        asset_dir = self._normalized_asset_dir(str(profile.get("editor_image_assets_dir") or "./assets/"))
        markdown, copied_assets = self._copy_assets_to_knowledge(
            markdown=markdown,
            assets=assets,
            root=context["root"],
            asset_dir=asset_dir,
            scan_id=scan_id,
        )
        target = self.knowledge_library_service.write_uploaded_file(
            user_id=context["user_id"],
            filename=filename,
            content=markdown.encode("utf-8"),
            conflict_strategy=conflict_strategy,
        )
        relative = target.relative_to(context["root"]).as_posix()
        if bool(profile.get("auto_ingest_on_upload")):
            self.knowledge_library_service.ingest_single_file(user_id=context["user_id"], path=relative)
        return {"ok": True, "path": relative, "assets": copied_assets}

    def export_payload(self, *, user_id: str, scan_id: str, variant: ScannerVariant) -> tuple[str, str, bytes]:
        """Return filename, media type, and bytes for native external saving."""

        if self.settings_service is None:
            raise RuntimeError("scanner worker cannot export projections")
        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            markdown = self._variant_content(record, variant)
            stem = Path(record.source_name).stem
            if variant == "ocr":
                return f"{stem}.md", "text/markdown; charset=utf-8", markdown.encode("utf-8")
            assets = self._asset_paths(record=record, context=context)
        profile = self.settings_service.ensure_user_profile(user_id=context["user_id"])
        asset_dir = self._normalized_asset_dir(str(profile.get("editor_image_assets_dir") or "./assets/"))
        markdown = self._rewrite_asset_directory(markdown, asset_dir)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{stem}.md", markdown)
            for asset in assets:
                archive.write(asset, f"{asset_dir}/{asset.name}")
        return f"{stem}.zip", "application/zip", buffer.getvalue()

    def _submit(self, scan_id: str) -> None:
        """Wake the queue dispatcher after a durable record is committed."""

        with self._lock:
            if self._closed:
                raise RuntimeError("scanner service is stopped")
        self._wake_event.set()

    @property
    def max_concurrency(self) -> int:
        """Return the normalized process capacity owned by this scanner scheduler."""

        return max(1, int(self.config.limits.scanner_worker_count))

    def _scheduler_loop(self) -> None:
        """Fill free process slots from the durable FIFO queue and reap exits."""

        capacity = self.max_concurrency
        while not self._stop_event.is_set():
            try:
                self._reap_finished_processes()
                while not self._stop_event.is_set() and self._active_process_count() < capacity:
                    job = self._claim_next()
                    if job is None:
                        break
                    self._start_claimed_task(job)
            except Exception:
                logger.exception("扫描器调度循环异常")
            self._wake_event.wait(timeout=self.config.limits.scanner_process_poll_seconds)
            self._wake_event.clear()

    def _active_process_count(self) -> int:
        """Return the number of process slots currently owned by the scheduler."""

        with self._lock:
            return len(self._processes)

    def _claim_next(self) -> dict[str, Any] | None:
        """Claim the oldest task whose general and OCR resource slots are free."""

        while True:
            with Session(self.engine) as db:
                queued = db.exec(
                    select(ScannerRecord)
                    .where(ScannerRecord.status == "queued")
                    .order_by(ScannerRecord.created_at, ScannerRecord.scan_id)
                ).all()
                running_ocr = db.exec(
                    select(ScannerRecord)
                    .where(ScannerRecord.status == "running")
                    .where(ScannerRecord.ocr_enabled == True)  # noqa: E712
                ).all()
                ocr_capacity = max(1, int(self.config.limits.scanner_ocr_worker_count))
                record = next(
                    (candidate for candidate in queued if not candidate.ocr_enabled or len(running_ocr) < ocr_capacity),
                    None,
                )
                if record is None:
                    return None
                try:
                    context = self._context(record.user_id, expected_library_id=record.library_id)
                except Exception as exc:
                    record.status = "failed"
                    record.stage = "failed"
                    record.stage_label = "解析失败"
                    record.error = str(exc)
                    record.finished_at = self._now()
                    record.updated_at = self._now()
                    db.add(record)
                    db.commit()
                    logger.exception("扫描器任务上下文解析失败 | scan_id=%s", record.scan_id)
                    continue
                record.status = "running"
                record.stage = "prepare"
                record.stage_label = "正在准备文件"
                record.progress = max(record.progress, 1)
                record.updated_at = self._now()
                db.add(record)
                db.commit()
                return {"scan_id": record.scan_id, "context": context}

    def _start_claimed_task(self, job: dict[str, Any]) -> None:
        """Launch one claimed record in its own spawn-isolated process."""

        scan_id = str(job["scan_id"])
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_run_scanner_worker,
            args=(str(self.engine.url), self.config, scan_id, dict(job["context"]), self._is_safe_mode(scan_id)),
            daemon=True,
            name=f"scanner-{scan_id[-8:]}",
        )
        with self._lock:
            self._processes[scan_id] = process
        try:
            if self._scan_status(scan_id) in {"cancelling", "cancelled"}:
                with self._lock:
                    self._processes.pop(scan_id, None)
                self._finish_cancelled(scan_id)
                return
            process.start()
        except Exception as exc:
            with self._lock:
                self._processes.pop(scan_id, None)
            self._finish_failed(scan_id, f"扫描工作进程启动失败: {exc}")

    def _reap_finished_processes(self) -> None:
        """Release completed process handles and repair abnormal exits."""

        with self._lock:
            snapshot = list(self._processes.items())
        for scan_id, process in snapshot:
            try:
                alive = process.is_alive()
            except ValueError:
                continue
            if alive:
                continue
            process.join(timeout=0)
            with self._lock:
                if self._processes.get(scan_id) is process:
                    self._processes.pop(scan_id, None)
            status = self._scan_status(scan_id)
            if status == "cancelling":
                self._finish_cancelled(scan_id)
            elif status in {"queued", "running"}:
                if self._claim_safe_mode_retry(scan_id=scan_id, exitcode=process.exitcode):
                    self._requeue_native_crash(scan_id)
                    self._wake_event.set()
                else:
                    self._finish_failed(scan_id, f"扫描工作进程异常退出 ({process.exitcode})")
            else:
                with self._lock:
                    self._safe_mode_scans.discard(scan_id)
            process.close()

    def _is_safe_mode(self, scan_id: str) -> bool:
        """Return whether one task is using its bounded native-crash retry."""

        with self._lock:
            return scan_id in self._safe_mode_scans

    def _claim_safe_mode_retry(self, *, scan_id: str, exitcode: int | None) -> bool:
        """Grant one retry for the Windows native access-violation exit code."""

        if exitcode is None or exitcode & 0xFFFFFFFF != WINDOWS_ACCESS_VIOLATION_EXIT_CODE:
            return False
        with self._lock:
            if scan_id in self._safe_mode_scans:
                return False
            self._safe_mode_scans.add(scan_id)
            return True

    def _requeue_native_crash(self, scan_id: str) -> None:
        """Return one crashed OCR task to the queue with explicit recovery state."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None or record.status not in {"queued", "running"}:
                return
            record.status = "queued"
            record.stage = "queued"
            record.stage_label = "高分辨率 OCR 异常，等待安全模式重试"
            record.progress = 0
            record.error = ""
            record.finished_at = None
            record.updated_at = self._now()
            db.add(record)
            db.commit()

    def _terminate_process(self, process: Any) -> None:
        """Terminate one child, escalating to kill when it does not exit promptly."""

        if process.is_alive():
            process.terminate()
            process.join(timeout=self.config.limits.scanner_process_join_timeout_seconds)
        if process.is_alive():
            process.kill()
            process.join(timeout=self.config.limits.scanner_process_join_timeout_seconds)
        close = getattr(process, "close", None)
        if callable(close):
            close()

    def _scan_status(self, scan_id: str) -> str:
        """Read one task status without holding the scheduler state lock."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            return record.status if record is not None else "missing"

    def _process(self, scan_id: str, context_override: dict[str, Any] | None = None) -> None:
        """Run file projection or webpage crawling and persist a terminal state."""

        try:
            self._set_progress(scan_id, status="running", stage="prepare", label="正在准备文件", progress=2)
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None:
                    return
                context = context_override or self._context(record.user_id, expected_library_id=record.library_id)
                if record.source_kind == "url":
                    no_ocr, ocr, assets, ocr_blocks, source_name, source_path, size = self._crawl(record=record, context=context)
                else:
                    no_ocr, ocr, assets, ocr_blocks = self._project_file(record=record, context=context)
                    source_name, source_path, size = record.source_name, record.source_path, record.size
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None or record.status in {"cancelled", "cancelling"}:
                    return
                record.source_name = source_name
                record.source_path = source_path
                record.size = size
                record.no_ocr_markdown = no_ocr
                record.ocr_markdown = ocr
                record.ocr_blocks_json = json.dumps(ocr_blocks, ensure_ascii=False)
                record.assets_json = json.dumps(assets, ensure_ascii=False)
                record.status = "finished"
                record.stage = "completed"
                record.stage_label = "解析完成"
                record.progress = 100
                record.error = ""
                record.finished_at = self._now()
                record.updated_at = self._now()
                db.add(record)
                db.commit()
        except Exception as exc:
            logger.exception("扫描器解析失败 | scan_id=%s", scan_id)
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None or record.status in {"cancelled", "cancelling"}:
                    return
                record.status = "failed"
                record.stage = "failed"
                record.stage_label = "解析失败"
                record.error = str(exc)
                record.finished_at = self._now()
                record.updated_at = self._now()
                db.add(record)
                db.commit()

    def _project_file(self, *, record: ScannerRecord, context: dict[str, Any]) -> tuple[str, str, list[str], list[dict[str, Any]]]:
        """Create no-OCR and optional OCR projections through the shared cleaner."""

        source = self._source_absolute(record=record, context=context)
        supported = set(self.config.constants.knowledge_supported_suffixes)
        if not FrontmatterBootstrapService._can_structure_source_file(source, supported):
            raise ValueError(f"unsupported binary file type: {source.suffix.lower() or 'unknown'}")
        assets_dir = self._scan_root(context=context, scan_id=record.scan_id) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in IMAGE_SUFFIXES:
            asset = assets_dir / self._safe_asset_name(source.name)
            shutil.copy2(source, asset)
            no_ocr = f"# {source.stem}\n\n![{source.stem}](./assets/{asset.name})\n"
        else:
            no_ocr_doc = FrontmatterBootstrapService(config=self.config, ocr_enabled=False, ocr_inline=True).build_markdown_projection(
                source_path=source,
                knowledge_dir=context["root"],
                asset_output_dir=assets_dir,
                asset_public_prefix="./assets",
                progress_callback=lambda payload: self._projection_progress(record.scan_id, payload, 4, 48),
            )
            no_ocr = no_ocr_doc.markdown
        assets = [path.relative_to(context["root"]).as_posix() for path in sorted(assets_dir.glob("*")) if path.is_file()]
        if not record.ocr_enabled:
            return no_ocr, "", assets, []
        if source.suffix.lower() in IMAGE_SUFFIXES:
            result = ImageOcrService(config=self.config, enabled=True, run_inline=True).extract_image_text(
                source,
                progress_callback=lambda payload: self._set_progress(
                    record.scan_id,
                    status="running",
                    stage=str(payload.get("stage") or "ocr"),
                    label=str(payload.get("stage_label") or "正在识别图片"),
                    progress=50 + max(0.0, min(100.0, float(payload.get("progress") or 0))) * 0.46,
                ),
            )
            if result.preview_image_png:
                (assets_dir / "ocr-preview.png").write_bytes(result.preview_image_png)
            return no_ocr, self._strip_markdown_images(result.content), assets, [dict(block) for block in result.blocks]
        ocr_doc = FrontmatterBootstrapService(config=self.config, ocr_enabled=True, ocr_inline=True).build_markdown_projection(
            source_path=source,
            knowledge_dir=context["root"],
            asset_output_dir=assets_dir,
            asset_public_prefix="./assets",
            progress_callback=lambda payload: self._projection_progress(record.scan_id, payload, 50, 96),
        )
        ocr_blocks = [dict(block) for block in ocr_doc.metadata.get("ocr_blocks", []) if isinstance(block, dict)]
        return no_ocr, self._strip_markdown_images(ocr_doc.markdown), assets, ocr_blocks

    def _crawl(self, *, record: ScannerRecord, context: dict[str, Any]) -> tuple[str, str, list[str], list[dict[str, Any]], str, str, int]:
        """Fetch a public webpage, localize images, and build both projection variants."""

        self._set_progress(record.scan_id, status="running", stage="download", label="正在抓取网页", progress=12)
        final_url, content_type, body = self._fetch_url(record.source_url)
        if "html" not in content_type.lower():
            raise ValueError("webpage URL did not return HTML")
        text = body.decode("utf-8", errors="replace")
        parser = HtmlMarkdownParser()
        parser.feed(text)
        title = parser.title() or urlparse(final_url).hostname or "webpage"
        safe_title = re.sub(r"[\\/:*?\"<>|]+", "-", title).strip(" .") or "webpage"
        scan_root = self._scan_root(context=context, scan_id=record.scan_id)
        source = scan_root / "source" / f"{safe_title}.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(body)
        markdown = parser.markdown()
        if not markdown.lstrip().startswith("#"):
            markdown = f"# {safe_title}\n\n{markdown}"
        assets_dir = scan_root / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        replacements: dict[str, str] = {}
        for index, (image_url, _alt) in enumerate(parser.images, start=1):
            try:
                absolute_url = urljoin(final_url, image_url)
                _, image_type, image_body = self._fetch_url(absolute_url)
                if not image_type.lower().startswith("image/"):
                    continue
                suffix = mimetypes.guess_extension(image_type.split(";", 1)[0].strip()) or Path(urlparse(absolute_url).path).suffix or ".img"
                name = self._safe_asset_name(f"image-{index}{suffix}")
                (assets_dir / name).write_bytes(image_body)
                replacements[image_url] = f"./assets/{name}"
            except Exception:
                logger.info("网页图片本地化失败 | scan_id=%s image=%s", record.scan_id, image_url)
        for remote, local in replacements.items():
            markdown = markdown.replace(f"]({remote})", f"]({local})")
        self._set_progress(record.scan_id, status="running", stage="normalize", label="正在生成 Markdown", progress=72)
        assets = [path.relative_to(context["root"]).as_posix() for path in sorted(assets_dir.glob("*")) if path.is_file()]
        ocr_texts: list[str] = []
        ocr_blocks: list[dict[str, Any]] = []
        if record.ocr_enabled and assets:
            ocr_service = ImageOcrService(config=self.config, enabled=True, run_inline=True)
            for index, relative in enumerate(assets, start=1):
                result = ocr_service.extract_image_text(context["root"] / relative)
                if result.has_text:
                    ocr_texts.append(result.content)
                ocr_blocks.extend(dict(block) for block in result.blocks)
                self._set_progress(record.scan_id, status="running", stage="ocr", label=f"正在识别网页图片 {index}/{len(assets)}", progress=72 + round(index / len(assets) * 22))
        ocr_markdown = self._strip_markdown_images(markdown)
        if ocr_texts:
            ocr_markdown += "\n\n## 图片文字\n\n" + "\n\n".join(ocr_texts)
        return markdown.strip() + "\n", ocr_markdown.strip() + "\n" if record.ocr_enabled else "", assets, ocr_blocks, source.name, source.relative_to(context["root"]).as_posix(), len(body)

    def _fetch_url(self, url: str) -> tuple[str, str, bytes]:
        """Fetch one public URL with per-hop SSRF checks and bounded bytes."""

        current = url
        for _ in range(self.config.limits.scanner_redirect_limit + 1):
            self._validate_public_url(current)
            response = requests.get(
                current,
                headers={"User-Agent": "MetaWeave-Scanner/1.0"},
                timeout=self.config.limits.web_fetch_timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location", "").strip()
                if not location:
                    raise ValueError("webpage redirect is missing a location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > self.config.limits.scanner_web_max_bytes:
                    raise ValueError("web resource exceeds scanner size limit")
            return current, response.headers.get("Content-Type", ""), bytes(data)
        raise ValueError("webpage exceeded redirect limit")

    def _validate_public_url(self, url: str) -> None:
        """Reject non-HTTP schemes and DNS targets in private/local networks."""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must use http or https")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("unable to resolve webpage host") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("private or local webpage addresses are not allowed")

    def _projection_progress(self, scan_id: str, payload: dict[str, Any], start: int, end: int) -> None:
        """Map the shared 0-100 projection progress into one scanner phase."""

        source_progress = float(payload.get("overall_progress") or 0)
        progress = round(start + max(0, min(100, source_progress)) / 100 * (end - start), 1)
        self._set_progress(scan_id, status="running", stage=str(payload.get("stage") or "extract"), label=str(payload.get("stage_label") or "正在解析文件"), progress=progress)

    def _set_progress(self, scan_id: str, *, status: str, stage: str, label: str, progress: float) -> None:
        """Persist monotonic scanner task progress."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None or record.status in {"cancelled", "cancelling"}:
                return
            record.status = status
            record.stage = stage
            record.stage_label = label
            running_max = self.config.limits.progress_max_percent - 0.1
            record.progress = max(record.progress, min(running_max, round(progress, 1)))
            record.updated_at = self._now()
            db.add(record)
            db.commit()

    def _copy_assets_to_knowledge(self, *, markdown: str, assets: list[Path], root: Path, asset_dir: str, scan_id: str) -> tuple[str, list[str]]:
        """Copy assets with collision-safe names and rewrite Markdown links."""

        target_dir = (root / asset_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        rewritten = self._rewrite_asset_directory(markdown, asset_dir)
        for asset in assets:
            target_name = self._safe_asset_name(f"{scan_id[-8:]}-{asset.name}")
            target = target_dir / target_name
            shutil.copy2(asset, target)
            rewritten = rewritten.replace(f"{asset_dir}/{asset.name}", f"{asset_dir}/{target_name}")
            copied.append(target.relative_to(root).as_posix())
        return rewritten, copied

    @staticmethod
    def _rewrite_asset_directory(markdown: str, asset_dir: str) -> str:
        """Rewrite scanner-local asset links to a configured relative directory."""

        normalized = f"./{asset_dir.strip('./')}/"
        return markdown.replace("./assets/", normalized)

    @staticmethod
    def _strip_markdown_images(markdown: str) -> str:
        """Remove Markdown and HTML image nodes from a pure-text OCR projection."""

        value = IMAGE_MARKDOWN_RE.sub("", markdown)
        value = re.sub(r"<img\b[^>]*>", "", value, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", value).strip() + "\n"

    @staticmethod
    def _normalized_asset_dir(value: str) -> str:
        """Return the safe slash-normalized relative asset directory."""

        parts = [part for part in value.replace("\\", "/").split("/") if part and part != "."]
        if not parts or ".." in parts:
            return "assets"
        return "/".join(parts)

    @staticmethod
    def _safe_asset_name(value: str) -> str:
        """Normalize one downloaded or extracted asset basename."""

        name = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(value).name).strip(".-")
        return name or f"asset-{uuid4().hex[:8]}"

    def _asset_paths(self, *, record: ScannerRecord, context: dict[str, Any]) -> list[Path]:
        """Resolve persisted relative asset paths without permitting traversal."""

        try:
            relative_paths = json.loads(record.assets_json or "[]")
        except json.JSONDecodeError:
            relative_paths = []
        assets: list[Path] = []
        for value in relative_paths if isinstance(relative_paths, list) else []:
            candidate = (context["root"] / str(value)).resolve()
            if self._is_relative_to(candidate, context["root"]) and candidate.is_file():
                assets.append(candidate)
        return assets

    @staticmethod
    def _variant_content(record: ScannerRecord, variant: ScannerVariant) -> str:
        """Return an available terminal Markdown variant or raise a clear error."""

        if record.status != "finished":
            raise ValueError("scan is not finished")
        if variant == "ocr" and not record.ocr_enabled:
            raise ValueError("OCR variant is unavailable for this scan")
        content = record.ocr_markdown if variant == "ocr" else record.no_ocr_markdown
        if not content:
            raise ValueError("scanner Markdown is empty")
        return content

    def _context(self, user_id: str, expected_library_id: str = "") -> dict[str, Any]:
        """Resolve the active user/library/root and optionally verify task scope."""

        if self.settings_service is None:
            raise RuntimeError("scanner worker requires an explicit task context")
        profile = self.settings_service.ensure_user_profile(user_id=self._required(user_id, "user_id"))
        active = dict(profile["active_knowledge_library"])
        library_id = str(active["library_id"])
        if expected_library_id and library_id != expected_library_id:
            raise ValueError("scanner record belongs to another knowledge library")
        root = Path(str(active["knowledge_dir"])).expanduser().resolve()
        return {"user_id": str(profile["user_id"]), "library_id": library_id, "root": root}

    @staticmethod
    def _scan_root(*, context: dict[str, Any], scan_id: str) -> Path:
        """Return one isolated scanner directory under the active knowledge root."""

        return Path(context["root"]) / ".mw" / "scan" / scan_id

    def _source_absolute(self, *, record: ScannerRecord, context: dict[str, Any]) -> Path:
        """Resolve a persisted managed source path within the active root."""

        source = (context["root"] / record.source_path).resolve()
        if not self._is_relative_to(source, context["root"]) or not source.is_file():
            raise ValueError("managed scanner source not found")
        return source

    @staticmethod
    def _owned_record(*, db: Session, context: dict[str, Any], scan_id: str) -> ScannerRecord:
        """Load one record and enforce user plus library ownership."""

        record = db.get(ScannerRecord, scan_id)
        if record is None or record.user_id != context["user_id"] or record.library_id != context["library_id"]:
            raise ValueError("scanner record not found")
        return record

    def _to_out(self, record: ScannerRecord, *, context: dict[str, Any], include_content: bool = True) -> ScannerOut:
        """Serialize a record, omitting large drafts from history-list payloads."""

        source_text: str | None = None
        if include_content and record.source_path:
            source = (context["root"] / record.source_path).resolve()
            if self._is_relative_to(source, context["root"]) and source.is_file() and source.suffix.lower() in TEXT_SUFFIXES:
                try:
                    source_text = source.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    source_text = source.read_text(encoding="utf-8", errors="replace")
        try:
            assets = json.loads(record.assets_json or "[]")
        except json.JSONDecodeError:
            assets = []
        try:
            ocr_blocks = json.loads(record.ocr_blocks_json or "[]")
        except json.JSONDecodeError:
            ocr_blocks = []
        return ScannerOut(
            scan_id=record.scan_id,
            user_id=record.user_id,
            library_id=record.library_id,
            source_kind=record.source_kind,
            source_name=record.source_name,
            source_path=record.source_path,
            source_url=record.source_url,
            size=record.size,
            ocr_enabled=record.ocr_enabled,
            status=record.status,
            stage=record.stage,
            stage_label=record.stage_label,
            progress=record.progress,
            no_ocr_markdown=record.no_ocr_markdown if include_content else "",
            ocr_markdown=record.ocr_markdown if include_content else "",
            ocr_blocks=[dict(item) for item in ocr_blocks if isinstance(item, dict)] if include_content else [],
            ocr_preview_path=self._ocr_preview_path(record=record, context=context),
            assets=[str(item) for item in assets] if isinstance(assets, list) else [],
            error=record.error,
            source_text=source_text,
            created_at=record.created_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
        )

    def _ocr_preview_path(self, *, record: ScannerRecord, context: dict[str, Any]) -> str:
        """Return the preprocessed image whose pixels match persisted OCR boxes."""

        preview = self._scan_root(context=context, scan_id=record.scan_id) / "assets" / "ocr-preview.png"
        return preview.relative_to(context["root"]).as_posix() if preview.is_file() else ""

    def _finish_cancelled(self, scan_id: str) -> None:
        """Persist the cancelled terminal state after the worker is gone."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None:
                return
            record.status = "cancelled"
            record.stage = "cancelled"
            record.stage_label = "已终止"
            record.error = ""
            record.finished_at = self._now()
            record.updated_at = self._now()
            db.add(record)
            db.commit()
        with self._lock:
            self._safe_mode_scans.discard(scan_id)

    def _finish_failed(self, scan_id: str, message: str) -> None:
        """Persist an abnormal worker exit without affecting sibling tasks."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None or record.status == "cancelled":
                return
            record.status = "failed"
            record.stage = "failed"
            record.stage_label = "解析失败"
            record.error = message
            record.finished_at = self._now()
            record.updated_at = self._now()
            db.add(record)
            db.commit()
        with self._lock:
            self._safe_mode_scans.discard(scan_id)

    def _requeue_interrupted(self, scan_id: str) -> None:
        """Return a shutdown-interrupted running task to the durable queue."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None or record.status not in {"running", "cancelling"}:
                return
            if record.status == "cancelling":
                record.status = "cancelled"
                record.stage = "cancelled"
                record.stage_label = "已终止"
                record.finished_at = self._now()
            else:
                record.status = "queued"
                record.stage = "queued"
                record.stage_label = "等待解析"
                record.progress = 0
            record.updated_at = self._now()
            db.add(record)
            db.commit()

    def _reconcile_interrupted_records(self) -> None:
        """Recover running work to the queue and complete interrupted cancellation."""

        with Session(self.engine) as db:
            records = db.exec(select(ScannerRecord).where(ScannerRecord.status.in_(["running", "cancelling"]))).all()
            for record in records:
                if record.status == "cancelling":
                    record.status = "cancelled"
                    record.stage = "cancelled"
                    record.stage_label = "已终止"
                    record.finished_at = self._now()
                else:
                    record.status = "queued"
                    record.stage = "queued"
                    record.stage_label = "等待解析"
                    record.progress = 0
                record.updated_at = self._now()
                db.add(record)
            if records:
                db.commit()

    @staticmethod
    def _required(value: str, label: str) -> str:
        """Normalize a required string."""

        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        """Return whether a resolved path remains inside a resolved root."""

        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _now() -> datetime:
        """Return the current timezone-aware UTC timestamp."""

        return datetime.now(timezone.utc)
