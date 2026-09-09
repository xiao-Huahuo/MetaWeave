"""
模型管理聚合状态与真实下载进度测试。

使用说明:
验证管理页所需的模型名称、路径、大小、文件数、启用/内存状态和真实字节
进度全部由后端生成，不允许前端猜测。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from types import ModuleType
from types import SimpleNamespace

import pytest

from agent_service.core.model_status import ModelState, get_model_status, set_model_state
from agent_service.scripts.download_model import (
    MODEL_MARKER_FILE,
    PADDLEOCR_MARKER_FILE,
    PADDLEOCR_PIPELINE_VERSION,
    get_all_download_progress,
    is_model_available,
    has_partial_model_download,
    restore_partial_download_progress,
    model_target_dir,
    reset_download_progress,
    update_download_progress,
)
import agent_service.scripts.download_model as download_module
from agent_service.services.model_management.service import ModelManagementService


class _SettingsStub:
    """提供用户级 OCR 启用状态。"""

    def is_ocr_enabled_for_user(self, *, user_id: str) -> bool:  # noqa: ARG002
        """测试用户启用 OCR。"""

        return True

    def get_model_preferences(self, *, user_id: str) -> dict[str, object]:  # noqa: ARG002
        """测试用户默认不自动下载。"""

        return {"auto_download_enabled": False}


def _complete_hf_model(path: Path, marker: str) -> None:
    """创建满足现有完整性规则的最小 Hugging Face 模型目录。"""

    path.mkdir(parents=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"weight-data")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / MODEL_MARKER_FILE).write_text(marker, encoding="utf-8")


def test_management_reports_real_model_details_and_enabled_state(tmp_path: Path) -> None:
    """管理接口应汇总真实磁盘与运行状态，不依赖前端路径映射。"""

    embedding_root = tmp_path / "models" / "embedding"
    rerank_root = tmp_path / "models" / "rerank"
    local_llm_root = tmp_path / "models" / "local-llm"
    ocr_root = tmp_path / "models" / "ocr"
    embedding_name = "BAAI/test-embedding"
    rerank_name = "BAAI/test-rerank"
    local_model_name = "Qwen/test-local"
    embedding_target = model_target_dir(embedding_name, embedding_root)
    _complete_hf_model(embedding_target, embedding_name)
    ocr_root.mkdir(parents=True)
    pipeline_model_names = {
        "layout_detection": "PP-DocLayout-L",
        "text_detection": "PP-OCRv5_server_det",
        "text_recognition": "PP-OCRv5_server_rec",
        "wired_table_structure": "SLANeXt_wired",
        "wireless_table_structure": "SLANeXt_wireless",
        "formula_recognition": "PP-FormulaNet_plus-M",
    }
    for model_name in pipeline_model_names.values():
        component_dir = ocr_root / model_name
        component_dir.mkdir()
        (component_dir / "inference.yml").write_text(f"model: {model_name}", encoding="utf-8")
    (ocr_root / PADDLEOCR_MARKER_FILE).write_text(json.dumps({
        "pipeline_version": PADDLEOCR_PIPELINE_VERSION,
        "models": pipeline_model_names,
    }), encoding="utf-8")
    config = SimpleNamespace(
        model=SimpleNamespace(
            embedding_model_name=embedding_name,
            rerank_model_name=rerank_name,
            local_model_name=local_model_name,
        ),
        storage=SimpleNamespace(
            embedding_model_dir=embedding_root,
            rerank_model_dir=rerank_root,
            local_model_dir=local_llm_root,
            paddleocr_model_dir=ocr_root,
        ),
        ocr=SimpleNamespace(
            language="ch",
            device="cpu",
            pipeline_model_names=pipeline_model_names,
            pipeline_feature_flags={
                "use_table_recognition": True,
                "use_formula_recognition": True,
                "use_chart_recognition": False,
                "use_seal_recognition": False,
            },
        ),
    )
    set_model_state("embedding", ModelState.READY)
    set_model_state("rerank", ModelState.NOT_DOWNLOADED)
    set_model_state("paddleocr", ModelState.READY)
    set_model_state("local_qwen", ModelState.NOT_DOWNLOADED)
    reset_download_progress("embedding")

    result = ModelManagementService(config=config, settings_service=_SettingsStub()).get_management_status(user_id="u1")
    models = {item["key"]: item for item in result["models"]}

    assert models["embedding"]["name"] == embedding_name
    assert models["embedding"]["path"] == str(embedding_target)
    assert models["embedding"]["size_bytes"] > 0
    assert models["embedding"]["file_count"] == 4
    assert models["embedding"]["enabled"] is True
    assert models["embedding"]["active"] is True
    assert models["rerank"]["downloaded"] is False
    assert models["local_qwen"]["name"] == local_model_name
    assert models["local_qwen"]["role"] == "本地主 Agent、小模型回退与图片理解"
    assert models["local_qwen"]["details"]["device"] == "CPU"
    assert models["paddleocr"]["enabled"] is True
    assert models["paddleocr"]["downloaded"] is True
    assert models["paddleocr"]["label"] == "PaddleOCR 结构化流水线"
    assert models["paddleocr"]["role"] == "扫描文档版面、文字、表格、公式与阅读顺序解析"
    assert models["paddleocr"]["details"]["layout_model"] == "PP-DocLayout-L"
    assert models["paddleocr"]["details"]["table_models"] == "SLANeXt_wired / SLANeXt_wireless"
    assert models["paddleocr"]["details"]["formula_model"] == "PP-FormulaNet_plus-M"
    assert models["paddleocr"]["details"]["supporting_models"] == ""
    assert models["paddleocr"]["details"]["disabled_modules"] == "图表解析 / 印章识别"
    assert models["paddleocr"]["details"]["language"] == "ch"


def test_download_progress_uses_real_bytes_and_honest_unknown_total() -> None:
    """已知总量显示真实百分比；未知总量只显示字节和不确定状态。"""

    update_download_progress(
        "embedding",
        status="downloading",
        stage="files",
        downloaded_bytes=50,
        total_bytes=200,
        message="下载模型文件",
    )
    update_download_progress(
        "paddleocr",
        status="downloading",
        stage="official_models",
        downloaded_bytes=75,
        total_bytes=None,
        message="准备 OCR 模型",
    )

    progress = get_all_download_progress()

    assert progress["embedding"] == {
        "status": "downloading",
        "stage": "files",
        "downloaded_bytes": 50,
        "total_bytes": 200,
        "percent": 25.0,
        "indeterminate": False,
        "message": "下载模型文件",
    }
    assert progress["paddleocr"]["downloaded_bytes"] == 75
    assert progress["paddleocr"]["percent"] is None
    assert progress["paddleocr"]["indeterminate"] is True


def test_paddleocr_download_failure_preserves_real_error_for_management_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """结构化流水线失败后必须保留原始原因，不能只留下通用“处理失败”。"""

    ocr_root = tmp_path / "paddleocr"
    ocr_root.mkdir()
    (ocr_root / "partial.bin").write_bytes(b"partial")
    config = SimpleNamespace(
        storage=SimpleNamespace(paddleocr_model_dir=ocr_root),
        ocr=SimpleNamespace(
            language="ch",
            device="cpu",
            pipeline_model_names={"layout_detection": "PP-DocLayout-L"},
            pipeline_feature_flags={},
        ),
    )
    monkeypatch.setattr(download_module, "ensure_paddleocr_models", lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("PP-StructureV3 requires paddlex[ocr]")
    ))
    reset_download_progress("paddleocr")
    service = ModelManagementService(config=config, settings_service=_SettingsStub())

    with pytest.raises(RuntimeError, match=r"paddlex\[ocr\]"):
        service._download_model("paddleocr")

    progress = get_all_download_progress()["paddleocr"]
    assert progress["status"] == "error"
    assert progress["stage"] == "failed"
    assert progress["downloaded_bytes"] == len(b"partial")
    assert progress["message"] == "PP-StructureV3 requires paddlex[ocr]"


def test_model_completeness_accepts_sharded_qwen_safetensors(tmp_path: Path) -> None:
    """本地 Qwen 的分片 Safetensors 必须被统一下载器识别为完整权重。"""

    target = tmp_path / "qwen"
    target.mkdir()
    (target / MODEL_MARKER_FILE).write_text("Qwen/Qwen3.5-2B", encoding="utf-8")
    (target / "config.json").write_text("{}", encoding="utf-8")
    (target / "tokenizer.json").write_text("{}", encoding="utf-8")
    (target / "model.safetensors-00001-of-00001.safetensors").write_bytes(b"weights")

    assert is_model_available(target) is True


def test_partial_qwen_progress_is_reconstructed_from_incomplete_bytes(tmp_path: Path) -> None:
    """后端重启后应从断点文件和权重索引恢复真实下载比例。"""

    target = tmp_path / "qwen"
    cache = target / ".cache" / "huggingface" / "download"
    cache.mkdir(parents=True)
    index_payload = '{"metadata":{"total_size":400},"weight_map":{}}'
    (target / "model.safetensors.index.json").write_text(index_payload, encoding="utf-8")
    (target / "config.json").write_bytes(b"c" * 20)
    (cache / "weight.incomplete").write_bytes(b"w" * 100)

    assert has_partial_model_download(target) is True

    progress = restore_partial_download_progress("local_qwen", target)

    assert progress["status"] == "downloading"
    assert progress["downloaded_bytes"] >= 120
    expected_total = 400 + len(index_payload.encode("utf-8")) + 20
    assert progress["total_bytes"] == expected_total
    assert progress["percent"] == round(progress["downloaded_bytes"] / expected_total * 100, 1)
    assert progress["message"] == "检测到下载断点，正在恢复模型文件"


def test_huggingface_tracker_observes_real_intermediate_file_bytes(tmp_path: Path, monkeypatch) -> None:
    """下载器必须从实际文件增长得到 25%，而不是定时器伪造百分比。"""

    fake_hub = ModuleType("huggingface_hub")

    class _HfApi:
        """返回一个总大小为 400 字节的仓库。"""

        def model_info(self, model_name: str, *, files_metadata: bool) -> SimpleNamespace:  # noqa: ARG002
            return SimpleNamespace(siblings=[SimpleNamespace(size=400)])

    def snapshot_download(*, repo_id: str, local_dir: str, local_dir_use_symlinks: bool) -> None:  # noqa: ARG001
        target = Path(local_dir)
        (target / "part.bin").write_bytes(b"a" * 100)
        time.sleep(0.9)
        (target / "part.bin").write_bytes(b"a" * 400)

    fake_hub.HfApi = _HfApi  # type: ignore[attr-defined]
    fake_hub.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    observed: list[dict[str, object]] = []
    real_update = download_module.update_download_progress

    def record_progress(model_type: str, **payload: object) -> None:
        real_update(model_type, **payload)  # type: ignore[arg-type]
        observed.append(download_module.get_download_progress(model_type))

    monkeypatch.setattr(download_module, "update_download_progress", record_progress)

    download_module._tracked_hf_download("demo/model", tmp_path / "model", "embedding")

    assert any(item["status"] == "downloading" and item["percent"] == 25.0 for item in observed)
    assert observed[-1]["status"] == "completed"
    assert observed[-1]["percent"] == 100.0


def test_post_startup_initialization_applies_four_independent_model_policies(monkeypatch) -> None:
    """启动成功后的四模型任务必须独立触发，并严格遵守各自加载条件。"""

    config = SimpleNamespace()
    service = ModelManagementService(config=config, settings_service=_SettingsStub())
    calls: list[tuple[str, bool, bool, bool]] = []
    monkeypatch.setattr(
        service,
        "prepare_model_async",
        lambda model, *, user_id, load_after, download_if_missing, prompt_if_missing: calls.append(
            (model, load_after, download_if_missing, prompt_if_missing)
        ) or True,
    )

    result = service.initialize_after_startup(user_id="u1")

    assert result == {"status": "started"}
    assert calls == [
        ("embedding", True, False, True),
        ("rerank", True, False, True),
        ("paddleocr", True, False, True),
        ("local_qwen", False, False, False),
    ]


def test_user_deleted_model_is_not_auto_downloaded_again_until_restart(tmp_path: Path, monkeypatch) -> None:
    """主动删除后本进程必须抑制自动下载，但不写入跨启动抑制状态。"""

    embedding_name = "BAAI/test-embedding"
    embedding_root = tmp_path / "models" / "embedding"
    target = model_target_dir(embedding_name, embedding_root)
    _complete_hf_model(target, embedding_name)
    config = SimpleNamespace(
        model=SimpleNamespace(
            embedding_model_name=embedding_name,
            rerank_model_name="BAAI/test-rerank",
            local_model_name="Qwen/test-local",
        ),
        storage=SimpleNamespace(
            embedding_model_dir=embedding_root,
            rerank_model_dir=tmp_path / "models" / "rerank",
            local_model_dir=tmp_path / "models" / "qwen",
            paddleocr_model_dir=tmp_path / "models" / "ocr",
        ),
    )
    service = ModelManagementService(config=config, settings_service=_SettingsStub())
    downloaded: list[str] = []
    monkeypatch.setattr(service, "_model_is_available", lambda _model: False)
    monkeypatch.setattr(service, "_download_model", lambda model: downloaded.append(model))

    deleted = service.delete_model("embedding", user_id="u1")
    service.prepare_model_async(
        "embedding",
        user_id="u1",
        load_after=False,
        download_if_missing=True,
        prompt_if_missing=False,
    )
    worker = service._workers.get("embedding")
    if worker is not None:
        worker.join(timeout=2)

    assert deleted["deleted"] is True
    assert target.exists() is False
    assert downloaded == []


def test_management_status_reconciles_loaded_provider_cache(monkeypatch) -> None:
    """共享模型已在内存时，任何遗留 loading 状态都必须自愈为 ready。"""

    import agent_service.services.memory.rag.embedding as embedding_module
    import agent_service.services.memory.rag.rerank as rerank_module

    monkeypatch.setattr(embedding_module, "is_shared_embedding_provider_loaded", lambda: True)
    monkeypatch.setattr(rerank_module, "is_shared_rerank_provider_loaded", lambda: True)
    set_model_state("embedding", ModelState.LOADING)
    set_model_state("rerank", ModelState.LOADING)

    ModelManagementService._reconcile_loaded_runtime_states()
    states = get_model_status().to_dict()

    assert states["embedding"] == "ready"
    assert states["rerank"] == "ready"
