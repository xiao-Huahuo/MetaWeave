"""
知识库单文件入库任务服务测试。

功能说明:
验证任务持久化、详细阶段进度和取消后的索引清理语义。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import SQLModel, create_engine

from agent_service.services.knowledge_ingestion_job.service import KnowledgeIngestionJobService


class _LibraryStub:
    """提供任务服务测试所需的最小知识库接口。"""

    def __init__(self, root: Path) -> None:
        """保存测试知识库根目录和失效调用。"""

        self.root = root
        self.invalidated: list[str] = []

    def get_active_root_path(self, *, user_id: str) -> Path:
        """返回测试知识库根目录。"""

        return self.root

    def invalidate_paths(self, *, user_id: str, relative_paths: list[str]) -> dict[str, int]:
        """记录取消后要求清理的来源路径。"""

        self.invalidated.extend(relative_paths)
        return {"files_invalidated": len(relative_paths), "chunks_deleted": 1}


def _service(tmp_path: Path) -> tuple[KnowledgeIngestionJobService, _LibraryStub]:
    """构造不自动启动后台调度器的任务服务。"""

    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    SQLModel.metadata.create_all(engine)
    root = tmp_path / "knowledge"
    root.mkdir()
    library = _LibraryStub(root)
    service = KnowledgeIngestionJobService(
        engine=engine,
        config=SimpleNamespace(),
        knowledge_library_service=library,
        autostart=False,
    )
    return service, library


def test_submit_jobs_persists_file_details_and_pipeline(tmp_path: Path) -> None:
    """每个文件必须形成独立、可恢复的持久化队列记录。"""

    service, _library = _service(tmp_path)
    source = tmp_path / "knowledge" / "report.pdf"
    source.write_bytes(b"%PDF-1.7")

    jobs = service.submit(user_id="u1", paths=["report.pdf"])
    restored = service.list_jobs(user_id="u1", active_only=True)

    assert jobs[0]["pipeline"] == "pdf"
    assert restored[0]["job_id"] == jobs[0]["job_id"]
    assert restored[0]["status"] == "queued"
    assert restored[0]["stage_label"] == "等待灌库"


def test_submit_reuses_same_active_file_and_appends_new_file(tmp_path: Path) -> None:
    """重复全量提交不得复制在途文件，但必须把后来出现的文件追加到队列。"""

    service, _library = _service(tmp_path)
    first = tmp_path / "knowledge" / "first.md"
    second = tmp_path / "knowledge" / "second.md"
    first.write_text("# first", encoding="utf-8")
    second.write_text("# second", encoding="utf-8")

    initial = service.submit(user_id="u1", paths=["first.md"])
    repeated = service.submit(user_id="u1", paths=["first.md", "second.md"])
    active = service.list_jobs(user_id="u1", active_only=True)

    assert repeated[0]["job_id"] == initial[0]["job_id"]
    assert [job["path"] for job in active] == ["first.md", "second.md"]


def test_scheduler_runs_two_files_concurrently_and_allows_out_of_order_completion(tmp_path: Path) -> None:
    """两个 worker 必须并发领取不同文件，并允许后启动的任务先完成。"""

    service, _library = _service(tmp_path)
    service.limits = SimpleNamespace(
        knowledge_job_worker_count=2,
        knowledge_job_poll_seconds=0.01,
        knowledge_job_scheduler_join_timeout_seconds=1.0,
        knowledge_job_process_join_timeout_seconds=1.0,
    )
    for name in ("first.md", "second.md"):
        (tmp_path / "knowledge" / name).write_text(f"# {name}", encoding="utf-8")
    service.submit(user_id="u1", paths=["first.md", "second.md"])

    both_started = threading.Barrier(3)
    releases = {name: threading.Event() for name in ("first.md", "second.md")}
    finished: list[str] = []
    all_finished = threading.Event()

    def run_claimed_job(job: dict[str, object]) -> None:
        path = str(job["path"])
        both_started.wait(timeout=2)
        assert releases[path].wait(timeout=2)
        finished.append(path)
        if len(finished) == 2:
            all_finished.set()

    service._run_claimed_job = run_claimed_job  # type: ignore[method-assign]
    try:
        service.start()
        both_started.wait(timeout=2)
        releases["second.md"].set()
        while not finished:
            assert not all_finished.wait(timeout=0.01)
        releases["first.md"].set()
        assert all_finished.wait(timeout=2)
    finally:
        for release in releases.values():
            release.set()
        service.stop()

    assert finished == ["second.md", "first.md"]


def test_progress_event_persists_detailed_stage_units(tmp_path: Path) -> None:
    """页、图片或切片等阶段单位必须直接进入任务记录。"""

    service, _library = _service(tmp_path)
    source = tmp_path / "knowledge" / "scan.pdf"
    source.write_bytes(b"%PDF-1.7")
    job = service.submit(user_id="u1", paths=["scan.pdf"])[0]

    service.apply_progress(job["job_id"], {
        "stage": "ocr",
        "stage_label": "OCR 第 3 / 12 页",
        "stage_current": 3,
        "stage_total": 12,
        "overall_progress": 46.27,
        "message": "正在识别扫描页",
    })
    updated = service.get_job(job_id=job["job_id"], user_id="u1")

    assert updated is not None
    assert updated["stage"] == "ocr"
    assert updated["stage_current"] == 3
    assert updated["stage_total"] == 12
    assert updated["progress"] == 46.3
    assert updated["message"] == "正在识别扫描页"


def test_cancel_queued_job_restores_unindexed_state(tmp_path: Path) -> None:
    """等待任务中止后必须标记 cancelled 并清理该来源索引。"""

    service, library = _service(tmp_path)
    source = tmp_path / "knowledge" / "note.md"
    source.write_text("# note", encoding="utf-8")
    job = service.submit(user_id="u1", paths=["note.md"])[0]

    cancelled = service.cancel(job_id=job["job_id"], user_id="u1")

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["stage_label"] == "已中止"
    assert cancelled["progress"] == 0
    assert library.invalidated == ["note.md"]


def test_cancel_running_job_terminates_worker_and_restores_unindexed_state(tmp_path: Path) -> None:
    """运行任务中止必须真实 terminate 独立进程，再清理该来源的部分索引。"""

    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.joined = False

        def is_alive(self) -> bool:
            return not self.terminated

        def terminate(self) -> None:
            self.terminated = True

        def join(self, timeout: int) -> None:
            self.joined = timeout == 2

    service, library = _service(tmp_path)
    source = tmp_path / "knowledge" / "large.pdf"
    source.write_bytes(b"%PDF-1.7")
    submitted = service.submit(user_id="u1", paths=["large.pdf"])[0]
    claimed = service._claim_next()
    process = FakeProcess()
    service._processes[submitted["job_id"]] = process  # type: ignore[assignment]

    cancelled = service.cancel(job_id=submitted["job_id"], user_id="u1")

    assert claimed is not None and claimed["status"] == "running"
    assert process.terminated is True
    assert process.joined is True
    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert cancelled["progress"] == 0
    assert library.invalidated == ["large.pdf"]
