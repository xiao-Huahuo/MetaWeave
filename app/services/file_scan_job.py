import os
import threading
from datetime import datetime
from typing import Dict, Optional, List

from sqlmodel import Session, select

from app.core.database import engine
from app.core.logger import global_logger as logger
from app.models.file_meta import FileMeta
from app.services.file_watcher import calculate_file_hash
from app.services.file_content_extractor import FileContentExtractor


_scan_jobs: Dict[int, Dict] = {}
_scan_lock = threading.Lock()


def start_scan_job(kb_id: int, kb_path: str, user_id: int) -> Dict:
    with _scan_lock:
        existing = _scan_jobs.get(kb_id)
        if existing and existing.get("status") == "running":
            return existing

        job = {
            "kb_id": kb_id,
            "status": "running",
            "total": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "message": ""
        }
        _scan_jobs[kb_id] = job

    thread = threading.Thread(
        target=_run_scan_job,
        args=(kb_id, kb_path, user_id),
        daemon=True
    )
    thread.start()
    return job


def get_scan_job(kb_id: int) -> Dict:
    with _scan_lock:
        job = _scan_jobs.get(kb_id)
        if job:
            return job
    return {
        "kb_id": kb_id,
        "status": "idle",
        "total": 0,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "started_at": None,
        "finished_at": None,
        "message": ""
    }


def _run_scan_job(kb_id: int, kb_path: str, user_id: int):
    try:
        file_paths = _collect_files(kb_path)

        with Session(engine) as session:
            existing_files = session.exec(
                select(FileMeta).where(
                    FileMeta.kb_id == kb_id,
                    FileMeta.user_id == user_id
                )
            ).all()
            existing_map = {f.file_path: f for f in existing_files}

            if not file_paths:
                file_paths = [p for p in existing_map.keys() if os.path.exists(p)]

            _update_job(kb_id, total=len(file_paths))

            seen_paths = set()
            for file_path in file_paths:
                seen_paths.add(file_path)
                _index_or_update_file(
                    session=session,
                    kb_id=kb_id,
                    user_id=user_id,
                    file_path=file_path,
                    existing_map=existing_map
                )
                _inc_job(kb_id, "processed")

            _mark_missing_files(session, existing_map, seen_paths)
            session.commit()

        _finish_job(kb_id, status="completed")
    except Exception as e:
        logger.error(f"扫描任务失败 kb_id={kb_id}: {e}")
        _finish_job(kb_id, status="failed", message=str(e))


def _collect_files(kb_path: str) -> List[str]:
    kb_path = os.path.normpath(kb_path)
    if not os.path.exists(kb_path):
        raise FileNotFoundError(f"路径不存在: {kb_path}")
    if not os.path.isdir(kb_path):
        raise NotADirectoryError(f"不是文件夹: {kb_path}")

    file_paths = []
    for root, dirs, files in os.walk(kb_path):
        for filename in files:
            file_paths.append(os.path.abspath(os.path.join(root, filename)))
    return file_paths


def _index_or_update_file(
    session: Session,
    kb_id: int,
    user_id: int,
    file_path: str,
    existing_map: Dict[str, FileMeta]
):
    try:
        file_hash = calculate_file_hash(file_path)
        file_mtime = os.path.getmtime(file_path)
        file_size = os.path.getsize(file_path)
        parent_folder = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        file_type = os.path.splitext(file_path)[1].lstrip(".")

        file_meta = existing_map.get(file_path)
        if file_meta:
            mtime_changed = file_meta.file_mtime != file_mtime
            need_parse = file_meta.file_hash != file_hash or mtime_changed or not file_meta.file_content
            file_meta.file_hash = file_hash
            file_meta.file_mtime = file_mtime
            file_meta.file_size = file_size
            file_meta.modified_at = datetime.now()
            file_meta.last_indexed_at = datetime.now()
            file_meta.is_deleted = False
            session.add(file_meta)

            if need_parse:
                _parse_and_update(file_meta, file_path)
            return

        file_meta = FileMeta(
            user_id=user_id,
            kb_id=kb_id,
            file_path=file_path,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            parent_folder=parent_folder,
            file_hash=file_hash,
            file_mtime=file_mtime
        )
        _parse_and_update(file_meta, file_path)
        session.add(file_meta)
    except Exception as e:
        logger.error(f"索引文件失败 {file_path}: {e}")
        _inc_job(kb_id, "failed")


def _parse_and_update(file_meta: FileMeta, file_path: str):
    if not FileContentExtractor.is_supported(file_path):
        file_meta.content_status = "skipped"
        file_meta.content_error = None
        file_meta.content_extracted_at = datetime.now()
        _inc_job(file_meta.kb_id, "skipped")
        return

    file_meta.content_status = "processing"
    file_meta.content_error = None

    try:
        content = FileContentExtractor.extract(file_path)
        file_meta.file_content = content
        if content:
            file_meta.content_status = "done"
            _inc_job(file_meta.kb_id, "success")
        else:
            file_meta.content_status = "failed"
            file_meta.content_error = "解析失败或无有效内容"
            _inc_job(file_meta.kb_id, "failed")
    except Exception as e:
        file_meta.file_content = None
        file_meta.content_status = "failed"
        file_meta.content_error = str(e)
        _inc_job(file_meta.kb_id, "failed")
    finally:
        file_meta.content_extracted_at = datetime.now()


def _mark_missing_files(session: Session, existing_map: Dict[str, FileMeta], seen_paths: set):
    now = datetime.now()
    for path, meta in existing_map.items():
        if path not in seen_paths and not meta.is_deleted:
            meta.is_deleted = True
            meta.modified_at = now
            session.add(meta)


def _update_job(kb_id: int, **kwargs):
    with _scan_lock:
        job = _scan_jobs.get(kb_id)
        if not job:
            return
        job.update(kwargs)


def _inc_job(kb_id: int, field: str):
    with _scan_lock:
        job = _scan_jobs.get(kb_id)
        if not job:
            return
        job[field] = int(job.get(field, 0)) + 1


def _finish_job(kb_id: int, status: str, message: str = ""):
    with _scan_lock:
        job = _scan_jobs.get(kb_id)
        if not job:
            return
        job["status"] = status
        job["message"] = message
        job["finished_at"] = datetime.now().isoformat()
