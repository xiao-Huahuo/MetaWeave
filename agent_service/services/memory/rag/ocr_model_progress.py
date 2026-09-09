"""Observe PP-StructureV3 child-model decisions without replacing PaddleX logic.

Usage:
Wrap one ``PPStructureV3.predict`` call with ``OcrModelProgressObserver``. The
observer temporarily proxies known PaddleX 3.7 child models, emits start and
completion events, then restores every original object even on failure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

OcrProgressCallback = Callable[[dict[str, Any]], None]

_MODEL_STAGES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("doc_preprocessor_pipeline",), "doc_preprocessor", "文档方向与展平流水线"),
    (("layout_det_model",), "layout_detection", "版面检测模型"),
    (("region_detection_model",), "region_detection", "区域检测模型"),
    (("formula_recognition_pipeline",), "formula_recognition", "公式裁决与识别流水线"),
    (("general_ocr_pipeline", "text_det_model"), "text_detection", "文字检测模型"),
    (("general_ocr_pipeline", "textline_orientation_model"), "textline_orientation", "文字行方向模型"),
    (("general_ocr_pipeline", "text_rec_model"), "text_recognition", "文字识别模型"),
    (("table_recognition_pipeline",), "table_recognition", "表格裁决与结构识别流水线"),
)
OCR_MODEL_STAGE_COUNT = len(_MODEL_STAGES)


def _unwrap_pipeline(value: Any) -> Any:
    """Return the concrete single-device PaddleX pipeline behind wrappers."""

    try:
        return object.__getattribute__(value, "_pipeline")
    except (AttributeError, TypeError):
        return value


class _ObservedModel:
    """Delegate one model while reporting the exact call boundary."""

    def __init__(self, target: Any, key: str, label: str, observer: "OcrModelProgressObserver") -> None:
        self._target = target
        self._key = key
        self._label = label
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        self._observer.model_started(self._key, self._label)
        recognized = False
        processed = 0
        detected = 0
        expected = len(args[0]) if args and hasattr(args[0], "__len__") else 0
        try:
            for item in self._target(*args, **kwargs):
                if isinstance(item, dict):
                    result_key = "formula_res_list" if self._key == "formula_recognition" else "table_res_list"
                    recognized = recognized or bool(item.get(result_key))
                    if self._key == "text_detection":
                        boxes = item.get("dt_polys")
                        detected += len(boxes) if boxes is not None else 0
                processed += 1
                if self._key in {"textline_orientation", "text_recognition"}:
                    self._observer.model_item(self._key, self._label, processed=processed, expected=expected)
                yield item
        except BaseException:
            raise
        else:
            decision_skipped = self._key in {"formula_recognition", "table_recognition"} and not recognized
            detail = detected if self._key == "text_detection" else processed
            self._observer.model_finished(self._key, self._label, skipped=decision_skipped, detail=detail)


class OcrModelProgressObserver(AbstractContextManager["OcrModelProgressObserver"]):
    """Temporarily observe every available model in one PP-StructureV3 call."""

    def __init__(self, pipeline: Any, callback: OcrProgressCallback | None) -> None:
        self.pipeline = _unwrap_pipeline(getattr(pipeline, "paddlex_pipeline", pipeline))
        self.callback = callback
        self.total = OCR_MODEL_STAGE_COUNT
        self.finished: set[str] = set()
        self.skipped: set[str] = set()
        self._last_stream_progress: dict[str, float] = {}
        self._originals: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> "OcrModelProgressObserver":
        if not self.callback:
            return self
        for path, key, label in _MODEL_STAGES:
            parent = self.pipeline
            try:
                for part in path[:-1]:
                    parent = _unwrap_pipeline(getattr(parent, part))
                attribute = path[-1]
                target = getattr(parent, attribute)
            except AttributeError:
                continue
            self._originals.append((parent, attribute, target))
            setattr(parent, attribute, _ObservedModel(target, key, label, self))
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        for parent, attribute, target in reversed(self._originals):
            setattr(parent, attribute, target)
        if exc_type is None and self.callback:
            skipped = len(self.skipped) + self.total - len(self.finished)
            self.callback({
                "status": "decided",
                "progress": 100.0,
                "completed": self.total - skipped,
                "skipped": skipped,
                "total": self.total,
                "stage": "ocr_decision",
                "stage_label": f"模型裁决完成 · 完成 {self.total - skipped} / 跳过 {skipped}",
            })
        return None

    def model_started(self, key: str, label: str) -> None:
        """Publish the active model without advancing completed progress."""

        if self.callback:
            self.callback(self._event("running", key, f"正在运行{label}"))

    def model_item(self, key: str, label: str, *, processed: int, expected: int) -> None:
        """Report real recognition output counts, throttled to one percentage point."""

        if not self.callback or expected <= 0:
            return
        progress = (len(self.finished) + min(processed, expected) / expected) / self.total * 100
        previous = self._last_stream_progress.get(key, -1.0)
        if processed < expected and progress - previous < 1.0:
            return
        self._last_stream_progress[key] = progress
        self.callback({
            **self._event("running", key, label),
            "progress": round(progress, 1),
            "stage_label": f"正在运行{label} · {processed}/{expected} 行 · 已裁决 {len(self.finished)}/{self.total}",
        })

    def model_finished(self, key: str, label: str, *, skipped: bool = False, detail: int = 0) -> None:
        """Advance exactly once after a child model invocation returns."""

        self.finished.add(key)
        if skipped:
            self.skipped.add(key)
        if self.callback:
            status = "skipped" if skipped else "completed"
            suffix = "裁决跳过" if skipped else "完成"
            detail_label = ""
            if key == "text_detection":
                detail_label = f" · 检测到 {detail} 个文字框"
            elif key in {"textline_orientation", "text_recognition"}:
                detail_label = f" · 已处理 {detail} 行"
            self.callback(self._event(status, key, f"{label}{suffix}{detail_label}"))

    def _event(self, status: str, key: str, label: str) -> dict[str, Any]:
        completed = len(self.finished)
        return {
            "status": status,
            "progress": round(completed / self.total * 100, 1),
            "completed": completed,
            "skipped": len(self.skipped),
            "total": self.total,
            "model": key,
            "stage": f"ocr_model_{key}",
            "stage_label": f"{label} · 已裁决 {completed}/{self.total}",
        }
