"""
图片结构化 OCR 工具。

功能说明:
本文件封装 PP-StructureV3 高质量流水线,供扫描器、普通图片、扫描 PDF 和文档内嵌
图片共用。流水线串行完成预处理、版面、文字、表格、公式和阅读顺序解析，并同时
返回 Markdown 与可写入 frontmatter 的版面块。未启用 OCR 或模型不完整时返回空结果。

使用说明:
service = ImageOcrService(config=config)
result = service.extract_image_text(Path("demo.png"))
"""

from __future__ import annotations

import io
import logging
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from PIL import Image, ImageOps

from agent_service.core.agent_config import AgentConfig
from agent_service.scripts.download_model import (
    _build_paddleocr_pipeline,
    _disable_paddleocr_mkldnn_by_default,
    is_paddleocr_pipeline_available,
)
from agent_service.services.memory.rag.ocr_model_progress import (
    OCR_MODEL_STAGE_COUNT,
    OcrModelProgressObserver,
    OcrProgressCallback,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImageOcrResult:
    """
    图片 OCR 结果。

    content: 按图片排版重排后的文本。
    has_text: 是否识别到可信文字。
    word_count: 可信文本片段数量。
    average_confidence: 可信文本片段平均置信度。
    engine_available: OCR 引擎是否可用。
    blocks: 按页码和阅读顺序排列的可序列化版面块。
    page_count/table_count/formula_count: 结构化结果统计。
    layout_labels: 本次结果实际出现的版面类型。
    """

    content: str = ""
    has_text: bool = False
    word_count: int = 0
    average_confidence: float = 0.0
    engine_available: bool = False
    blocks: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    table_count: int = 0
    formula_count: int = 0
    layout_labels: list[str] = field(default_factory=list)
    preview_image_png: bytes = b""


class ImageOcrService:
    """
    图片 OCR 服务。

    config: 全局配置,用于读取 OCR 开关、PaddleOCR 模型名称、语言和置信度阈值。
    """

    _pipeline_cache: dict[tuple[str, ...], Any] = {}
    _pipeline_errors: dict[tuple[str, ...], Exception] = {}
    _pipeline_lock = threading.Lock()
    _inference_lock = threading.Lock()

    def __init__(self, *, config: AgentConfig, enabled: bool | None = None, run_inline: bool = False) -> None:
        """保存配置；进程隔离调用可同步推理，避免遗留原生守护线程。"""

        self.config = config
        self.enabled = config.ocr.enabled if enabled is None else bool(enabled)
        self.run_inline = run_inline

    def extract_image_text(
        self,
        source_path: Path,
        progress_callback: OcrProgressCallback | None = None,
    ) -> ImageOcrResult:
        """
        对单张图片执行 OCR。

        source_path: 图片文件路径。
        """

        if not self.enabled:
            return ImageOcrResult()
        if _is_uniform_image(source_path):
            return ImageOcrResult(engine_available=True)
        timeout_seconds = max(float(self.config.ocr.timeout_seconds), 0.001)
        if self.run_inline:
            try:
                with _normalized_ocr_image(source_path, max_side_pixels=self.config.ocr.input_max_side_pixels) as normalized_source:
                    return self._extract_image_text(normalized_source, progress_callback, timeout_seconds)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                logger.warning("OCR 图片规范化失败: %s | path=%s", exc, source_path)
                return ImageOcrResult(engine_available=False)
        active = threading.Event()
        active.set()
        result_queue: Queue[ImageOcrResult] = Queue(maxsize=1)

        def emit_progress(payload: dict[str, Any]) -> None:
            """停止等待后丢弃迟到进度，避免后台推理继续改写已终止任务。"""

            if active.is_set() and progress_callback:
                progress_callback(payload)

        def run() -> None:
            """在守护线程中隔离可能不返回的第三方原生推理。"""

            result_queue.put(self._extract_image_text(source_path, emit_progress, timeout_seconds))

        threading.Thread(target=run, daemon=True, name="paddleocr-inference").start()
        try:
            return result_queue.get(timeout=timeout_seconds)
        except Empty:
            logger.warning("PaddleOCR 图片推理超时: %.3fs | path=%s", timeout_seconds, source_path)
            return ImageOcrResult(engine_available=False)
        finally:
            active.clear()

    def _extract_image_text(
        self,
        source_path: Path,
        progress_callback: OcrProgressCallback | None,
        timeout_seconds: float,
    ) -> ImageOcrResult:
        """执行一次 OCR；锁等待与外层调用共享同一个有界时限。"""

        acquired = self._inference_lock.acquire(timeout=timeout_seconds)
        if not acquired:
            return ImageOcrResult(engine_available=False)
        try:
            if progress_callback:
                progress_callback({
                    "status": "loading", "progress": 0.0, "completed": 0, "skipped": 0,
                    "total": OCR_MODEL_STAGE_COUNT, "stage": "ocr_model_loading", "stage_label": "正在加载结构化 OCR 模型",
                })
            pipeline = self._get_pipeline()
            if pipeline is None:
                return ImageOcrResult()
            raw_result = self._run_pipeline(
                pipeline=pipeline,
                source_path=source_path,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            logger.warning("PaddleOCR 图片推理失败: %s | path=%s", exc, source_path)
            return ImageOcrResult(engine_available=False)
        finally:
            self._inference_lock.release()

        if progress_callback:
            progress_callback({
                "status": "formatting", "progress": 100.0,
                "stage": "ocr_result", "stage_label": "正在整理结构化 OCR 结果 · 模型裁决已完成",
            })
        structured = self._collect_structured_result(raw_result)
        if structured.content:
            return structured
        items = self._collect_items(raw_result)
        trusted_items = [item for item in items if item["confidence"] >= self.config.ocr.min_confidence]
        if not trusted_items:
            return ImageOcrResult(engine_available=True, preview_image_png=structured.preview_image_png)
        content = self._format_items_as_lines(trusted_items)
        average_confidence = sum(float(item["confidence"]) for item in trusted_items) / len(trusted_items)
        return ImageOcrResult(
            content=content,
            has_text=bool(content.strip()),
            word_count=len(trusted_items),
            average_confidence=average_confidence,
            engine_available=True,
            preview_image_png=structured.preview_image_png,
        )

    def warmup(self) -> None:
        """在独立守护线程中预热 OCR pipeline，不阻塞设置保存或其他业务。"""

        threading.Thread(
            target=self._get_pipeline,
            daemon=True,
            name="paddleocr-load",
        ).start()

    @property
    def loaded(self) -> bool:
        """返回当前配置对应的 OCR pipeline 是否已在共享缓存中。"""

        return self._pipeline_key() in self._pipeline_cache

    @classmethod
    def clear_shared_pipeline(cls) -> None:
        """在删除受管模型时等待当前推理结束并释放全部共享流水线引用。"""

        with cls._inference_lock:
            with cls._pipeline_lock:
                cls._pipeline_cache.clear()
                cls._pipeline_errors.clear()

    def _pipeline_key(self) -> tuple[str, ...]:
        """构造当前 OCR 配置的稳定共享缓存键。"""

        return (
            self.config.ocr.language,
            *self.config.ocr.pipeline_model_names.values(),
            *(str(value) for value in self.config.ocr.pipeline_feature_flags.values()),
            self.config.ocr.device,
            str(self.config.storage.paddleocr_model_dir),
        )

    def _get_pipeline(self) -> Any | None:
        """同步获取可复用的 OCR pipeline，避免首次请求返回假空结果。"""

        from agent_service.core.model_status import ModelState, set_model_state

        model_root = Path(self.config.storage.paddleocr_model_dir)
        if not is_paddleocr_pipeline_available(model_root, self.config.ocr.pipeline_model_names):
            set_model_state("paddleocr", ModelState.AWAITING_DOWNLOAD)
            return None

        key = self._pipeline_key()
        if key in self._pipeline_cache:
            return self._pipeline_cache[key]
        if key in self._pipeline_errors:
            return None

        with self._pipeline_lock:
            if key in self._pipeline_cache:
                return self._pipeline_cache[key]
            if key in self._pipeline_errors:
                return None
            self._load_pipeline(key)
        return self._pipeline_cache.get(key)

    def _load_pipeline(self, key: tuple[str, ...]) -> None:
        """加载并缓存 PaddleOCR pipeline。"""

        from agent_service.core.model_status import ModelState, set_model_state

        _disable_paddleocr_mkldnn_by_default()
        try:
            from paddleocr import PPStructureV3  # type: ignore[import-untyped]
        except ImportError:
            set_model_state("paddleocr", ModelState.ERROR)
            self._pipeline_errors[key] = ImportError("缺少支持 PP-StructureV3 的 PaddleOCR 依赖")
            return
        set_model_state("paddleocr", ModelState.LOADING)
        try:
            self._pipeline_cache[key] = _build_paddleocr_pipeline(
                PPStructureV3=PPStructureV3,
                model_root=Path(self.config.storage.paddleocr_model_dir),
                model_names=self.config.ocr.pipeline_model_names,
                feature_flags=self.config.ocr.pipeline_feature_flags,
                device=self.config.ocr.device,
            )
            set_model_state("paddleocr", ModelState.READY)
        except Exception as exc:
            set_model_state("paddleocr", ModelState.ERROR)
            self._pipeline_errors[key] = exc

    def _run_pipeline(
        self,
        *,
        pipeline: Any,
        source_path: Path,
        progress_callback: OcrProgressCallback | None = None,
    ) -> Any:
        """执行结构化推理并显式关闭未纳入产品范围的图表和印章模块。"""

        with OcrModelProgressObserver(pipeline, progress_callback):
            return list(pipeline.predict(
                input=str(source_path),
                format_block_content=True,
                text_rec_score_thresh=self.config.ocr.min_confidence,
                use_wired_table_cells_trans_to_html=True,
                use_wireless_table_cells_trans_to_html=True,
                use_e2e_wired_table_rec_model=False,
                use_e2e_wireless_table_rec_model=False,
                **self.config.ocr.pipeline_feature_flags,
            ))

    def _collect_structured_result(self, raw_result: Any) -> ImageOcrResult:
        """将 PP-StructureV3 页面结果规整为 Markdown、版面块与统计。"""

        preview_image_png = _preprocessed_preview_png(raw_result)
        markdown_pages: list[str] = []
        blocks: list[dict[str, Any]] = []
        confidences: list[float] = []
        table_count = 0
        formula_count = 0
        page_count = 0
        for fallback_page, node in enumerate(_iter_result_nodes(raw_result), start=1):
            payload = _result_json_payload(node)
            if not payload:
                continue
            page = int(payload.get("page_index") or 0) + 1 if payload.get("page_index") is not None else fallback_page
            page_count = max(page_count, page)
            markdown = _result_markdown(node)
            if markdown:
                markdown_pages.append(markdown.strip())
            for raw_block in payload.get("parsing_res_list") or []:
                block = _normalize_structure_block(
                    raw_block,
                    page=page,
                    page_width=float(payload.get("width") or 0),
                    page_height=float(payload.get("height") or 0),
                )
                if block:
                    blocks.append(block)
            ocr_payload = payload.get("overall_ocr_res") or {}
            scores = ocr_payload.get("rec_scores") or ocr_payload.get("scores") or []
            confidences.extend(
                score for score in (_safe_float(value, default=0.0) for value in scores)
                if score >= self.config.ocr.min_confidence
            )
            table_count += len(payload.get("table_res_list") or [])
            formula_count += len(payload.get("formula_res_list") or [])
        blocks.sort(key=lambda block: (int(block["page"]), int(block["order"])))
        if not markdown_pages and blocks:
            markdown_pages = [str(block["content"]) for block in blocks if str(block["content"]).strip()]
        content = "\n\n".join(part for part in markdown_pages if part).strip()
        if not content:
            return ImageOcrResult(engine_available=True, preview_image_png=preview_image_png)
        labels = sorted({str(block["type"]) for block in blocks})
        return ImageOcrResult(
            content=content,
            has_text=True,
            word_count=len(confidences) or len([block for block in blocks if block["content"]]),
            average_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
            engine_available=True,
            blocks=blocks,
            page_count=page_count or len(markdown_pages),
            table_count=table_count,
            formula_count=formula_count,
            layout_labels=labels,
            preview_image_png=preview_image_png,
        )

    def _collect_items(self, raw_result: Any) -> list[dict[str, Any]]:
        """从 PaddleOCR 不同版本的输出结构中抽取文本、置信度和框坐标。"""

        normalized = _normalize_raw_result(raw_result)
        items: list[dict[str, Any]] = []
        for node in normalized:
            if isinstance(node, dict):
                items.extend(self._collect_items_from_dict(node))
                continue
            if isinstance(node, (list, tuple)):
                items.extend(self._collect_items_from_sequence(node))
        return [item for item in items if str(item.get("text", "")).strip()]

    def _collect_items_from_dict(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """抽取 PaddleOCR 3.x 字典结构中的识别结果。"""

        nested_result = payload.get("res")
        if isinstance(nested_result, dict):
            return self._collect_items_from_dict(nested_result)

        texts = payload.get("rec_texts") or payload.get("texts") or []
        scores = payload.get("rec_scores") or payload.get("scores") or []
        boxes = payload.get("rec_boxes") or payload.get("dt_polys") or payload.get("boxes") or []
        items: list[dict[str, Any]] = []
        for index, text in enumerate(texts):
            items.append(
                {
                    "text": str(text).strip(),
                    "confidence": _float_at(scores, index, default=1.0),
                    "box": _box_at(boxes, index),
                }
            )
        return items

    def _collect_items_from_sequence(self, payload: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        """抽取旧版 PaddleOCR 嵌套列表结构中的识别结果。"""

        items: list[dict[str, Any]] = []
        if len(payload) >= 2 and isinstance(payload[1], (list, tuple)) and len(payload[1]) >= 2:
            text = str(payload[1][0]).strip()
            confidence = _safe_float(payload[1][1], default=1.0)
            items.append({"text": text, "confidence": confidence, "box": payload[0]})
            return items
        for child in payload:
            if isinstance(child, dict):
                items.extend(self._collect_items_from_dict(child))
            elif isinstance(child, (list, tuple)):
                items.extend(self._collect_items_from_sequence(child))
        return items

    @staticmethod
    def _format_items_as_lines(items: list[dict[str, Any]]) -> str:
        """把识别结果按纵向行、横向列重排为文本,表格截图会尽量保留列次序。"""

        enriched = []
        for item in items:
            left, top, height = _box_geometry(item.get("box"))
            enriched.append({**item, "left": left, "top": top, "height": height})
        enriched.sort(key=lambda item: (item["top"], item["left"]))
        lines: list[list[dict[str, Any]]] = []
        for item in enriched:
            if not lines:
                lines.append([item])
                continue
            previous = lines[-1]
            average_height = max(8.0, sum(float(node["height"]) for node in previous) / len(previous))
            if abs(float(item["top"]) - float(previous[0]["top"])) <= average_height * 0.6:
                previous.append(item)
            else:
                lines.append([item])
        formatted_lines = []
        for line in lines:
            ordered = sorted(line, key=lambda item: float(item["left"]))
            formatted_lines.append(" | ".join(str(item["text"]).strip() for item in ordered if str(item["text"]).strip()))
        return "\n".join(line for line in formatted_lines if line).strip()


def _iter_result_nodes(raw_result: Any) -> list[Any]:
    """保留 PaddleX 结果对象本身，以便同时读取 markdown 与 json 属性。"""

    if raw_result is None:
        return []
    if isinstance(raw_result, (list, tuple)):
        return list(raw_result)
    return [raw_result]


def _result_json_payload(node: Any) -> dict[str, Any]:
    """读取 LayoutParsingResultV2 或测试字典中的 JSON `res`。"""

    raw = node.get("json") if isinstance(node, dict) and "json" in node else getattr(node, "json", node)
    if not isinstance(raw, dict):
        return {}
    payload = raw.get("res", raw)
    return payload if isinstance(payload, dict) else {}


def _result_markdown(node: Any) -> str:
    """读取 PaddleX MarkdownMixin 生成的结构化正文。"""

    raw = node.get("markdown") if isinstance(node, dict) and "markdown" in node else getattr(node, "markdown", None)
    if isinstance(raw, dict):
        return str(raw.get("markdown_texts") or raw.get("text") or "")
    return str(raw or "")


def _preprocessed_preview_png(raw_result: Any) -> bytes:
    """Encode the first PaddleX preprocessed page used by layout coordinates."""

    for node in _iter_result_nodes(raw_result):
        try:
            preprocessor = node.get("doc_preprocessor_res")
            output_img = preprocessor.get("output_img") if preprocessor is not None else None
        except (AttributeError, TypeError):
            continue
        if output_img is None or not hasattr(output_img, "shape"):
            continue
        pixels = output_img[:, :, :3][:, :, ::-1] if len(output_img.shape) == 3 and output_img.shape[2] >= 3 else output_img
        image = Image.fromarray(pixels).convert("RGB")
        try:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        finally:
            image.close()
    return b""


def _normalize_structure_block(
    raw_block: Any,
    *,
    page: int,
    page_width: float,
    page_height: float,
) -> dict[str, Any] | None:
    """把版面块转换为可写入 frontmatter JSON 的稳定字段。"""

    if not isinstance(raw_block, dict):
        return None
    label = str(raw_block.get("block_label") or raw_block.get("label") or "").strip()
    content = str(raw_block.get("block_content") or raw_block.get("content") or "").strip()
    if not label and not content:
        return None
    raw_bbox = raw_block.get("block_bbox") or raw_block.get("bbox") or []
    if hasattr(raw_bbox, "tolist"):
        raw_bbox = raw_bbox.tolist()
    bbox = [float(value) for value in raw_bbox] if isinstance(raw_bbox, (list, tuple)) else []
    block_id = raw_block.get("block_id", raw_block.get("id"))
    raw_order = raw_block.get("block_order", raw_block.get("order"))
    order = int(raw_order) if raw_order is not None else int(block_id or 0)
    return {
        "page": page,
        "type": label or "text",
        "content": content,
        "bbox": bbox,
        "id": block_id,
        "order": order,
        "page_width": page_width,
        "page_height": page_height,
    }


def _normalize_raw_result(raw_result: Any) -> list[Any]:
    """将 PaddleOCR 输出规整为可遍历节点列表。"""

    if raw_result is None:
        return []
    if isinstance(raw_result, dict):
        return [raw_result]
    if isinstance(raw_result, (list, tuple)):
        nodes: list[Any] = []
        for item in raw_result:
            if hasattr(item, "json") and isinstance(item.json, dict):
                nodes.append(item.json)
            elif hasattr(item, "to_dict"):
                nodes.append(item.to_dict())
            elif hasattr(item, "__dict__") and item.__dict__:
                nodes.append(item.__dict__)
            else:
                nodes.append(item)
        return nodes
    if hasattr(raw_result, "json") and isinstance(raw_result.json, dict):
        return [raw_result.json]
    if hasattr(raw_result, "to_dict"):
        return [raw_result.to_dict()]
    if hasattr(raw_result, "__dict__") and raw_result.__dict__:
        return [raw_result.__dict__]
    return []


def _float_at(values: Any, index: int, *, default: float) -> float:
    """安全读取列表中的浮点数。"""

    try:
        return _safe_float(values[index], default=default)
    except (IndexError, TypeError):
        return default


def _box_at(values: Any, index: int) -> Any:
    """安全读取列表中的框坐标。"""

    try:
        return values[index]
    except (IndexError, TypeError):
        return None


def _safe_float(value: Any, *, default: float) -> float:
    """安全转换浮点数。"""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _box_geometry(box: Any) -> tuple[float, float, float]:
    """从 PaddleOCR 框坐标中估算 left/top/height。"""

    if not box:
        return 0.0, 0.0, 12.0
    if isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(item, (int, float)) for item in box):
        left, top, right, bottom = [float(item) for item in box]
        return left, top, max(1.0, bottom - top)
    points: list[tuple[float, float]] = []
    if isinstance(box, (list, tuple)):
        for point in box:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((_safe_float(point[0], default=0.0), _safe_float(point[1], default=0.0)))
    if not points:
        return 0.0, 0.0, 12.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(1.0, max(ys) - min(ys))


def _is_uniform_image(source_path: Path) -> bool:
    """识别纯色或全透明空白图，避免为确定无内容的输入加载 OCR。"""

    try:
        with Image.open(source_path) as image:
            rgba = image.convert("RGBA")
            if rgba.getchannel("A").getextrema() == (0, 0):
                return True
            return all(low == high for low, high in rgba.convert("RGB").getextrema())
    except (OSError, ValueError):
        return False


@contextmanager
def _normalized_ocr_image(source_path: Path, *, max_side_pixels: int) -> Iterator[Path]:
    """Decode, orient, and bound one RGB PNG before native OCR receives it."""

    with tempfile.TemporaryDirectory(prefix="metaweave-ocr-") as directory:
        target = Path(directory) / "input.png"
        with Image.open(source_path) as image:
            oriented = ImageOps.exif_transpose(image)
            limit = max(1, int(max_side_pixels))
            if max(oriented.size) > limit:
                oriented.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            if "A" in oriented.getbands():
                rgba = oriented.convert("RGBA")
                normalized = Image.new("RGB", rgba.size, "white")
                normalized.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
            else:
                normalized = oriented.convert("RGB")
            try:
                normalized.save(target, format="PNG")
            finally:
                normalized.close()
        yield target
