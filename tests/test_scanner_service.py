"""Focused scanner service persistence and projection regression tests."""

from __future__ import annotations

import io
import multiprocessing
import threading
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import SQLModel, Session, create_engine

import agent_service.models  # noqa: F401
from agent_service.core.agent_config import AgentConfig
from agent_service.models.scanner import ScannerRecord
from agent_service.services.memory.rag.image_ocr import ImageOcrResult, ImageOcrService
from agent_service.services.scanner import ScannerService


class _SettingsStub:
    """Provide one active library without touching user settings storage."""

    def __init__(self, root: Path) -> None:
        """Retain the isolated knowledge root."""

        self.root = root

    def ensure_user_profile(self, *, user_id: str) -> dict:
        """Return the profile fields consumed by ScannerService."""

        return {
            "user_id": user_id,
            "active_knowledge_library": {"library_id": "lib-test", "knowledge_dir": str(self.root)},
            "editor_image_assets_dir": "./assets/",
            "auto_ingest_on_upload": False,
        }


class _OnlineSettingsStub(_SettingsStub):
    """Provide one enabled MinerU config for parent-to-worker snapshot tests."""

    def get_vlm_config(self, *, user_id: str) -> dict[str, object]:
        """Return the validated user-scoped VLM configuration."""

        return {"user_id": user_id, "enabled": True, "configured": True, "api_key": "worker-key", "model": "vlm", "max_file_bytes": 209715200}


class _KnowledgeStub:
    """Persist saved Markdown into the isolated knowledge root."""

    def __init__(self, root: Path) -> None:
        """Retain the isolated knowledge root."""

        self.root = root

    def write_uploaded_file(self, *, filename: str, content: bytes, **_: object) -> Path:
        """Write the requested Markdown file and return its absolute path."""

        target = self.root / filename
        target.write_bytes(content)
        return target

    def ingest_single_file(self, **_: object) -> None:
        """Record no work because auto ingestion is disabled in this test."""


class _FakeProcess:
    """Record process lifecycle calls without launching a child process."""

    def __init__(self, *, alive: bool = True, exitcode: int | None = None) -> None:
        """Initialize one live fake process."""

        self.alive = alive
        self.exitcode = exitcode
        self.terminated = False
        self.killed = False

    def is_alive(self) -> bool:
        """Return the current fake liveness."""

        return self.alive

    def terminate(self) -> None:
        """Record termination and stop immediately."""

        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        """Record forced termination and stop immediately."""

        self.killed = True
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        """Match the multiprocessing process join contract."""

    def close(self) -> None:
        """Match release of an exited process handle."""


def test_scanner_scheduler_runs_two_tasks_and_keeps_overflow_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two configured slots run concurrently while the third task waits."""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-queue.db'}")
    SQLModel.metadata.create_all(engine)
    config = AgentConfig()
    config.limits.scanner_worker_count = 2
    service = ScannerService(
        engine=engine,
        config=config,
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    assert service.max_concurrency == 2
    started: list[str] = []

    def fake_start(job: dict[str, object]) -> None:
        scan_id = str(job["scan_id"])
        started.append(scan_id)
        service._processes[scan_id] = _FakeProcess()  # type: ignore[assignment]

    monkeypatch.setattr(service, "_start_claimed_task", fake_start)
    try:
        tasks = [
            service.create_file(user_id="u1", filename=f"{index}.txt", content=b"text", ocr_enabled=False)
            for index in range(3)
        ]
        service.start()
        deadline = time.monotonic() + 2
        while len(started) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert set(started) == {tasks[0].scan_id, tasks[1].scan_id}
        assert service.get_scan(user_id="u1", scan_id=tasks[2].scan_id).status == "queued"
    finally:
        service.stop()


def test_scanner_scheduler_queues_second_ocr_task_for_the_model_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only one OCR process may own the heavy native model while other work can use the second slot."""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-ocr-queue.db'}")
    SQLModel.metadata.create_all(engine)
    config = AgentConfig()
    config.limits.scanner_worker_count = 2
    config.limits.scanner_ocr_worker_count = 1
    service = ScannerService(
        engine=engine,
        config=config,
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    started: list[str] = []

    def fake_start(job: dict[str, object]) -> None:
        scan_id = str(job["scan_id"])
        started.append(scan_id)
        service._processes[scan_id] = _FakeProcess()  # type: ignore[assignment]

    monkeypatch.setattr(service, "_start_claimed_task", fake_start)
    try:
        first = service.create_file(user_id="u1", filename="first.png", content=b"first", ocr_enabled=True)
        second = service.create_file(user_id="u1", filename="second.png", content=b"second", ocr_enabled=True)
        service.start()
        deadline = time.monotonic() + 2
        while not started and time.monotonic() < deadline:
            time.sleep(0.01)

        assert started == [first.scan_id]
        assert service.get_scan(user_id="u1", scan_id=second.scan_id).status == "queued"
    finally:
        service.stop()


def test_inline_ocr_runs_native_inference_on_the_worker_main_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Process-isolated OCR must not leave a native daemon thread behind after timeout."""

    image_path = tmp_path / "non-uniform.jpeg"
    image = Image.new("RGB", (4, 3), "white")
    image.putpixel((3, 2), (0, 0, 0))
    image.save(image_path, format="JPEG")
    config = AgentConfig()
    config.ocr.input_max_side_pixels = 3
    service = ImageOcrService(config=config, enabled=True, run_inline=True)
    called_from: list[str] = []
    normalized_inputs: list[tuple[bool, str | None, str, tuple[int, int]]] = []

    def fake_extract(source_path: Path, progress_callback: object, timeout_seconds: float) -> ImageOcrResult:
        called_from.append(threading.current_thread().name)
        with Image.open(source_path) as normalized:
            normalized_inputs.append((source_path != image_path, normalized.format, normalized.mode, normalized.size))
        return ImageOcrResult(engine_available=True)

    monkeypatch.setattr(service, "_extract_image_text", fake_extract)

    service.extract_image_text(image_path)

    assert called_from == ["MainThread"]
    assert normalized_inputs == [(True, "PNG", "RGB", (3, 2))]


def test_scanner_cancel_hard_stops_only_the_selected_running_task(tmp_path: Path) -> None:
    """Cancelling one running scan terminates its process and preserves siblings."""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-cancel.db'}")
    SQLModel.metadata.create_all(engine)
    service = ScannerService(
        engine=engine,
        config=AgentConfig(),
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    selected = service.create_file(user_id="u1", filename="selected.txt", content=b"one", ocr_enabled=False)
    other = service.create_file(user_id="u1", filename="other.txt", content=b"two", ocr_enabled=False)
    process_context = multiprocessing.get_context("spawn")
    selected_process = process_context.Process(target=time.sleep, args=(30,))
    selected_process.start()
    selected_pid = selected_process.pid
    other_process = _FakeProcess()
    service._processes = {selected.scan_id: selected_process, other.scan_id: other_process}  # type: ignore[assignment]
    with Session(engine) as db:
        record = db.get(ScannerRecord, selected.scan_id)
        assert record is not None
        record.status = "running"
        db.add(record)
        db.commit()

    cancelled = service.cancel(user_id="u1", scan_id=selected.scan_id)

    assert cancelled.status == "cancelled"
    assert cancelled.stage_label == "已终止"
    assert selected_pid not in {process.pid for process in multiprocessing.active_children()}
    assert other_process.terminated is False
    assert service.get_scan(user_id="u1", scan_id=other.scan_id).status == "queued"


def test_scanner_retries_one_access_violation_in_safe_ocr_mode_then_fails(tmp_path: Path) -> None:
    """A native Windows OCR crash gets one bounded low-resolution retry only."""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-native-retry.db'}")
    SQLModel.metadata.create_all(engine)
    service = ScannerService(
        engine=engine,
        config=AgentConfig(),
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    created = service.create_file(user_id="u1", filename="large.jpg", content=b"image", ocr_enabled=True)
    with Session(engine) as db:
        record = db.get(ScannerRecord, created.scan_id)
        assert record is not None
        record.status = "running"
        db.add(record)
        db.commit()

    service._processes[created.scan_id] = _FakeProcess(alive=False, exitcode=0xC0000005)  # type: ignore[assignment]
    service._reap_finished_processes()

    first = service.get_scan(user_id="u1", scan_id=created.scan_id)
    assert first.status == "queued"
    assert created.scan_id in service._safe_mode_scans

    with Session(engine) as db:
        record = db.get(ScannerRecord, created.scan_id)
        assert record is not None
        record.status = "running"
        db.add(record)
        db.commit()
    service._processes[created.scan_id] = _FakeProcess(alive=False, exitcode=0xC0000005)  # type: ignore[assignment]
    service._reap_finished_processes()

    second = service.get_scan(user_id="u1", scan_id=created.scan_id)
    assert second.status == "failed"
    assert "3221225477" in second.error
    assert created.scan_id not in service._safe_mode_scans


def test_scanner_projection_preserves_fractional_backend_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """扫描器不得把清洗流水线的细粒度进度截断为整数。"""

    service = object.__new__(ScannerService)
    captured: dict[str, object] = {}
    monkeypatch.setattr(service, "_set_progress", lambda scan_id, **payload: captured.update(payload))

    service._projection_progress(
        "scan-1",
        {"overall_progress": 12.5, "stage": "ocr", "stage_label": "正在分析版面"},
        4,
        48,
    )

    assert captured["progress"] == 9.5
    assert captured["label"] == "正在分析版面"


def test_scanner_worker_uses_parent_vlm_config_snapshot_without_settings_service() -> None:
    """Spawn 子进程必须从任务上下文读取 Key，不能依赖被置空的 SettingsService。"""

    service = object.__new__(ScannerService)
    service.settings_service = None
    snapshot = {"enabled": True, "configured": True, "api_key": "worker-key", "model": "vlm"}

    resolved = service._vlm_config_from_context({"user_id": "u1", "vlm_config": snapshot})

    assert resolved == snapshot
    assert resolved is not snapshot


def test_scanner_claim_attaches_user_vlm_config_to_spawn_context(tmp_path: Path) -> None:
    """父调度器领取联网任务时必须把用户 Key 放入传给 spawn worker 的上下文。"""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-vlm-context.db'}")
    SQLModel.metadata.create_all(engine)
    service = ScannerService(
        engine=engine,
        config=AgentConfig(),
        settings_service=_OnlineSettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    service.create_file(user_id="u1", filename="online.txt", content=b"text", ocr_enabled=False, online_enabled=True)

    job = service._claim_next()

    assert job is not None
    assert job["context"]["vlm_config"]["api_key"] == "worker-key"


def test_scanner_docx_no_ocr_renders_embedded_image_in_document_order(tmp_path: Path) -> None:
    """DOCX No OCR 投影应以内嵌图片节点替换文本引用，并保留文档流顺序。"""

    root = tmp_path / "knowledge"
    root.mkdir()
    docx_path = tmp_path / "with-image.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>图片前文本</w:t></w:r></w:p>'
            '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
            '<w:p><w:r><w:t>图片后文本</w:t></w:r></w:p>'
            '</w:body></w:document>',
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/image1.png"/></Relationships>',
        )
        archive.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n")

    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-docx.db'}")
    SQLModel.metadata.create_all(engine)
    service = ScannerService(
        engine=engine,
        config=AgentConfig(),
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
    )
    try:
        created = service.create_file(user_id="u1", filename=docx_path.name, content=docx_path.read_bytes(), ocr_enabled=False)
        deadline = time.monotonic() + 20
        current = created
        while current.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            current = service.get_scan(user_id="u1", scan_id=created.scan_id)

        image_markdown = "![image1.png](./assets/image1.png)"
        assert current.status == "finished", current.error
        assert "[DOCX 图片引用:" not in current.no_ocr_markdown
        assert current.no_ocr_markdown.count(image_markdown) == 1
        assert current.no_ocr_markdown.index("图片前文本") < current.no_ocr_markdown.index(image_markdown)
        assert current.no_ocr_markdown.index(image_markdown) < current.no_ocr_markdown.index("图片后文本")
        assert (root / current.assets[0]).is_file()
    finally:
        service.stop()


def test_scanner_finishes_docx_and_pdf_with_blank_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DOCX 与 PDF 中的纯空白图片都应快速结束，且不得启动 OCR 流水线。"""

    blank_buffer = io.BytesIO()
    Image.new("RGB", (512, 512), "white").save(blank_buffer, format="PNG")
    blank_png = blank_buffer.getvalue()
    docx_buffer = io.BytesIO()
    with zipfile.ZipFile(docx_buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:body>'
            '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
            '</w:body></w:document>',
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/blank.png"/></Relationships>',
        )
        archive.writestr("word/media/blank.png", blank_png)

    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_image(page.rect, stream=blank_png)
    pdf_bytes = pdf.tobytes()
    pdf.close()
    monkeypatch.setattr(
        ImageOcrService,
        "_get_pipeline",
        lambda self: (_ for _ in ()).throw(AssertionError("blank image must bypass OCR pipeline")),
    )

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-blank-images.db'}")
    SQLModel.metadata.create_all(engine)
    service = ScannerService(
        engine=engine,
        config=AgentConfig(),
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
    )
    try:
        for filename, content in (("blank.docx", docx_buffer.getvalue()), ("blank.pdf", pdf_bytes)):
            created = service.create_file(user_id="u1", filename=filename, content=content, ocr_enabled=True)
            deadline = time.monotonic() + 20
            current = created
            while current.status in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.05)
                current = service.get_scan(user_id="u1", scan_id=created.scan_id)

            assert current.status == "finished", f"{filename}: {current.error}"
            assert current.progress == 100
    finally:
        service.stop()


def test_scanner_text_projection_draft_save_export_and_delete(tmp_path: Path) -> None:
    """Exercise the complete terminal lifecycle without loading OCR models."""

    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner.db'}")
    SQLModel.metadata.create_all(engine)
    config = AgentConfig()
    config.storage.knowledge_dir = root
    service = ScannerService(
        engine=engine,
        config=config,
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
    )
    try:
        created = service.create_file(user_id="u1", filename="notes.txt", content="alpha\nbeta".encode(), ocr_enabled=False)
        assert created.source_path.startswith(f".mw/scan/{created.scan_id}/source/")
        deadline = time.monotonic() + 20
        current = created
        while current.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            current = service.get_scan(user_id="u1", scan_id=created.scan_id)
        assert current.status == "finished", current.error
        assert "alpha" in current.no_ocr_markdown
        assert current.ocr_markdown == ""

        updated = service.update_draft(user_id="u1", scan_id=created.scan_id, variant="no_ocr", content="# Edited\n")
        assert updated.no_ocr_markdown == "# Edited\n"
        saved = service.save_to_knowledge(user_id="u1", scan_id=created.scan_id, variant="no_ocr", conflict_strategy="overwrite")
        assert saved["path"] == "notes.md"
        assert (root / "notes.md").read_text(encoding="utf-8") == "# Edited\n"

        filename, media_type, payload = service.export_payload(user_id="u1", scan_id=created.scan_id, variant="no_ocr")
        assert filename == "notes.zip"
        assert media_type == "application/zip"
        assert payload.startswith(b"PK")
        batch_filename, batch_media_type, batch_payload = service.export_batch_payload(
            user_id="u1",
            items=[(created.scan_id, "no_ocr")],
        )
        assert batch_filename == "scanner-batch.zip"
        assert batch_media_type == "application/zip"
        with zipfile.ZipFile(io.BytesIO(batch_payload)) as batch_archive:
            assert any(name.endswith("/notes.md") for name in batch_archive.namelist())

        assert service.delete_scan(user_id="u1", scan_id=created.scan_id)
        assert not (root / ".mw" / "scan" / created.scan_id).exists()

        image = service.create_file(user_id="u1", filename="diagram.png", content=b"not-a-real-png", ocr_enabled=False)
        deadline = time.monotonic() + 20
        image_result = image
        while image_result.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            image_result = service.get_scan(user_id="u1", scan_id=image.scan_id)
        assert image_result.status == "finished", image_result.error
        assert "![diagram](./assets/diagram.png)" in image_result.no_ocr_markdown
        assert len(image_result.assets) == 1

        with pytest.raises(ValueError, match="private or local"):
            service.create_url(user_id="u1", url="http://127.0.0.1/private", ocr_enabled=False)
    finally:
        service.stop()


def test_scanner_persists_structured_ocr_markdown(tmp_path: Path, monkeypatch: object) -> None:
    """扫描器 OCR 版本必须保留表格 HTML 和公式 LaTeX，并移除原图节点。"""

    monkeypatch.setattr(
        ImageOcrService,
        "extract_image_text",
        lambda self, source_path, progress_callback=None: ImageOcrResult(  # noqa: ARG005
            content="# 实验清单\n\n<table><tr><td>样品</td><td>42</td></tr></table>\n\n$$E=mc^2$$",
            has_text=True,
            word_count=3,
            average_confidence=0.97,
            engine_available=True,
            blocks=[{
                "page": 1, "type": "table", "content": "<table><tr><td>样品</td><td>42</td></tr></table>",
                "bbox": [12.0, 80.0, 640.0, 320.0], "id": 1, "order": 0,
            }],
            page_count=1,
            table_count=1,
            formula_count=1,
            layout_labels=["doc_title", "formula", "table"],
        ),
    )
    root = tmp_path / "knowledge"
    root.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner.db'}")
    SQLModel.metadata.create_all(engine)
    config = AgentConfig()
    config.storage.knowledge_dir = root
    service = ScannerService(
        engine=engine,
        config=config,
        settings_service=_SettingsStub(root),  # type: ignore[arg-type]
        knowledge_library_service=_KnowledgeStub(root),  # type: ignore[arg-type]
        autostart=False,
    )
    try:
        created = service.create_file(
            user_id="u1",
            filename="structured.png",
            content=b"fake-image",
            ocr_enabled=True,
        )
        service._process(created.scan_id, service._context("u1"))
        deadline = time.monotonic() + 8
        current = created
        while current.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            current = service.get_scan(user_id="u1", scan_id=created.scan_id)

        assert current.status == "finished", current.error
        assert "![structured](./assets/structured.png)" in current.no_ocr_markdown
        assert "<table><tr><td>样品</td><td>42</td></tr></table>" in current.ocr_markdown
        assert "$$E=mc^2$$" in current.ocr_markdown
        assert "![structured]" not in current.ocr_markdown
        assert current.ocr_blocks[0]["type"] == "table"
        assert current.ocr_blocks[0]["bbox"] == [12.0, 80.0, 640.0, 320.0]
    finally:
        service.stop()
