"""会话附件异步上传、按需解析与远程视觉工具测试。

上传测试只验证原文件落盘与并行边界；解析测试用假的 OCR/视觉服务，禁止下载或执行
真实模型。知识库文件的统一读取行为由 Agent 工具测试覆盖。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from PIL import Image

from agent_service.core.agent_config import AgentConfig
from agent_service.services.memory.rag.image_ocr import ImageOcrResult, ImageOcrService
from agent_service.services.session_attachment.service import SessionAttachmentService
from agent_service.services.vision.service import VisionUnderstandingResult
from agent_service.tools.builtin.knowledge import read_file, understand_image
from agent_service.tools.runtime_context import clear_tool_runtime, set_tool_runtime
from agent_service.tools.tool_registry import ToolRegistry
from tests.db_test_utils import create_test_engine


class _SettingsStub:
    """提供附件服务需要的 active 知识库和用户级 OCR/识图设置。"""

    def __init__(
        self,
        root: Path,
        *,
        ocr_enabled: bool = False,
        vision_enabled: bool = False,
        vlm_enabled: bool = False,
    ) -> None:
        """保存测试目录和开关。"""

        self.root = root
        self.ocr_enabled = ocr_enabled
        self.vision_enabled = vision_enabled
        self.vlm_enabled = vlm_enabled

    def get_active_knowledge_library(self, *, user_id: str) -> dict[str, str]:  # noqa: ARG002
        """返回测试专用知识库。"""

        return {"library_id": "library-1", "name": "测试库", "knowledge_dir": str(self.root)}

    def is_ocr_enabled_for_user(self, *, user_id: str) -> bool:  # noqa: ARG002
        """返回文档解析使用的 OCR 设置。"""

        return self.ocr_enabled

    def is_vision_understanding_enabled_for_user(self, *, user_id: str) -> bool:  # noqa: ARG002
        """返回用户是否允许原图发送到远程视觉模型。"""

        return self.vision_enabled

    def get_vlm_config(self, *, user_id: str) -> dict[str, object]:  # noqa: ARG002
        """默认关闭 MinerU，按本地解析路径完成隔离测试。"""

        return {
            "enabled": self.vlm_enabled,
            "api_key": "mineru-test-key" if self.vlm_enabled else "",
            "model": "vlm",
        }


class _VisionStub:
    """记录视觉调用参数并返回稳定语义。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.call_count = 0
        self.user_id = ""
        self.ocr_text = ""
        self.prompt = ""

    def understand_image(
        self,
        *,
        user_id: str,
        image_path: Path,
        ocr_text: str,
        prompt: str = "",
    ) -> VisionUnderstandingResult:  # noqa: ARG002
        """模拟远程视觉模型。"""

        self.call_count += 1
        self.user_id = user_id
        self.ocr_text = ocr_text
        self.prompt = prompt
        return VisionUnderstandingResult(text="图中有一条蓝色箭头。", model_name="deepseek-flash")


def _png_bytes(color: str = "white") -> bytes:
    """生成无需测试资源文件的最小 PNG。"""

    buffer = BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _service(tmp_path: Path, *, settings: _SettingsStub | None = None) -> tuple[AgentConfig, object, SessionAttachmentService]:
    """创建使用独立 SQLite 的正式附件服务。"""

    config = AgentConfig.load_config(
        {"storage": {"base_data_dir": str(tmp_path / "runtime"), "sqlite_path": str(tmp_path / "runtime" / "db" / "attachments.db")}},
        load_env=False,
        ensure_directories=True,
        ensure_models=False,
    )
    engine = create_test_engine(f"sqlite:///{tmp_path / 'runtime' / 'db' / 'attachments.db'}")
    service = SessionAttachmentService(
        config=config,
        engine=engine,
        create_tables=False,
        settings_service=settings or _SettingsStub(tmp_path / "knowledge"),  # type: ignore[arg-type]
    )
    return config, engine, service


def _set_runtime(*, config: AgentConfig, engine: object, service: SessionAttachmentService, vision: object | None = None) -> None:
    """为直接工具调用注入正式附件服务和可选视觉 stub。"""

    services: dict[str, object] = {"session_attachment": service}
    if vision is not None:
        services["vision"] = vision
    set_tool_runtime(
        config=config,
        user_id="u1",
        session_id="s1",
        database_engine=engine,  # type: ignore[arg-type]
        settings_service=service.settings_service,
        tool_services=services,
        retrieval_service=SimpleNamespace(),  # type: ignore[arg-type]
        memory_service=SimpleNamespace(engine=engine),  # type: ignore[arg-type]
        embedding_service=SimpleNamespace(),  # type: ignore[arg-type]
    )


def test_unified_read_file_and_remote_image_tools_are_the_only_registered_readers() -> None:
    """注册表只暴露统一读文件工具与独立识图工具。"""

    config = AgentConfig.load_config({}, load_env=False, ensure_directories=False, ensure_models=False)
    registry = ToolRegistry.with_builtin_tools(config=config)

    assert registry.get("read_file") is not None
    assert registry.get("read_file").display_name == "阅读文件"  # type: ignore[union-attr]
    assert registry.get("read_session_attachment") is None
    assert registry.get("read_knowledge_file") is None
    assert registry.get("understand_image") is not None
    assert "远程视觉模型" in registry.get("understand_image").description  # type: ignore[union-attr]


def test_upload_only_persists_raw_attachment_without_starting_parser(tmp_path: Path, monkeypatch: object) -> None:
    """上传阶段只落盘登记，绝不启动 OCR、文档解析或视觉调用。"""

    _config, _engine, service = _service(tmp_path)
    parser_calls = 0

    def unexpected_parser(**_kwargs: object) -> None:
        """记录任何越过上传边界的解析调用。"""

        nonlocal parser_calls
        parser_calls += 1

    monkeypatch.setattr(service, "_parse_to_attachment_text", unexpected_parser)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="raw.png",
        content=_png_bytes(),
        mime_type="image/png",
    )
    record = service.list_session_attachments(user_id="u1", session_id="s1")[0]

    assert parser_calls == 0
    assert uploaded["metadata"]["processing_status"] == "uploaded"
    assert uploaded["metadata"]["content_status"] == "unparsed"
    assert record.text_path == ""
    assert Path(record.path).read_bytes() == _png_bytes()


def test_attachment_context_exposes_read_file_reference_without_automatic_content(tmp_path: Path) -> None:
    """未解析附件只进入目录，引导 Agent 主动调用 read_file。"""

    _config, _engine, service = _service(tmp_path)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="report.txt",
        content=b"private attachment body",
        mime_type="text/plain",
    )

    context = service.build_context(user_id="u1", session_id="s1", current_prompt="请阅读附件")

    assert f"attachment://{uploaded['attachment_id']}" in context.content
    assert "Use read_file" in context.content
    assert "private attachment body" not in context.content
    assert context.injected_count == 0


def test_read_file_parses_session_attachment_once_then_reuses_cached_text(tmp_path: Path, monkeypatch: object) -> None:
    """统一读取工具首次解析会话附件，之后直接复用持久化文本。"""

    config, engine, service = _service(tmp_path)
    ocr_calls = 0

    def fake_ocr(self: ImageOcrService, source_path: Path, **_kwargs: object) -> ImageOcrResult:  # noqa: ARG001
        """返回稳定文字并记录实际解析次数。"""

        nonlocal ocr_calls
        ocr_calls += 1
        return ImageOcrResult(content="按需 OCR 文本", has_text=True, engine_available=True)

    monkeypatch.setattr(ImageOcrService, "extract_image_text", fake_ocr)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="lazy.png",
        content=_png_bytes(),
        mime_type="image/png",
    )
    _set_runtime(config=config, engine=engine, service=service)
    try:
        first = json.loads(read_file(path=f"attachment://{uploaded['attachment_id']}"))
        second = json.loads(read_file(path=f"attachment://{uploaded['attachment_id']}"))
    finally:
        clear_tool_runtime()

    record = service.list_session_attachments(user_id="u1", session_id="s1")[0]
    assert "按需 OCR 文本" in first["content"]
    assert second["content"] == first["content"]
    assert ocr_calls == 1
    assert Path(record.text_path).is_file()
    assert record.metadata_json["content_status"] == "parsed"


def test_understand_image_can_use_raw_upload_without_waiting_for_ocr(tmp_path: Path) -> None:
    """识图工具直接读取原图；未调用 read_file 时 OCR 辅助文本应为空。"""

    settings = _SettingsStub(tmp_path / "knowledge", vision_enabled=True)
    config, engine, service = _service(tmp_path, settings=settings)
    vision = _VisionStub()
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="diagram.png",
        content=_png_bytes("blue"),
        mime_type="image/png",
    )
    _set_runtime(config=config, engine=engine, service=service, vision=vision)
    try:
        result = understand_image(attachment=str(uploaded["attachment_id"]), prompt="箭头是什么颜色？")
    finally:
        clear_tool_runtime()

    assert "蓝色箭头" in result
    assert vision.call_count == 1
    assert vision.ocr_text == ""
    assert vision.prompt == "箭头是什么颜色？"


def test_read_file_reuses_vlm_setting_and_mineru_parser_for_uploaded_documents(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """会话附件按需读取与扫描器共享 OCR/VLM 设置和 MinerU 解析内核。"""

    from agent_service.services.document_parsing import MinerUClient

    settings = _SettingsStub(tmp_path / "knowledge", vlm_enabled=True)
    config, engine, service = _service(tmp_path, settings=settings)

    def fake_parse_file(self: MinerUClient, source_path: Path, **_kwargs: object) -> SimpleNamespace:  # noqa: ARG001
        """模拟 MinerU 返回统一 Markdown 和结构字段。"""

        return SimpleNamespace(
            markdown="# MinerU attachment\n\n远程结构化正文",
            task_id="task-test",
            blocks=[],
            assets=[],
        )

    monkeypatch.setattr(MinerUClient, "parse_file", fake_parse_file)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="mineru.png",
        content=_png_bytes(),
        mime_type="image/png",
    )
    _set_runtime(config=config, engine=engine, service=service)
    try:
        result = json.loads(read_file(path=f"attachment://{uploaded['attachment_id']}"))
    finally:
        clear_tool_runtime()

    record = service.list_session_attachments(user_id="u1", session_id="s1")[0]
    assert "远程结构化正文" in result["content"]
    assert record.metadata_json["multimodal_metadata"]["parser_engine"] == "mineru"


def test_read_file_cursor_continues_cached_attachment_text(tmp_path: Path) -> None:
    """统一读取工具保留 attachment:// 正文的 cursor 分页能力。"""

    config, engine, service = _service(tmp_path)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="notes.txt",
        content="\n".join(f"line-{index}" for index in range(12)).encode("utf-8"),
        mime_type="text/plain",
    )
    _set_runtime(config=config, engine=engine, service=service)
    try:
        full = json.loads(read_file(path=f"attachment://{uploaded['attachment_id']}"))
        page = json.loads(read_file(path=f"attachment://{uploaded['attachment_id']}", cursor=4, end_line=8))
    finally:
        clear_tool_runtime()

    assert page["content"].splitlines() == full["content"].splitlines()[4:8]
    assert page["next_cursor"] == 8


def test_parallel_same_name_uploads_create_distinct_files(tmp_path: Path) -> None:
    """同一会话的并行同名上传使用原子文件创建，不覆盖彼此。"""

    _config, _engine, service = _service(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(
            service.upload_file,
            user_id="u1",
            session_id="s1",
            filename="same.png",
            content=b"first-image",
            mime_type="image/png",
        )
        second_future = pool.submit(
            service.upload_file,
            user_id="u1",
            session_id="s1",
            filename="same.png",
            content=b"second-image",
            mime_type="image/png",
        )
        first = first_future.result(timeout=3)
        second = second_future.result(timeout=3)

    first_path, _, _ = service.get_attachment_file_by_uri(uri=str(first["uri"]))
    second_path, _, _ = service.get_attachment_file_by_uri(uri=str(second["uri"]))
    assert first_path != second_path
    assert {first_path.read_bytes(), second_path.read_bytes()} == {b"first-image", b"second-image"}


def test_concurrent_reads_share_one_attachment_parse_without_holding_registry_lock(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """同一附件并发读取只解析一次，等待者通过 single-flight 事件取得缓存。"""

    _config, _engine, service = _service(tmp_path)
    parser_started = threading.Event()
    release_parser = threading.Event()
    ocr_calls = 0

    def blocked_ocr(self: ImageOcrService, source_path: Path, **_kwargs: object) -> ImageOcrResult:  # noqa: ARG001
        """暂停唯一解析者，让第二个读取者进入有界事件等待。"""

        nonlocal ocr_calls
        ocr_calls += 1
        parser_started.set()
        assert release_parser.wait(timeout=2)
        return ImageOcrResult(content="共享解析结果", has_text=True, engine_available=True)

    monkeypatch.setattr(ImageOcrService, "extract_image_text", blocked_ocr)
    uploaded = service.upload_file(
        user_id="u1",
        session_id="s1",
        filename="shared.png",
        content=_png_bytes(),
        mime_type="image/png",
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            service.read_attachment_text,
            user_id="u1",
            session_id="s1",
            attachment_id=str(uploaded["attachment_id"]),
        )
        assert parser_started.wait(timeout=1)
        second = pool.submit(
            service.read_attachment_text,
            user_id="u1",
            session_id="s1",
            attachment_id=str(uploaded["attachment_id"]),
        )
        release_parser.set()
        first_text = first.result(timeout=3)[1]
        second_text = second.result(timeout=3)[1]

    assert "共享解析结果" in first_text
    assert second_text == first_text
    assert ocr_calls == 1


def test_upload_endpoint_runs_synchronous_persistence_in_parallel_threads(monkeypatch: object) -> None:
    """两个上传请求必须并行进入同步落盘服务，不能相互占用事件循环。"""

    from agent_service.api.rest import agent as agent_rest

    barrier = threading.Barrier(2)
    active_lock = threading.Lock()
    active = 0
    max_active = 0

    class _Service:
        """用屏障证明两个同步调用确实位于不同工作线程。"""

        def upload_file(self, **kwargs: object) -> dict[str, object]:
            """等待另一个请求同时进入后返回附件 DTO。"""

            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait(timeout=2)
                return {"attachment_id": str(kwargs["filename"]), "metadata": {"processing_status": "uploaded"}}
            finally:
                with active_lock:
                    active -= 1

    class _Upload:
        """提供路由所需的最小异步 UploadFile 接口。"""

        def __init__(self, filename: str) -> None:
            self.filename = filename
            self.content_type = "text/plain"

        async def read(self) -> bytes:
            """模拟已由 Starlette 接收完成的上传正文。"""

            return self.filename.encode("utf-8")

    service = _Service()
    monkeypatch.setattr(agent_rest, "_require_attachment_service", lambda: service)

    async def run_uploads() -> None:
        """同时调度两个路由调用。"""

        await asyncio.gather(
            agent_rest.upload_agent_attachment(user_id="u1", session_id="s1", file=_Upload("a.txt")),  # type: ignore[arg-type]
            agent_rest.upload_agent_attachment(user_id="u1", session_id="s1", file=_Upload("b.txt")),  # type: ignore[arg-type]
        )

    asyncio.run(run_uploads())
    assert max_active == 2
