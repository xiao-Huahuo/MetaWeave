"""MinerU 精准 API 客户端和共享 frontmatter 路由测试。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import requests

from agent_service.services.document_parsing.mineru import MinerUClient, MinerUNetworkError
from agent_service.core.agent_config import AgentConfig
from agent_service.services.document_parsing.mineru import MinerUParseResult
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService


def _result_zip() -> bytes:
    """创建包含 Markdown 与标准 0–1000 坐标内容列表的最小结果。"""

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("demo/full.md", "# MinerU\n\n正文\n\n![chart](images/chart.png)")
        archive.writestr("demo/images/chart.png", b"image-bytes")
        archive.writestr(
            "demo/demo_content_list.json",
            json.dumps([{"type": "text", "text": "正文", "bbox": [100, 200, 900, 800], "page_idx": 0}]),
        )
    return payload.getvalue()


class _Response:
    """requests 响应最小替身。"""

    def __init__(self, body: dict | None = None, *, content: bytes = b"") -> None:
        self._body = body or {}
        self.content = content
        self.status_code = 200

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        return None


def test_mineru_precision_upload_poll_and_bbox_normalization(tmp_path: Path, monkeypatch) -> None:
    """精准 API 通过签名上传/批次轮询返回 Markdown 和现有覆盖框合同。"""

    source = tmp_path / "scan.png"
    from PIL import Image

    Image.new("RGB", (200, 100), "white").save(source)
    calls: list[str] = []

    def request(method: str, url: str, **_: object) -> _Response:
        calls.append(f"{method}:{url}")
        if url.endswith("/file-urls/batch"):
            return _Response({"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload.test/file"]}})
        return _Response({"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": "https://download.test/result.zip"}]}})

    monkeypatch.setattr(requests, "request", request)
    monkeypatch.setattr(requests, "put", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response(content=_result_zip()))
    asset_dir = tmp_path / "assets"
    result = MinerUClient({"api_key": "token", "poll_interval_seconds": 0.01}).parse_file(
        source,
        ocr_enabled=True,
        asset_output_dir=asset_dir,
        asset_public_prefix="./assets",
    )

    assert result.markdown.startswith("# MinerU")
    assert result.blocks[0]["bbox"] == [20.0, 20.0, 180.0, 80.0]
    assert result.blocks[0]["page"] == 1
    assert "./assets/chart.png" in result.markdown
    assert (asset_dir / "chart.png").read_bytes() == b"image-bytes"
    assert any("file-urls/batch" in call for call in calls)


def test_mineru_network_failure_is_typed_for_local_fallback(tmp_path: Path, monkeypatch) -> None:
    """只有网络错误才进入调用方的本地回退分支。"""

    source = tmp_path / "demo.txt"
    source.write_text("demo", encoding="utf-8")

    def fail(*_: object, **__: object) -> object:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "request", fail)
    try:
        MinerUClient({"api_key": "token"}).parse_file(source, ocr_enabled=False)
    except MinerUNetworkError:
        pass
    else:
        raise AssertionError("network errors must be classified")


def test_frontmatter_uses_mineru_once_and_reuses_source_hash_cache(tmp_path: Path, monkeypatch) -> None:
    """扫描器/灌库共享入口必须在第二次处理前命中缓存，避免重复计费。"""

    source = tmp_path / "paper.png"
    from PIL import Image

    Image.new("RGB", (100, 80), "white").save(source)
    calls = 0

    def parse(self, source_path: Path, *, ocr_enabled: bool, progress_callback=None, **kwargs) -> MinerUParseResult:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return MinerUParseResult(
            markdown="# 论文\n\nMinerU 正文",
            blocks=[{"page": 1, "type": "text", "content": "MinerU 正文", "bbox": [0, 0, 100, 80], "id": 1, "order": 0}],
            task_id="task-1",
        )

    monkeypatch.setattr(MinerUClient, "parse_file", parse)
    config = AgentConfig()
    service = FrontmatterBootstrapService(
        config=config,
        ocr_enabled=True,
        vlm_config={"enabled": True, "api_key": "token", "model": "vlm"},
        online_enabled=True,
    )
    frontmatter = tmp_path / ".mw" / "frontmatter"
    markdown = tmp_path / ".mw" / "md"
    first, path = service.build_frontmatter_file(source_path=source, knowledge_dir=tmp_path, frontmatter_dir=frontmatter, markdown_dir=markdown)
    second, _ = service.build_frontmatter_file(source_path=source, knowledge_dir=tmp_path, frontmatter_dir=frontmatter, markdown_dir=markdown)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert first.files_written == 1
    assert second.files_skipped == 1
    assert calls == 1
    assert payload["metadata"]["parser_engine"] == "mineru"
    assert payload["metadata"]["parser_model"] == "vlm"


def test_mineru_concurrency_slot_is_shared_between_clients(tmp_path: Path) -> None:
    """独立客户端必须争用同一文件槽位，覆盖扫描与灌库的跨进程合同。"""

    config = {"api_key": "token", "max_concurrency": 1, "timeout_seconds": 0.05, "slot_dir": str(tmp_path / "slots")}
    first = MinerUClient(config)
    second = MinerUClient(config)
    with first._process_slot():
        try:
            with second._process_slot():
                raise AssertionError("the second client must not enter a saturated slot")
        except MinerUNetworkError:
            pass
