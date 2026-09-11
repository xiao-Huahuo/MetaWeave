"""MinerU 精准 API 客户端。

本模块负责签名上传、异步轮询、ZIP/Markdown/布局结果读取和公开限制校验。
它不负责切片、向量化或知识图谱；调用方只得到标准 Markdown 与 OCR 块。
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import uuid
import zipfile
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import requests

MINERU_SUPPORTED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".html", ".htm",
}


class MinerUError(RuntimeError):
    """MinerU 返回业务失败或无法解析的响应。"""


class MinerUNetworkError(MinerUError):
    """无法连接 MinerU；调用方可以按产品规则回退本地。"""


class MinerUAuthError(MinerUError):
    """MinerU Token 缺失、失效或无权限；不得伪装成断网回退。"""


@dataclass(slots=True)
class MinerUParseResult:
    """共享 frontmatter 层消费的 MinerU 解析结果。"""

    markdown: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    task_id: str = ""


class _MinuteLimiter:
    """进程内滑动窗口限流器，避免单个 worker 违反官方分钟频控。"""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        """在不持锁执行网络 I/O 的前提下等待一个请求配额。"""

        while True:
            delay = 0.0
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return
                delay = max(0.01, 60 - (now - self._calls[0]))
            time.sleep(delay)


class MinerUClient:
    """使用一份用户生效配置调用 MinerU 精准 API。"""

    _limiter_lock = threading.Lock()
    _limiters: dict[tuple[str, str, int], _MinuteLimiter] = {}

    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.base_url = str(config.get("base_url") or "https://mineru.net").rstrip("/")
        self.api_key = str(config.get("api_key") or "").strip()
        self.timeout = float(config.get("timeout_seconds") or 300)
        self.poll_interval = float(config.get("poll_interval_seconds") or 3)
        self._submit_limiter = self._shared_limiter("submit", int(config.get("submit_rate_per_minute") or 300))
        self._result_limiter = self._shared_limiter("result", int(config.get("result_rate_per_minute") or 1000))

    def parse_file(
        self,
        source_path: Path,
        *,
        ocr_enabled: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> MinerUParseResult:
        """在用户配置的并发槽位内执行本地文件精准解析。"""

        with self._process_slot():
            return self._parse_file(
                source_path,
                ocr_enabled=ocr_enabled,
                progress_callback=progress_callback,
                asset_output_dir=asset_output_dir,
                asset_public_prefix=asset_public_prefix,
            )

    def _parse_file(
        self,
        source_path: Path,
        *,
        ocr_enabled: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> MinerUParseResult:
        """上传一个本地文件，轮询精准解析任务并读取 Markdown/布局结果。"""

        if not self.api_key:
            raise MinerUAuthError("未配置 MinerU API Key")
        size = source_path.stat().st_size
        if size > int(self.config.get("max_file_bytes") or 200 * 1024 * 1024):
            raise MinerUError("文件超过 MinerU 精准 API 大小上限")
        self._validate_pdf_pages(source_path)
        data_id = source_path.stem[:96]
        model = "MinerU-HTML" if source_path.suffix.lower() in {".html", ".htm"} else str(self.config.get("model") or "vlm")
        payload = {
            "files": [{"name": source_path.name, "data_id": data_id}],
            "model_version": model,
            "is_ocr": bool(ocr_enabled),
            "enable_formula": True,
            "enable_table": True,
        }
        created = self._request_json("post", "/api/v4/file-urls/batch", json=payload, submit=True)
        batch_id = str(created.get("batch_id") or "")
        file_urls = created.get("file_urls") or []
        if not batch_id or not isinstance(file_urls, list) or not file_urls:
            raise MinerUError("MinerU 未返回批次或签名上传地址")
        self._emit(progress_callback, "vlm_upload", "正在上传至 MinerU")
        try:
            with source_path.open("rb") as source:
                response = requests.put(str(file_urls[0]), data=source, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MinerUNetworkError("无法上传文件到 MinerU") from exc
        self._emit(progress_callback, "vlm_pending", "MinerU 正在解析")
        result = self._poll_batch(batch_id, progress_callback)
        zip_url = str(result.get("full_zip_url") or "")
        if not zip_url:
            raise MinerUError("MinerU 任务完成但未返回结果 ZIP")
        archive = self._download(zip_url)
        parsed = self._read_archive(
            archive,
            source_path=source_path,
            asset_output_dir=asset_output_dir,
            asset_public_prefix=asset_public_prefix,
        )
        parsed.task_id = batch_id
        self._emit(progress_callback, "vlm_completed", "MinerU 解析完成")
        return parsed

    def parse_url(
        self,
        url: str,
        *,
        source_path: Path,
        ocr_enabled: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> MinerUParseResult:
        """在用户配置的并发槽位内执行 URL 精准解析。"""

        with self._process_slot():
            return self._parse_url(
                url,
                source_path=source_path,
                ocr_enabled=ocr_enabled,
                progress_callback=progress_callback,
                asset_output_dir=asset_output_dir,
                asset_public_prefix=asset_public_prefix,
            )

    def _parse_url(
        self,
        url: str,
        *,
        source_path: Path,
        ocr_enabled: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> MinerUParseResult:
        """提交一个公开文档/HTML URL，并读取精准解析结果。"""

        if not self.api_key:
            raise MinerUAuthError("未配置 MinerU API Key")
        model = "MinerU-HTML" if source_path.suffix.lower() in {".html", ".htm"} else str(self.config.get("model") or "vlm")
        created = self._request_json(
            "post",
            "/api/v4/extract/task",
            json={
                "url": url,
                "model_version": model,
                "is_ocr": bool(ocr_enabled),
                "enable_formula": True,
                "enable_table": True,
            },
            submit=True,
        )
        task_id = str(created.get("task_id") or "")
        if not task_id:
            raise MinerUError("MinerU 未返回任务 ID")
        self._emit(progress_callback, "vlm_pending", "MinerU 正在解析")
        result = self._poll_task(task_id, progress_callback)
        zip_url = str(result.get("full_zip_url") or "")
        if not zip_url:
            raise MinerUError("MinerU 任务完成但未返回结果 ZIP")
        parsed = self._read_archive(
            self._download(zip_url),
            source_path=source_path,
            asset_output_dir=asset_output_dir,
            asset_public_prefix=asset_public_prefix,
        )
        parsed.task_id = task_id
        self._emit(progress_callback, "vlm_completed", "MinerU 解析完成")
        return parsed

    @contextmanager
    def _process_slot(self) -> Iterator[None]:
        """通过有界文件租约在扫描器与灌库进程之间共享并发容量。"""

        capacity = max(1, int(self.config.get("max_concurrency") or 2))
        slot_root = Path(str(self.config.get("slot_dir") or Path.cwd() / "runtime" / "locks" / "mineru"))
        slot_root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        lease_ttl = self.timeout * 4 + 60
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        while time.monotonic() < deadline:
            for index in range(capacity):
                lease = slot_root / f"slot-{index}.lease"
                try:
                    descriptor = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    try:
                        if time.time() - lease.stat().st_mtime > lease_ttl:
                            lease.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                try:
                    os.write(descriptor, token.encode("ascii"))
                finally:
                    os.close(descriptor)
                try:
                    yield
                finally:
                    try:
                        if lease.read_text(encoding="ascii") == token:
                            lease.unlink(missing_ok=True)
                    except OSError:
                        pass
                return
            time.sleep(0.1)
        raise MinerUNetworkError("等待 MinerU 并发槽位超时")

    def _shared_limiter(self, kind: str, limit: int) -> _MinuteLimiter:
        """让同一进程内全部任务共享官方分钟频控窗口。"""

        key = (self.base_url, kind, max(1, limit))
        with self._limiter_lock:
            return self._limiters.setdefault(key, _MinuteLimiter(limit))

    def check(self) -> dict[str, object]:
        """使用额度查询验证网络和 Token，不泄露凭据。"""

        if not self.api_key:
            return {"online": False, "authorized": False, "message": "未配置 MinerU API Key"}
        try:
            self._request_json("get", "/api/v4/quota", result=True)
        except MinerUAuthError as exc:
            return {"online": True, "authorized": False, "message": str(exc)}
        except MinerUNetworkError as exc:
            return {"online": False, "authorized": False, "message": str(exc)}
        except MinerUError:
            # 部分个人 Token 不开放 quota；能够收到业务响应仍证明网络与鉴权链可达。
            return {"online": True, "authorized": True, "message": "MinerU 可连接"}
        return {"online": True, "authorized": True, "message": "MinerU 可连接"}

    def _poll_batch(
        self,
        batch_id: str,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        """有界轮询批次，直到单文件进入完成或失败终态。"""

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            payload = self._request_json("get", f"/api/v4/extract-results/batch/{batch_id}", result=True)
            items = payload.get("extract_result") or payload.get("extract_results") or []
            if isinstance(items, dict):
                items = [items]
            if isinstance(items, list) and items:
                item = items[0]
                state = str(item.get("state") or "")
                if state == "done":
                    return dict(item)
                if state == "failed":
                    raise MinerUError(str(item.get("err_msg") or "MinerU 解析失败"))
                self._emit(progress_callback, f"vlm_{state or 'pending'}", f"MinerU {state or 'pending'}")
            time.sleep(self.poll_interval)
        raise MinerUNetworkError("MinerU 解析等待超时")

    def _poll_task(
        self,
        task_id: str,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        """有界轮询单任务。"""

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            item = self._request_json("get", f"/api/v4/extract/task/{task_id}", result=True)
            state = str(item.get("state") or "")
            if state == "done":
                return item
            if state == "failed":
                raise MinerUError(str(item.get("err_msg") or "MinerU 解析失败"))
            self._emit(progress_callback, f"vlm_{state or 'pending'}", f"MinerU {state or 'pending'}")
            time.sleep(self.poll_interval)
        raise MinerUNetworkError("MinerU 解析等待超时")

    def _request_json(self, method: str, path: str, *, submit: bool = False, result: bool = False, **kwargs: Any) -> dict[str, Any]:
        """发送带鉴权的 JSON 请求并将网络、鉴权和业务错误分类。"""

        (self._submit_limiter if submit else self._result_limiter).wait()
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            response = requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise MinerUNetworkError("无法连接 MinerU") from exc
        if response.status_code in {401, 403}:
            raise MinerUAuthError("MinerU API Key 无效或无权限")
        try:
            body = response.json()
        except ValueError as exc:
            raise MinerUError(f"MinerU 返回非 JSON 响应（HTTP {response.status_code}）") from exc
        code = body.get("code")
        if response.status_code >= 400 or code not in {0, "0", None}:
            message = str(body.get("msg") or body.get("message") or f"HTTP {response.status_code}")
            if str(code) in {"A0202", "A0211"}:
                raise MinerUAuthError(message)
            raise MinerUError(message)
        data = body.get("data")
        if not isinstance(data, dict):
            raise MinerUError("MinerU 响应缺少 data")
        return data

    def _download(self, url: str) -> bytes:
        """下载有界结果归档。"""

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MinerUNetworkError("无法下载 MinerU 解析结果") from exc
        return response.content

    def _read_archive(
        self,
        payload: bytes,
        *,
        source_path: Path,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> MinerUParseResult:
        """读取标准结果 ZIP，并把 0–1000 bbox 映射到现有覆盖框合同。"""

        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                markdown_name = next((name for name in names if name.lower().endswith(".md")), "")
                content_name = next((name for name in names if name.lower().endswith("_content_list.json")), "")
                if not markdown_name:
                    raise MinerUError("MinerU ZIP 中没有 Markdown")
                markdown = archive.read(markdown_name).decode("utf-8")
                raw_blocks = json.loads(archive.read(content_name).decode("utf-8")) if content_name else []
                assets: list[dict[str, Any]] = []
                if asset_output_dir is not None:
                    asset_output_dir.mkdir(parents=True, exist_ok=True)
                    image_names = [name for name in names if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}]
                    for index, archive_name in enumerate(image_names, start=1):
                        original_name = Path(archive_name).name
                        target_name = original_name if not (asset_output_dir / original_name).exists() else f"mineru-{index}-{original_name}"
                        target = asset_output_dir / target_name
                        target.write_bytes(archive.read(archive_name))
                        public_url = f"{asset_public_prefix.rstrip('/')}/{target_name}" if asset_public_prefix else target_name
                        markdown = markdown.replace(archive_name, public_url).replace(f"images/{original_name}", public_url)
                        assets.append({"name": target_name, "path": str(target), "public_url": public_url})
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MinerUError("MinerU 结果归档损坏") from exc
        return MinerUParseResult(markdown=markdown, blocks=self._normalize_blocks(raw_blocks, source_path), assets=assets)

    def _normalize_blocks(self, payload: Any, source_path: Path) -> list[dict[str, Any]]:
        """将 MinerU 0–1000 坐标转换成现有页尺寸坐标。"""

        if not isinstance(payload, list):
            return []
        page_sizes = self._page_sizes(source_path)
        blocks: list[dict[str, Any]] = []
        for order, item in enumerate(payload):
            if not isinstance(item, dict) or not isinstance(item.get("bbox"), list) or len(item["bbox"]) != 4:
                continue
            page = int(item.get("page_idx") or 0) + 1
            width, height = page_sizes.get(page, (1000.0, 1000.0))
            try:
                x0, y0, x1, y1 = (float(value) for value in item["bbox"])
            except (TypeError, ValueError):
                continue
            content = item.get("text") or item.get("content") or item.get("table_body") or item.get("equation") or ""
            blocks.append({
                "page": page,
                "type": str(item.get("type") or "text"),
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                "bbox": [x0 * width / 1000, y0 * height / 1000, x1 * width / 1000, y1 * height / 1000],
                "id": item.get("id", order),
                "order": order,
                "page_width": width,
                "page_height": height,
            })
        return blocks

    def _page_sizes(self, source_path: Path) -> dict[int, tuple[float, float]]:
        """读取原件页面尺寸，使 MinerU 覆盖框与既有预览坐标一致。"""

        if source_path.suffix.lower() == ".pdf":
            try:
                import fitz  # type: ignore[import-untyped]

                with fitz.open(source_path) as document:
                    return {index + 1: (float(page.rect.width), float(page.rect.height)) for index, page in enumerate(document)}
            except Exception:
                return {}
        try:
            from PIL import Image

            with Image.open(source_path) as image:
                return {1: (float(image.width), float(image.height))}
        except Exception:
            return {}

    def _validate_pdf_pages(self, source_path: Path) -> None:
        """在上传前拒绝超过用户配置页数的 PDF。"""

        if source_path.suffix.lower() != ".pdf":
            return
        try:
            import fitz  # type: ignore[import-untyped]

            with fitz.open(source_path) as document:
                if document.page_count > int(self.config.get("max_pages") or 600):
                    raise MinerUError("PDF 超过 MinerU 精准 API 页数上限")
        except MinerUError:
            raise
        except Exception:
            return

    @staticmethod
    def _emit(callback: Callable[[dict[str, Any]], None] | None, stage: str, label: str) -> None:
        """联网解析只发布真实阶段，不伪造百分比。"""

        if callback:
            callback({"stage": stage, "stage_label": label, "indeterminate": True})
