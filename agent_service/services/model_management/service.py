"""
模型管理状态聚合服务。

使用说明:
设置页、REST 与 gRPC 调用 `get_management_status()` 获取模型名称、路径、大小、
磁盘完整性、内存状态、用户启用状态和真实下载进度，前端不推测业务数据。
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import threading
from typing import Any

from agent_service.core.model_status import ModelState, get_model_status, set_model_state
from agent_service.scripts.download_model import (
    get_download_progress,
    is_model_available,
    is_paddleocr_pipeline_available,
    model_target_dir,
    reset_download_progress,
)

logger = logging.getLogger(__name__)

MODEL_KEYS = ("embedding", "rerank", "paddleocr", "local_qwen")


class ModelManagementService:
    """把四类本地模型的配置、磁盘和运行状态合并为稳定管理 DTO。"""

    def __init__(self, *, config: Any, settings_service: Any) -> None:
        """保存只读服务配置和用户设置依赖。"""

        self.config = config
        self.settings_service = settings_service
        self._worker_lock = threading.Lock()
        self._workers: dict[str, threading.Thread] = {}
        self._auto_download_suppressed: set[tuple[str, str]] = set()

    def initialize_after_startup(self, *, user_id: str) -> dict[str, str]:
        """在前端已显示应用后，为四类模型分别启动独立的验证任务。"""

        preferences = self.settings_service.get_model_preferences(user_id=user_id)
        auto_download = bool(preferences.get("auto_download_enabled"))
        self.prepare_model_async(
            "embedding", user_id=user_id, load_after=True,
            download_if_missing=auto_download, prompt_if_missing=True,
        )
        self.prepare_model_async(
            "rerank", user_id=user_id, load_after=True,
            download_if_missing=auto_download, prompt_if_missing=True,
        )
        self.prepare_model_async(
            "local_qwen", user_id=user_id, load_after=False,
            download_if_missing=auto_download, prompt_if_missing=False,
        )
        return {"status": "started"}

    def prepare_model_async(
        self,
        model: str,
        *,
        user_id: str,
        load_after: bool,
        download_if_missing: bool,
        prompt_if_missing: bool,
    ) -> bool:
        """异步验证一个模型，并按调用方策略下载或加载，绝不阻塞请求线程。"""

        self._validate_model_key(model)

        def prepare() -> None:
            """执行当前模型独占的验证、可选下载和可选加载链路。"""

            if self._model_is_available(model):
                set_model_state(model, ModelState.DOWNLOADED)
                if load_after:
                    self._load_model(model)
                return
            suppressed = (user_id, model) in self._auto_download_suppressed
            if download_if_missing and not suppressed:
                self._download_model(model)
                if load_after:
                    self._load_model(model)
                return
            set_model_state(
                model,
                ModelState.AWAITING_DOWNLOAD if prompt_if_missing else ModelState.NOT_DOWNLOADED,
            )

        silent_qwen_disk_check = model == "local_qwen" and not (
            load_after or download_if_missing or prompt_if_missing
        )
        return self._start_worker(
            model=model,
            state=ModelState.NOT_DOWNLOADED if silent_qwen_disk_check else ModelState.VERIFYING,
            target=prepare,
        )

    def start_download(self, model: str, *, user_id: str, load_after: bool = True) -> bool:
        """在用户确认或自动下载策略授权后启动一个模型下载线程。"""

        self._validate_model_key(model)

        def download() -> None:
            """下载完整模型，并仅在领域条件允许时加载。"""

            self._download_model(model)
            should_load = load_after and (
                model != "paddleocr" or self.settings_service.is_ocr_enabled_for_user(user_id=user_id)
            )
            if should_load:
                self._load_model(model)

        return self._start_worker(model=model, state=ModelState.DOWNLOADING, target=download)

    def delete_model(self, model: str, *, user_id: str) -> dict[str, object]:
        """删除一个模型的受管磁盘目录，并抑制本进程内的再次自动下载。"""

        self._validate_model_key(model)
        with self._worker_lock:
            worker = self._workers.get(model)
            if worker is not None and worker.is_alive():
                raise ValueError("模型任务仍在运行，暂时无法删除")
        target = self._model_path(model)
        removed = target.exists()
        if removed:
            if model == "paddleocr":
                from agent_service.services.memory.rag.image_ocr import ImageOcrService

                ImageOcrService.clear_shared_pipeline()
            shutil.rmtree(target)
        self._auto_download_suppressed.add((user_id, model))
        reset_download_progress(model)
        set_model_state(model, ModelState.NOT_DOWNLOADED)
        return {"model": model, "deleted": removed, "path": str(target)}

    def _start_worker(self, *, model: str, state: ModelState, target: Any) -> bool:
        """为单个模型启动唯一守护线程；不同模型可完全并行。"""

        with self._worker_lock:
            current = self._workers.get(model)
            if current is not None and current.is_alive():
                return False
            set_model_state(model, state)

            def run() -> None:
                """执行模型任务并发布可见错误状态。"""

                try:
                    target()
                except Exception:
                    set_model_state(model, ModelState.ERROR)
                    logger.exception("模型后台任务失败 | model=%s", model)
                finally:
                    with self._worker_lock:
                        self._workers.pop(model, None)

            worker = threading.Thread(target=run, daemon=True, name=f"model-{model}-worker")
            self._workers[model] = worker
            worker.start()
            return True

    def _download_model(self, model: str) -> None:
        """使用现有下载器下载指定模型，并验证完整性。"""

        set_model_state(model, ModelState.DOWNLOADING)
        if model == "paddleocr":
            from agent_service.scripts.download_model import ensure_paddleocr_models, update_download_progress

            update_download_progress(
                "paddleocr", status="downloading", stage="official_models",
                downloaded_bytes=self._directory_stats(self._model_path(model))[0], total_bytes=None,
                message="正在准备版面、文字、表格与公式模型",
            )
            try:
                ensure_paddleocr_models(
                    paddleocr_model_dir=self.config.storage.paddleocr_model_dir,
                    language=self.config.ocr.language,
                    model_names=self.config.ocr.pipeline_model_names,
                    feature_flags=self.config.ocr.pipeline_feature_flags,
                    device=self.config.ocr.device,
                )
            except Exception as exc:
                update_download_progress(
                    "paddleocr", status="error", stage="failed",
                    downloaded_bytes=self._directory_stats(self._model_path(model))[0], total_bytes=None,
                    message=str(exc),
                )
                raise
            downloaded_bytes = self._directory_stats(self._model_path(model))[0]
            update_download_progress(
                "paddleocr", status="completed", stage="completed",
                downloaded_bytes=downloaded_bytes, total_bytes=downloaded_bytes,
                message="结构化 OCR 流水线下载完成",
            )
        else:
            from agent_service.scripts.download_model import ensure_model

            name, base_path = self._hf_model_config(model)
            ensure_model(name, base_path, model_type=model)
        if not self._model_is_available(model):
            raise RuntimeError(f"模型下载后仍不完整: {self._model_path(model)}")
        set_model_state(model, ModelState.DOWNLOADED)

    def _load_model(self, model: str) -> None:
        """调用现有模型门面的异步预热入口。"""

        set_model_state(model, ModelState.LOADING)
        if model == "embedding":
            from agent_service.services.memory.rag.embedding import _get_shared_provider

            provider = _get_shared_provider(self.config)
            provider.warmup()
            if provider._model is not None:
                set_model_state(model, ModelState.READY)
        elif model == "rerank":
            from agent_service.services.memory.rag.rerank import _get_shared_rerank_provider

            provider = _get_shared_rerank_provider(self.config)
            provider.warmup()
            if provider._model is not None:
                set_model_state(model, ModelState.READY)
        elif model == "paddleocr":
            from agent_service.services.memory.rag.image_ocr import ImageOcrService

            service = ImageOcrService(config=self.config, enabled=True)
            service.warmup()
            if service.loaded:
                set_model_state(model, ModelState.READY)
        else:
            from agent_service.services.local_qwen.service import get_local_qwen_service

            service = get_local_qwen_service(self.config)
            service.ensure_loaded()
            if service.loaded:
                set_model_state(model, ModelState.READY)

    def _model_is_available(self, model: str) -> bool:
        """按模型类型执行只读磁盘完整性验证。"""

        if model == "paddleocr":
            return is_paddleocr_pipeline_available(
                self._model_path(model),
                self.config.ocr.pipeline_model_names,
            )
        return is_model_available(self._model_path(model))

    def _model_path(self, model: str) -> Path:
        """返回模型实际受管目录。"""

        if model == "paddleocr":
            return Path(self.config.storage.paddleocr_model_dir).expanduser().resolve()
        name, base_path = self._hf_model_config(model)
        return model_target_dir(name, base_path)

    def _hf_model_config(self, model: str) -> tuple[str, Path]:
        """返回 Hugging Face 模型名称与缓存根目录。"""

        values = {
            "embedding": (self.config.model.embedding_model_name, self.config.storage.embedding_model_dir),
            "rerank": (self.config.model.rerank_model_name, self.config.storage.rerank_model_dir),
            "local_qwen": (self.config.model.local_model_name, self.config.storage.local_model_dir),
        }
        name, base_path = values[model]
        return str(name), Path(base_path)

    @staticmethod
    def _validate_model_key(model: str) -> None:
        """拒绝任何不属于四类受管模型的键。"""

        if model not in MODEL_KEYS:
            raise ValueError("model 必须是 embedding / rerank / paddleocr / local_qwen")

    def get_management_status(self, *, user_id: str) -> dict[str, list[dict[str, Any]]]:
        """返回本地 Qwen、Embedding、ReRank 与 PaddleOCR 的完整管理状态。"""

        self._reconcile_loaded_runtime_states()
        states = get_model_status().to_dict()
        embedding = self._hf_model(
            key="embedding",
            label="Embedding 模型",
            role="知识向量化",
            name=self.config.model.embedding_model_name,
            base_path=Path(self.config.storage.embedding_model_dir),
            state=states["embedding"],
        )
        rerank = self._hf_model(
            key="rerank",
            label="ReRank 模型",
            role="检索结果重排",
            name=self.config.model.rerank_model_name,
            base_path=Path(self.config.storage.rerank_model_dir),
            state=states["rerank"],
        )
        local_qwen = self._hf_model(
            key="local_qwen",
            label="本地 Qwen 大语言模型",
            role="本地主 Agent、小模型回退与图片理解",
            name=self.config.model.local_model_name,
            base_path=Path(self.config.storage.local_model_dir),
            state=states["local_qwen"],
            extra_details={
                "device": "CPU",
                "capabilities": "文本生成 / 工具调用 / 图片理解",
                "fallback": "未配置大模型时同时承担主模型与小模型",
            },
        )
        ocr_path = Path(self.config.storage.paddleocr_model_dir).expanduser().resolve()
        ocr_size, ocr_files = self._directory_stats(ocr_path)
        model_names = self.config.ocr.pipeline_model_names
        feature_flags = self.config.ocr.pipeline_feature_flags
        ocr_downloaded = is_paddleocr_pipeline_available(ocr_path, model_names)
        paddleocr = {
            "key": "paddleocr",
            "label": "PaddleOCR 结构化流水线",
            "role": "扫描文档版面、文字、表格、公式与阅读顺序解析",
            "name": "PP-StructureV3 高质量流水线",
            "path": str(ocr_path),
            "base_path": str(ocr_path),
            "size_bytes": ocr_size,
            "file_count": ocr_files,
            "status": states["paddleocr"],
            "enabled": bool(self.settings_service.is_ocr_enabled_for_user(user_id=user_id)),
            "active": states["paddleocr"] == "ready",
            "downloaded": ocr_downloaded,
            "progress": get_download_progress("paddleocr"),
            "details": {
                "provider": "PaddleOCR / PaddleX",
                "language": self.config.ocr.language,
                "device": self.config.ocr.device,
                "layout_model": model_names.get("layout_detection", ""),
                "ocr_models": " / ".join(filter(None, (
                    model_names.get("text_detection"), model_names.get("text_recognition"),
                ))),
                "table_models": " / ".join(filter(None, (
                    model_names.get("wired_table_structure"), model_names.get("wireless_table_structure"),
                ))),
                "formula_model": model_names.get("formula_recognition", ""),
                "supporting_models": " / ".join(dict.fromkeys(filter(None, (
                    model_names.get("region_detection"),
                    model_names.get("doc_orientation"),
                    model_names.get("doc_unwarping"),
                    model_names.get("textline_orientation"),
                    model_names.get("table_classification"),
                    model_names.get("wired_table_cells"),
                    model_names.get("wireless_table_cells"),
                    model_names.get("table_orientation"),
                )))),
                "preprocessing": "方向分类 / 透视与弯曲校正 / 文本行方向",
                "disabled_modules": " / ".join(
                    label for key, label in (
                        ("use_chart_recognition", "图表解析"),
                        ("use_seal_recognition", "印章识别"),
                    ) if not feature_flags.get(key, False)
                ),
            },
        }
        return {"models": [local_qwen, embedding, rerank, paddleocr]}

    @staticmethod
    def _reconcile_loaded_runtime_states() -> None:
        """用真实共享 provider 缓存修复被并发状态写入覆盖的 READY 状态。"""

        from agent_service.services.memory.rag.embedding import is_shared_embedding_provider_loaded
        from agent_service.services.memory.rag.rerank import is_shared_rerank_provider_loaded

        if is_shared_embedding_provider_loaded():
            set_model_state("embedding", ModelState.READY)
        if is_shared_rerank_provider_loaded():
            set_model_state("rerank", ModelState.READY)

    def _hf_model(
        self,
        *,
        key: str,
        label: str,
        role: str,
        name: str,
        base_path: Path,
        state: str,
        extra_details: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """构造一个 Hugging Face 模型的磁盘与运行状态。"""

        target = model_target_dir(name, base_path)
        size_bytes, file_count = self._directory_stats(target)
        return {
            "key": key,
            "label": label,
            "role": role,
            "name": name,
            "path": str(target),
            "base_path": str(Path(base_path).expanduser().resolve()),
            "size_bytes": size_bytes,
            "file_count": file_count,
            "status": state,
            "enabled": bool(name),
            "active": state == "ready",
            "downloaded": is_model_available(target),
            "progress": get_download_progress(key),
            "details": {
                "provider": "Hugging Face",
                "repository": name,
                "model_type": key,
                **(extra_details or {}),
            },
        }

    @staticmethod
    def _directory_stats(path: Path) -> tuple[int, int]:
        """返回目录真实字节数和文件数，不跟随不存在的路径。"""

        if not path.exists():
            return 0, 0
        size_bytes = 0
        file_count = 0
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            try:
                size_bytes += item.stat().st_size
                file_count += 1
            except OSError:
                continue
        return size_bytes, file_count
