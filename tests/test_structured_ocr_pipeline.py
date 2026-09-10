"""
高质量 PaddleOCR 结构化流水线回归测试。

使用说明:
测试只注入假的 PP-StructureV3 构造器和结果，不下载或加载真实模型；用于锁定
MetaWeave 选择的组件、关闭的能力以及结构化 Markdown/块输出合同。
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

from agent_service.core.agent_config import AgentConfig
from agent_service.scripts.download_model import _build_paddleocr_pipeline
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.services.memory.rag.image_ocr import ImageOcrResult
from agent_service.services.memory.rag.ocr_model_progress import OcrModelProgressObserver
from agent_service.services.memory.rag.multimodal_cleaner import MultimodalDocumentCleaner


def _config() -> AgentConfig:
    """返回不创建目录、不加载模型的测试配置。"""

    return AgentConfig.load_config(
        {"ocr": {"enabled": True}},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )


def test_selected_pipeline_uses_high_quality_structure_models() -> None:
    """默认选型必须是已确认的高质量流水线，而不是 mobile/lightweight 组合。"""

    config = _config()

    assert config.ocr.pipeline_model_names == {
        "layout_detection": "PP-DocLayout-L",
        "region_detection": "PP-DocBlockLayout",
        "doc_orientation": "PP-LCNet_x1_0_doc_ori",
        "doc_unwarping": "UVDoc",
        "text_detection": "PP-OCRv5_server_det",
        "textline_orientation": "PP-LCNet_x1_0_textline_ori",
        "text_recognition": "PP-OCRv5_server_rec",
        "table_classification": "PP-LCNet_x1_0_table_cls",
        "wired_table_structure": "SLANeXt_wired",
        "wireless_table_structure": "SLANeXt_wireless",
        "wired_table_cells": "RT-DETR-L_wired_table_cell_det",
        "wireless_table_cells": "RT-DETR-L_wireless_table_cell_det",
        "table_orientation": "PP-LCNet_x1_0_doc_ori",
        "formula_recognition": "PP-FormulaNet_plus-M",
    }
    assert config.ocr.pipeline_feature_flags == {
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_textline_orientation": True,
        "use_table_recognition": True,
        "use_formula_recognition": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "use_region_detection": True,
    }


def test_pipeline_builder_passes_every_selected_component(tmp_path: Path) -> None:
    """构造 PP-StructureV3 时必须显式传入全部模型与开关。"""

    config = _config()
    captured: dict[str, Any] = {}

    class FakePPStructureV3:
        """记录构造参数，禁止真实模型初始化。"""

        def __init__(self, **kwargs: Any) -> None:
            """保存本次流水线构造参数。"""

            captured.update(kwargs)

    pipeline = _build_paddleocr_pipeline(
        PPStructureV3=FakePPStructureV3,
        model_root=tmp_path,
        model_names=config.ocr.pipeline_model_names,
        feature_flags=config.ocr.pipeline_feature_flags,
        device=config.ocr.device,
    )

    assert isinstance(pipeline, FakePPStructureV3)
    assert captured["layout_detection_model_name"] == "PP-DocLayout-L"
    assert captured["wireless_table_structure_recognition_model_name"] == "SLANeXt_wireless"
    assert captured["formula_recognition_model_name"] == "PP-FormulaNet_plus-M"
    assert captured["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert captured["text_recognition_model_name"] == "PP-OCRv5_server_rec"
    assert captured["use_chart_recognition"] is False
    assert captured["use_seal_recognition"] is False
    assert captured["format_block_content"] is True
    assert captured["device"] == "cpu"


def test_structure_result_preserves_markdown_blocks_and_counts(tmp_path: Path, monkeypatch) -> None:
    """扫描结果必须保留阅读顺序、版面框、表格、公式和可信度。"""

    class FakeResult:
        """模拟 PaddleX LayoutParsingResultV2 的公开结果属性。"""

        markdown = {
            "markdown_texts": "# 实验报告\n\n<table><tr><td>项目</td><td>数值</td></tr></table>\n\n$$E=mc^2$$",
        }
        json = {
            "res": {
                "page_index": 0,
                "width": 800,
                "height": 1200,
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "实验报告",
                        "block_bbox": [20, 10, 500, 80],
                        "block_id": 3,
                        "block_order": 0,
                    },
                    {
                        "block_label": "table",
                        "block_content": "<table><tr><td>项目</td><td>数值</td></tr></table>",
                        "block_bbox": [20, 100, 500, 300],
                        "block_id": 4,
                        "block_order": 1,
                    },
                    {
                        "block_label": "formula",
                        "block_content": "E=mc^2",
                        "block_bbox": [20, 320, 260, 380],
                        "block_id": 5,
                        "block_order": 2,
                    },
                ],
                "overall_ocr_res": {
                    "rec_texts": ["实验报告", "项目"],
                    "rec_scores": [0.98, 0.92],
                },
                "table_res_list": [{"table_region_id": 1}],
                "formula_res_list": [{"formula_region_id": 1}],
            }
        }

    class FakePipeline:
        """返回单页结构化结果并记录正式推理开关。"""

        def __init__(self) -> None:
            """初始化推理参数记录。"""

            self.kwargs: dict[str, Any] = {}

        def predict(self, **kwargs: Any) -> list[FakeResult]:
            """记录推理开关并返回固定结构页面。"""

            self.kwargs = kwargs
            return [FakeResult()]

    source = tmp_path / "scan.png"
    source.write_bytes(b"fake")
    pipeline = FakePipeline()
    service = ImageOcrService(config=_config(), enabled=True)
    monkeypatch.setattr(service, "_get_pipeline", lambda: pipeline)

    result = service.extract_image_text(source)

    assert result.has_text is True
    assert result.content.startswith("# 实验报告")
    assert result.word_count == 2
    assert result.average_confidence == 0.95
    assert result.page_count == 1
    assert result.table_count == 1
    assert result.formula_count == 1
    assert result.layout_labels == ["doc_title", "formula", "table"]
    assert result.blocks[1] == {
        "page": 1,
        "type": "table",
        "content": "<table><tr><td>项目</td><td>数值</td></tr></table>",
        "bbox": [20.0, 100.0, 500.0, 300.0],
        "id": 4,
            "order": 1,
            "page_width": 800.0,
            "page_height": 1200.0,
        }
    assert pipeline.kwargs["use_table_recognition"] is True
    assert pipeline.kwargs["use_formula_recognition"] is True
    assert pipeline.kwargs["use_chart_recognition"] is False
    assert pipeline.kwargs["use_seal_recognition"] is False


def test_structure_result_preserves_the_preprocessed_page_used_by_layout_boxes() -> None:
    """Overlay consumers must receive the exact page image used for bbox coordinates."""

    output_img = np.zeros((3, 5, 3), dtype=np.uint8)
    raw_result = [{
        "markdown": {"markdown_texts": "正文"},
        "json": {"res": {"page_index": 0, "width": 5, "height": 3, "parsing_res_list": []}},
        "doc_preprocessor_res": {"output_img": output_img},
    }]

    result = ImageOcrService(config=_config(), enabled=True)._collect_structured_result(raw_result)

    with Image.open(io.BytesIO(result.preview_image_png)) as preview:
        assert preview.format == "PNG"
        assert preview.mode == "RGB"
        assert preview.size == (5, 3)


def test_real_ocr_lifecycle_reports_loading_inference_and_result_stages(tmp_path: Path, monkeypatch) -> None:
    """扫描器应看到 OCR 当前在加载、推理还是整理结果，而不是停在一个笼统状态。"""

    class FakePipeline:
        def predict(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
            return [{"markdown": {"markdown_texts": "正文"}, "json": {"res": {"page_index": 0}}}]

    source = tmp_path / "scan.png"
    source.write_bytes(b"fake")
    service = ImageOcrService(config=_config(), enabled=True)
    monkeypatch.setattr(service, "_get_pipeline", lambda: FakePipeline())
    stages: list[dict[str, Any]] = []

    result = service.extract_image_text(source, progress_callback=stages.append)

    assert result.has_text is True
    assert [event["stage"] for event in stages] == ["ocr_model_loading", "ocr_decision", "ocr_result"]
    assert stages[1]["stage_label"] == "模型裁决完成 · 完成 0 / 跳过 8"


def test_image_ocr_returns_when_pipeline_exceeds_configured_timeout(tmp_path: Path, monkeypatch) -> None:
    """无文字图片的流水线未返回时，OCR 必须按服务配置结束等待。"""

    release_pipeline = threading.Event()

    class BlockingPipeline:
        """模拟空白图片触发的长时间无结果推理。"""

        def predict(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
            release_pipeline.wait(timeout=1)
            return []

    source = tmp_path / "blank.png"
    source.write_bytes(b"fake")
    config = _config()
    config.ocr.timeout_seconds = 0.05  # type: ignore[assignment]
    service = ImageOcrService(config=config, enabled=True)
    monkeypatch.setattr(service, "_get_pipeline", lambda: BlockingPipeline())

    started = time.monotonic()
    try:
        result = service.extract_image_text(source)
    finally:
        release_pipeline.set()

    assert time.monotonic() - started < 0.5
    assert result == ImageOcrResult(engine_available=False)


def test_image_ocr_skips_uniform_image_without_loading_pipeline(tmp_path: Path, monkeypatch) -> None:
    """纯色空白图片应直接得到无文字终态，不加载结构化模型。"""

    source = tmp_path / "blank.png"
    Image.new("RGB", (512, 512), "white").save(source)
    service = ImageOcrService(config=_config(), enabled=True)
    monkeypatch.setattr(service, "_get_pipeline", lambda: (_ for _ in ()).throw(AssertionError("pipeline should not load")))

    started = time.monotonic()
    result = service.extract_image_text(source)

    assert time.monotonic() - started < 0.5
    assert result == ImageOcrResult(engine_available=True)


def test_model_observer_advances_only_after_real_child_model_calls_and_restores_objects() -> None:
    """模型完成才推进进度，未被流水线调用的裁决分支统一记为跳过。"""

    class Model:
        def __call__(self, *args: Any, **kwargs: Any):  # noqa: ARG002
            yield {"ok": True}

    class Node:
        pass

    root = Node()
    root.layout_det_model = Model()
    root.general_ocr_pipeline = Node()
    root.general_ocr_pipeline._pipeline = Node()
    root.general_ocr_pipeline._pipeline.text_det_model = Model()
    root.general_ocr_pipeline._pipeline.textline_orientation_model = Model()
    root.general_ocr_pipeline._pipeline.text_rec_model = Model()
    outer = Node()
    outer.paddlex_pipeline = Node()
    outer.paddlex_pipeline._pipeline = root
    original_layout = root.layout_det_model
    events: list[dict[str, Any]] = []

    with OcrModelProgressObserver(outer, events.append):
        list(root.layout_det_model([]))
        list(root.general_ocr_pipeline._pipeline.text_det_model([1]))
        list(root.general_ocr_pipeline._pipeline.textline_orientation_model([1]))
        list(root.general_ocr_pipeline._pipeline.text_rec_model([1]))

    assert events[0]["status"] == "running" and events[0]["progress"] == 0.0
    assert events[1]["status"] == "completed" and events[1]["progress"] == 12.5
    assert any(event["stage_label"].startswith("正在运行文字识别模型 · 1/1 行") for event in events)
    assert events[-1]["progress"] == 100.0
    assert events[-1]["completed"] == 4
    assert events[-1]["skipped"] == 4
    assert root.layout_det_model is original_layout


def test_image_projection_persists_structure_metadata(tmp_path: Path) -> None:
    """统一灌库结果必须携带可追溯版面块，而不只留下渲染后的 Markdown。"""

    class FakeOcrService:
        """返回包含一张表格的稳定结构结果。"""

        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            """验证输入存在并返回结构化 OCR 结果。"""

            assert source_path.is_file()
            return ImageOcrResult(
                content="# 清单\n\n<table><tr><td>A</td></tr></table>",
                has_text=True,
                word_count=2,
                average_confidence=0.96,
                engine_available=True,
                blocks=[{
                    "page": 1, "type": "table", "content": "<table><tr><td>A</td></tr></table>",
                    "bbox": [10.0, 20.0, 300.0, 200.0], "id": 1, "order": 0,
                }],
                page_count=1,
                table_count=1,
                formula_count=0,
                layout_labels=["table"],
            )

    source = tmp_path / "table.png"
    source.write_bytes(b"fake")
    cleaned = MultimodalDocumentCleaner(
        ocr_enabled=True,
        image_ocr_service=FakeOcrService(),
    ).clean(source_path=source, title="table")

    assert cleaned.sections[0].content.startswith("# 清单")
    assert cleaned.metadata["ocr_table_count"] == 1
    assert cleaned.metadata["ocr_layout_labels"] == ["table"]
    assert cleaned.metadata["ocr_blocks"][0]["bbox"] == [10.0, 20.0, 300.0, 200.0]


def test_structure_pipeline_inference_is_globally_serialized(tmp_path: Path, monkeypatch) -> None:
    """扫描器、灌库和附件共享模型时不得同时进入 PP-StructureV3 推理。"""

    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    call_count = 0

    class FakePipeline:
        """用事件屏障暴露两个调用是否发生重叠。"""

        def predict(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
            """阻塞第一次调用，观察第二次调用能否越过全局门禁。"""

            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_started.set()
                assert release_first.wait(timeout=2)
            else:
                second_started.set()
            return [{
                "markdown": {"markdown_texts": "正文"},
                "json": {"res": {"page_index": 0, "parsing_res_list": []}},
            }]

    source = tmp_path / "scan.png"
    source.write_bytes(b"fake")
    service = ImageOcrService(config=_config(), enabled=True)
    monkeypatch.setattr(service, "_get_pipeline", lambda: FakePipeline())
    first = threading.Thread(target=service.extract_image_text, args=(source,))
    second = threading.Thread(target=service.extract_image_text, args=(source,))

    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    time.sleep(0.05)
    assert second_started.is_set() is False
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert first.is_alive() is False
    assert second.is_alive() is False
    assert second_started.is_set() is True
