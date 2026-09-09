"""
模型下载脚本。

功能说明:
本文件负责检查并下载本地 Embedding 模型和 ReRank 模型。`AgentConfig.load_config()`
会在加载配置时调用 `ensure_models()` 自动检查模型是否存在;如果模型目录缺失、
缺少模型配置或缺少权重文件,则会使用 `huggingface_hub.snapshot_download()` 下载模型。

手动使用:
可以通过命令行同时指定 Embedding 与 ReRank 的模型名称和本地绝对下载目录:

python -m agent_service.scripts.download_model \
  --embedding-model-name "BAAI/bge-small-zh-v1.5" \
  --embedding-model-dir "D:/Projects/Python/AgentService/runtime/models/embedding" \
  --rerank-model-name "BAAI/bge-reranker-v2-m3" \
  --rerank-model-dir "D:/Projects/Python/AgentService/runtime/models/rerank"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_MARKER_FILE = ".download_complete"
MODEL_CONFIG_FILES = {
    "config.json",
    "modules.json",
    "config_sentence_transformers.json",
}
MODEL_WEIGHT_FILES = {
    "model.safetensors",
    "pytorch_model.bin",
    "model.onnx",
}
MODEL_TOKENIZER_FILES = {
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "vocab.txt",
}
PADDLEOCR_MARKER_FILE = ".paddleocr_download_complete"
PADDLEOCR_PIPELINE_VERSION = "pp-structure-v3-high-quality-v1"

# ---- 下载进度跟踪 ----
_download_progress: dict[str, dict[str, object]] = {}
_download_progress_lock = threading.Lock()


def update_download_progress(
    model_type: str,
    *,
    status: str,
    stage: str,
    downloaded_bytes: int,
    total_bytes: int | None,
    message: str,
) -> None:
    """记录真实落盘字节；总量未知时明确返回不确定进度而非伪百分比。"""

    percent = (
        min(100.0, round(downloaded_bytes / total_bytes * 100, 1))
        if total_bytes and total_bytes > 0
        else None
    )
    with _download_progress_lock:
        _download_progress[model_type] = {
            "status": status,
            "stage": stage,
            "downloaded_bytes": max(0, int(downloaded_bytes)),
            "total_bytes": int(total_bytes) if total_bytes is not None else None,
            "percent": percent,
            "indeterminate": percent is None and status == "downloading",
            "message": message,
        }


def reset_download_progress(model_type: str) -> None:
    """将一个模型进度恢复为空闲状态，供重试和磁盘检测使用。"""

    update_download_progress(
        model_type,
        status="idle",
        stage="idle",
        downloaded_bytes=0,
        total_bytes=None,
        message="",
    )


def get_download_progress(model_type: str) -> dict[str, object]:
    """返回一个模型的结构化下载状态。"""

    with _download_progress_lock:
        return dict(_download_progress.get(model_type, {
            "status": "idle",
            "stage": "idle",
            "downloaded_bytes": 0,
            "total_bytes": None,
            "percent": None,
            "indeterminate": False,
            "message": "",
        }))


def get_all_download_progress() -> dict[str, dict[str, object]]:
    """返回所有已记录模型的结构化真实进度快照。"""

    with _download_progress_lock:
        return {key: dict(value) for key, value in _download_progress.items()}


def _tracked_hf_download(
    model_name: str,
    target_dir: Path,
    model_type: str,
) -> None:
    """从 Hugging Face 下载模型并按文件数估算进度。"""

    from huggingface_hub import HfApi, snapshot_download

    total_bytes: int | None = None
    try:
        info = HfApi().model_info(model_name, files_metadata=True)
        sibling_sizes = [int(item.size) for item in (info.siblings or []) if item.size is not None]
        if sibling_sizes:
            total_bytes = sum(sibling_sizes)
    except Exception:
        pass

    target_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()

    def _observed_download_bytes() -> int:
        """Return resumable model bytes, clamped to known repository payload size."""

        observed = _directory_size(target_dir)
        return min(observed, total_bytes) if total_bytes is not None else observed

    def _track() -> None:
        while not stop_event.is_set():
            update_download_progress(
                model_type,
                status="downloading",
                stage="model_files",
                downloaded_bytes=_observed_download_bytes(),
                total_bytes=total_bytes,
                message="正在下载模型文件",
            )
            stop_event.wait(0.75)

    tracker = threading.Thread(target=_track, daemon=True)
    tracker.start()
    try:
        snapshot_download(
            repo_id=model_name,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
        )
        (target_dir / MODEL_MARKER_FILE).write_text(model_name, encoding="utf-8")
    except Exception:
        update_download_progress(
            model_type,
            status="error",
            stage="failed",
            downloaded_bytes=_observed_download_bytes(),
            total_bytes=total_bytes,
            message="模型下载失败",
        )
        raise
    finally:
        stop_event.set()
        tracker.join(timeout=2)
    downloaded = _observed_download_bytes()
    update_download_progress(
        model_type,
        status="completed",
        stage="completed",
        downloaded_bytes=downloaded,
        total_bytes=total_bytes or downloaded,
        message="模型下载完成",
    )


def _directory_size(path: Path) -> int:
    """计算下载目录当前落盘字节，用于实时进度而非文件数量估算。"""

    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def model_downloaded_bytes(target_dir: Path) -> int:
    """Return logical bytes already present for completed and resumable model files."""

    return _directory_size(target_dir)


def has_partial_model_download(target_dir: Path) -> bool:
    """Return whether Hugging Face left resumable `.incomplete` files for a model."""

    download_dir = target_dir / ".cache" / "huggingface" / "download"
    return download_dir.is_dir() and any(download_dir.glob("*.incomplete"))


def infer_model_repository_total_bytes(target_dir: Path) -> int | None:
    """Infer repository bytes offline from a Safetensors index and downloaded support files."""

    index_path = target_dir / "model.safetensors.index.json"
    if not index_path.is_file():
        return None
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        weight_bytes = int((payload.get("metadata") or {}).get("total_size") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if weight_bytes <= 0:
        return None
    support_bytes = 0
    for item in target_dir.iterdir():
        if not item.is_file() or item.name == MODEL_MARKER_FILE or item.name.endswith(".safetensors"):
            continue
        try:
            support_bytes += item.stat().st_size
        except OSError:
            continue
    return weight_bytes + support_bytes


def restore_partial_download_progress(model_type: str, target_dir: Path) -> dict[str, object]:
    """Rebuild process-local progress from resumable Hugging Face artifacts after restart."""

    downloaded_bytes = _directory_size(target_dir)
    total_bytes = infer_model_repository_total_bytes(target_dir)
    update_download_progress(
        model_type,
        status="downloading",
        stage="resuming",
        downloaded_bytes=downloaded_bytes,
        total_bytes=total_bytes,
        message="检测到下载断点，正在恢复模型文件",
    )
    return get_download_progress(model_type)


def ensure_model(model_name: str, model_dir: Path | str, model_type: str | None = None) -> Path | None:
    """
    检查指定模型是否已经存在,不存在时从 Hugging Face 下载。

    model_name: Hugging Face 模型名称,例如 BAAI/bge-small-zh-v1.5。
    model_dir: 该类模型的本地缓存根目录。
    """

    if not model_name:
        return None

    target_dir = model_target_dir(model_name, model_dir)
    if is_model_available(target_dir):
        logger.info("模型已存在,跳过下载: %s | 路径: %s", model_name, target_dir)
        return target_dir

    _download_from_huggingface(model_name, target_dir, model_type=model_type)
    if not is_model_available(target_dir):
        raise RuntimeError(f"模型下载后仍不完整: {target_dir}")
    return target_dir


def ensure_models(
    *,
    embedding_model_name: str,
    embedding_model_dir: Path | str,
    rerank_model_name: str,
    rerank_model_dir: Path | str,
) -> None:
    """
    检查 Embedding 与 ReRank 模型,缺失时分别下载到对应目录。

    embedding_model_name: Embedding 模型名称。
    embedding_model_dir: Embedding 模型本地缓存根目录。
    rerank_model_name: ReRank 模型名称。
    rerank_model_dir: ReRank 模型本地缓存根目录。
    """

    ensure_model(embedding_model_name, embedding_model_dir)
    ensure_model(rerank_model_name, rerank_model_dir)


def ensure_paddleocr_models(
    *,
    paddleocr_model_dir: Path | str,
    language: str,
    model_names: dict[str, str],
    feature_flags: dict[str, bool],
    device: str = "cpu",
) -> Path:
    """
    下载并验证 PP-StructureV3 高质量结构化流水线的全部启用模型。

    paddleocr_model_dir: PaddleOCR 模型缓存根目录。
    language: OCR 语言参数,中英文场景使用 ch。
    model_names: AgentConfig 统一提供的组件键与模型名称。
    feature_flags: 表格、公式、预处理等流水线开关。
    device: 推理设备,默认 cpu。
    """

    target_root = Path(paddleocr_model_dir).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    _disable_paddleocr_mkldnn_by_default()
    try:
        from paddleocr import PPStructureV3  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("缺少支持 PP-StructureV3 的 paddleocr / paddlepaddle 依赖。") from exc

    logger.info("开始准备 PaddleOCR 结构化流水线: %s", ", ".join(dict.fromkeys(model_names.values())))
    _build_paddleocr_pipeline(
        PPStructureV3=PPStructureV3,
        model_root=target_root,
        model_names=model_names,
        feature_flags=feature_flags,
        device=device,
    )
    for model_name in dict.fromkeys(model_names.values()):
        _sync_paddlex_official_model(
            model_name=model_name,
            target_dir=_paddleocr_model_dir(target_root, model_name),
        )
    if not _all_paddleocr_component_dirs_available(target_root, model_names):
        raise RuntimeError("PP-StructureV3 流水线下载后仍有模型缺失")
    marker_payload = {
        "pipeline_version": PADDLEOCR_PIPELINE_VERSION,
        "language": language,
        "device": device,
        "models": model_names,
        "features": feature_flags,
    }
    (target_root / PADDLEOCR_MARKER_FILE).write_text(
        json.dumps(marker_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("PaddleOCR 结构化流水线准备完成: %s", target_root)
    return target_root


def _build_paddleocr_pipeline(
    *,
    PPStructureV3: object,
    model_root: Path,
    model_names: dict[str, str],
    feature_flags: dict[str, bool],
    device: str,
) -> object:
    """使用受管目录和显式开关创建唯一的 PP-StructureV3 流水线。"""

    _disable_paddleocr_mkldnn_by_default()

    def model_dir(component: str) -> str | None:
        """仅向 PaddleX 传入已经完整同步到 runtime 的组件目录。"""

        return _existing_paddle_model_dir(_paddleocr_model_dir(model_root, model_names[component]))

    return PPStructureV3(
        layout_detection_model_name=model_names["layout_detection"],
        layout_detection_model_dir=model_dir("layout_detection"),
        region_detection_model_name=model_names["region_detection"],
        region_detection_model_dir=model_dir("region_detection"),
        doc_orientation_classify_model_name=model_names["doc_orientation"],
        doc_orientation_classify_model_dir=model_dir("doc_orientation"),
        doc_unwarping_model_name=model_names["doc_unwarping"],
        doc_unwarping_model_dir=model_dir("doc_unwarping"),
        text_detection_model_name=model_names["text_detection"],
        text_detection_model_dir=model_dir("text_detection"),
        textline_orientation_model_name=model_names["textline_orientation"],
        textline_orientation_model_dir=model_dir("textline_orientation"),
        text_recognition_model_name=model_names["text_recognition"],
        text_recognition_model_dir=model_dir("text_recognition"),
        table_classification_model_name=model_names["table_classification"],
        table_classification_model_dir=model_dir("table_classification"),
        wired_table_structure_recognition_model_name=model_names["wired_table_structure"],
        wired_table_structure_recognition_model_dir=model_dir("wired_table_structure"),
        wireless_table_structure_recognition_model_name=model_names["wireless_table_structure"],
        wireless_table_structure_recognition_model_dir=model_dir("wireless_table_structure"),
        wired_table_cells_detection_model_name=model_names["wired_table_cells"],
        wired_table_cells_detection_model_dir=model_dir("wired_table_cells"),
        wireless_table_cells_detection_model_name=model_names["wireless_table_cells"],
        wireless_table_cells_detection_model_dir=model_dir("wireless_table_cells"),
        table_orientation_classify_model_name=model_names["table_orientation"],
        table_orientation_classify_model_dir=model_dir("table_orientation"),
        formula_recognition_model_name=model_names["formula_recognition"],
        formula_recognition_model_dir=model_dir("formula_recognition"),
        format_block_content=True,
        markdown_ignore_labels=["number", "footnote", "header", "header_image", "footer", "footer_image"],
        device=device,
        **feature_flags,
    )


def _disable_paddleocr_mkldnn_by_default() -> None:
    """默认关闭 PaddleX MKLDNN,规避 Windows CPU 下部分 OCR 模型 oneDNN 推理异常。"""

    os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"


def _existing_paddle_model_dir(model_dir: Path | None) -> str | None:
    """仅当本地 PaddleOCR 模型目录已经完整时才传给 PaddleOCR。"""

    if model_dir is None:
        return None
    return str(model_dir) if (model_dir / "inference.yml").is_file() else None


def _paddleocr_model_dir(root: Path, model_name: str) -> Path:
    """把官方模型名称映射到 PaddleOCR 受管根目录下的稳定子目录。"""

    return root / model_name


def _all_paddleocr_component_dirs_available(root: Path, model_names: dict[str, str]) -> bool:
    """检查全部唯一组件目录是否都包含 PaddleX 推理清单。"""

    return all(
        (_paddleocr_model_dir(root, name) / "inference.yml").is_file()
        for name in dict.fromkeys(model_names.values())
    )


def is_paddleocr_pipeline_available(root: Path, model_names: dict[str, str]) -> bool:
    """验证 marker 版本、模型选择和每个受管组件目录。"""

    marker = root / PADDLEOCR_MARKER_FILE
    if not marker.is_file() or not _all_paddleocr_component_dirs_available(root, model_names):
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("pipeline_version") == PADDLEOCR_PIPELINE_VERSION
        and payload.get("models") == model_names
    )


def _sync_paddlex_official_model(*, model_name: str, target_dir: Path) -> None:
    """把 PaddleX 自动下载的官方模型同步到项目 runtime 模型目录。"""

    source_dir = Path.home() / ".paddlex" / "official_models" / model_name
    if not (source_dir / "inference.yml").is_file():
        return
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)


def model_target_dir(model_name: str, model_dir: Path | str) -> Path:
    """
    根据模型名称生成稳定的本地目标目录。

    model_name: Hugging Face 模型名称。
    model_dir: 该类模型的本地缓存根目录。
    """

    safe_name = model_name.replace("/", "__")
    return Path(model_dir).expanduser().resolve() / safe_name


def is_model_available(target_dir: Path) -> bool:
    """
    判断目标目录中是否已经存在完整可用的模型文件。

    target_dir: 某个具体模型的本地目录。
    """

    if not target_dir.exists() or not target_dir.is_dir():
        return False
    file_names = {path.name for path in target_dir.rglob("*") if path.is_file()}
    has_config = bool(file_names & MODEL_CONFIG_FILES)
    has_weight = bool(file_names & MODEL_WEIGHT_FILES) or any(
        name.endswith(".safetensors") for name in file_names
    )
    has_tokenizer = bool(file_names & MODEL_TOKENIZER_FILES)
    has_marker = (target_dir / MODEL_MARKER_FILE).exists()
    return has_marker and has_config and has_weight and has_tokenizer


def _download_from_huggingface(model_name: str, target_dir: Path, model_type: str | None = None) -> None:
    """调用 huggingface_hub 下载模型快照。"""

    if model_type:
        _tracked_hf_download(model_name, target_dir, model_type)
        return

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("缺少 huggingface_hub 依赖,无法自动下载模型。") from exc

    banner = "=" * 57
    logger.info(banner)
    logger.info("开始下载模型: %s", model_name)
    logger.info("目标目录: %s", target_dir)
    logger.info(banner)
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=model_name,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
    )
    (target_dir / MODEL_MARKER_FILE).write_text(model_name, encoding="utf-8")
    logger.info(banner)
    logger.info("模型下载完成: %s", model_name)
    logger.info(banner)


def main() -> None:
    """命令行入口,用于手动下载 Embedding 与 ReRank 两类模型。"""

    parser = argparse.ArgumentParser(description="Download Hugging Face embedding and rerank models.")
    parser.add_argument("--embedding-model-name", required=True)
    parser.add_argument("--embedding-model-dir", required=True)
    parser.add_argument("--rerank-model-name", required=True)
    parser.add_argument("--rerank-model-dir", required=True)
    args = parser.parse_args()
    ensure_models(
        embedding_model_name=args.embedding_model_name,
        embedding_model_dir=args.embedding_model_dir,
        rerank_model_name=args.rerank_model_name,
        rerank_model_dir=args.rerank_model_dir,
    )


if __name__ == "__main__":
    main()
