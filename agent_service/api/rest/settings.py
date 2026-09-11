"""用户设置端点。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.services.document_parsing import MinerUClient
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.api.rest.deps import (
    _require_agent,
    _require_dsh_runtime_manager,
    _require_knowledge_library_service,
    _require_latex_service,
    _require_model_management_service,
    _require_settings_service,
)

router = APIRouter()

logger = logging.getLogger(__name__)

# ---- 系统提示词条目 ----

@router.get("/settings/models/status")
async def get_model_status() -> dict[str, Any]:
    """返回 Embedding / ReRank / PaddleOCR 模型加载状态快照。"""

    from agent_service.core.model_status import get_model_status as _get_model_status

    return _get_model_status().to_dict()


@router.post("/settings/models/download")
async def download_model(body: dict[str, Any]) -> dict[str, Any]:
    """异步触发指定模型的后台下载。

    body: { "model": "embedding" | "rerank" | "paddleocr" | "local_qwen" }
    返回后前端轮询 GET /settings/models/status 获取进度。
    """

    model = str(body.get("model") or "").strip()
    if model not in ("embedding", "rerank", "paddleocr", "local_qwen"):
        raise HTTPException(status_code=422, detail="model 必须是 embedding / rerank / paddleocr / local_qwen")

    from agent_service.core.model_status import ModelState, set_model_state

    svc = _require_settings_service()
    config = svc.config

    if model == "local_qwen":
        from agent_service.services.local_qwen.service import start_local_qwen_download

        started = start_local_qwen_download(config, load_after=True)
        return {"status": "started" if started else "already_running", "model": model}

    def _download_embedding() -> None:
        try:
            from agent_service.scripts.download_model import ensure_model, model_target_dir, is_model_available

            model_name = config.model.embedding_model_name
            model_dir = config.storage.embedding_model_dir
            set_model_state("embedding", ModelState.DOWNLOADING)
            ensure_model(model_name, model_dir, model_type="embedding")
            target = model_target_dir(model_name, model_dir)
            if is_model_available(target):
                set_model_state("embedding", ModelState.DOWNLOADED)
                _trigger_embedding_load(config)
            else:
                set_model_state("embedding", ModelState.ERROR)
        except Exception as exc:
            from agent_service.scripts.download_model import update_download_progress

            update_download_progress(
                "embedding",
                status="error",
                stage="failed",
                downloaded_bytes=0,
                total_bytes=None,
                message=str(exc),
            )
            set_model_state("embedding", ModelState.ERROR)

    def _download_rerank() -> None:
        try:
            from agent_service.scripts.download_model import ensure_model, model_target_dir, is_model_available

            model_name = config.model.rerank_model_name
            model_dir = config.storage.rerank_model_dir
            set_model_state("rerank", ModelState.DOWNLOADING)
            ensure_model(model_name, model_dir, model_type="rerank")
            target = model_target_dir(model_name, model_dir)
            if is_model_available(target):
                set_model_state("rerank", ModelState.DOWNLOADED)
                _trigger_rerank_load(config)
            else:
                set_model_state("rerank", ModelState.ERROR)
        except Exception as exc:
            from agent_service.scripts.download_model import update_download_progress

            update_download_progress(
                "rerank",
                status="error",
                stage="failed",
                downloaded_bytes=0,
                total_bytes=None,
                message=str(exc),
            )
            set_model_state("rerank", ModelState.ERROR)

    def _download_paddleocr() -> None:
        """在后台下载完整 PP-StructureV3 受管模型组并发布真实字节进度。"""

        stop_progress = threading.Event()

        def _tracked_bytes() -> int:
            """Return real bytes written to MetaWeave and PaddleX OCR model roots."""

            roots = [
                Path(config.storage.paddleocr_model_dir),
                *(
                    Path.home() / ".paddlex" / "official_models" / model_name
                    for model_name in dict.fromkeys(config.ocr.pipeline_model_names.values())
                ),
            ]
            total = 0
            for root in roots:
                if root.exists():
                    for item in root.rglob("*"):
                        if not item.is_file():
                            continue
                        try:
                            total += item.stat().st_size
                        except OSError:
                            continue
            return total

        def _track_ocr() -> None:
            """轮询 MetaWeave 与 PaddleX 模型目录的真实落盘字节。"""

            from agent_service.scripts.download_model import update_download_progress

            while not stop_progress.is_set():
                update_download_progress(
                    "paddleocr",
                    status="downloading",
                    stage="official_models",
                    downloaded_bytes=_tracked_bytes(),
                    total_bytes=None,
                    message="正在准备版面、文字、表格与公式模型",
                )
                stop_progress.wait(0.75)

        tracker = threading.Thread(target=_track_ocr, daemon=True)
        tracker.start()
        try:
            from agent_service.scripts.download_model import ensure_paddleocr_models, update_download_progress

            set_model_state("paddleocr", ModelState.DOWNLOADING)
            ensure_paddleocr_models(
                paddleocr_model_dir=config.storage.paddleocr_model_dir,
                language=config.ocr.language,
                model_names=config.ocr.pipeline_model_names,
                feature_flags=config.ocr.pipeline_feature_flags,
                device=config.ocr.device,
            )
            downloaded_bytes = _tracked_bytes()
            update_download_progress(
                "paddleocr",
                status="completed",
                stage="completed",
                downloaded_bytes=downloaded_bytes,
                total_bytes=downloaded_bytes,
                message="结构化 OCR 流水线准备完成",
            )
            set_model_state("paddleocr", ModelState.READY)
        except Exception as exc:
            from agent_service.scripts.download_model import update_download_progress

            update_download_progress(
                "paddleocr",
                status="error",
                stage="failed",
                downloaded_bytes=_tracked_bytes(),
                total_bytes=None,
                message=str(exc),
            )
            set_model_state("paddleocr", ModelState.ERROR)
        finally:
            stop_progress.set()
            tracker.join(timeout=2)

    t = threading.Thread(target={
        "embedding": _download_embedding,
        "rerank": _download_rerank,
        "paddleocr": _download_paddleocr,
    }[model], daemon=True)
    t.start()

    return {"status": "started", "model": model}


def _trigger_embedding_load(config: Any) -> None:
    """触发 Embedding 模型后台加载。"""
    try:
        from agent_service.services.memory.rag.embedding import _get_shared_provider
        provider = _get_shared_provider(config)
        provider.warmup()
        # warmup 后如果模型已就绪，同步状态（防止状态漂移）
        if provider._model is not None:
            from agent_service.core.model_status import ModelState, set_model_state
            set_model_state("embedding", ModelState.READY)
    except Exception:
        pass


def _trigger_rerank_load(config: Any) -> None:
    """触发 ReRank 模型后台加载。"""
    try:
        from agent_service.services.memory.rag.rerank import _get_shared_rerank_provider
        provider = _get_shared_rerank_provider(config)
        provider.warmup()
        if provider._model is not None:
            from agent_service.core.model_status import ModelState, set_model_state
            set_model_state("rerank", ModelState.READY)
    except Exception:
        pass


def _trigger_local_qwen_load(config: Any) -> None:
    """在后台线程中加载共享 CPU Qwen 实例。"""

    def _load() -> None:
        try:
            from agent_service.services.local_qwen.service import get_local_qwen_service

            get_local_qwen_service(config).ensure_loaded()
        except Exception:
            logger.exception("本地 Qwen 后台加载失败")

    threading.Thread(target=_load, daemon=True, name="local-qwen-load").start()


@router.post("/settings/models/load")
async def load_model(body: dict[str, Any]) -> dict[str, Any]:
    """触发指定模型的后台加载（不下载，只加载到内存）。

    body: { "model": "embedding" | "rerank" | "local_qwen" }
    """
    model = str(body.get("model") or "").strip()
    if model not in ("embedding", "rerank", "local_qwen"):
        raise HTTPException(status_code=422, detail="model 必须是 embedding / rerank / local_qwen")

    from agent_service.core.model_status import ModelState, set_model_state

    svc = _require_settings_service()
    config = svc.config

    if model == "embedding":
        _trigger_embedding_load(config)
    elif model == "rerank":
        _trigger_rerank_load(config)
    else:
        _trigger_local_qwen_load(config)

    return {"status": "triggered", "model": model}


@router.get("/settings/models/download-progress")
async def get_download_progress() -> dict[str, dict[str, object]]:
    """返回各模型真实字节、总量、阶段和确定/不确定进度。"""

    from agent_service.scripts.download_model import get_all_download_progress

    return get_all_download_progress()


@router.get("/settings/models/management")
def get_model_management(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """返回模型管理区需要的配置、磁盘、运行和真实下载状态。"""

    return _require_model_management_service().get_management_status(user_id=user_id)


@router.get("/settings/models/preferences")
async def get_model_preferences(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),
) -> dict[str, Any]:
    """返回当前用户持久化的模型自动下载偏好。"""

    return _require_settings_service().get_model_preferences(user_id=user_id)


@router.put("/settings/models/preferences")
async def save_model_preferences(body: dict[str, Any]) -> dict[str, Any]:
    """保存模型自动下载偏好；该设置默认关闭。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id or "auto_download_enabled" not in body:
        raise HTTPException(status_code=422, detail="user_id and auto_download_enabled are required")
    result = _require_settings_service().save_model_preferences(
        user_id=user_id,
        auto_download_enabled=bool(body["auto_download_enabled"]),
    )
    if result["auto_download_enabled"]:
        _require_model_management_service().initialize_after_startup(user_id=user_id)
    return result


@router.post("/settings/models/initialize")
async def initialize_models(body: dict[str, Any]) -> dict[str, Any]:
    """在前端完整启动后触发四类模型的独立后台验证任务。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    return _require_model_management_service().initialize_after_startup(user_id=user_id)


@router.post("/settings/models/download-confirmed")
async def download_confirmed_model(body: dict[str, Any]) -> dict[str, Any]:
    """在用户确认后启动指定模型的后台下载。"""

    user_id = str(body.get("user_id") or "").strip()
    model = str(body.get("model") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        started = _require_model_management_service().start_download(model, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "started" if started else "already_running", "model": model}


@router.post("/settings/models/delete")
async def delete_managed_model(body: dict[str, Any]) -> dict[str, Any]:
    """删除用户明确选择的模型，并抑制本次进程内自动重新下载。"""

    user_id = str(body.get("user_id") or "").strip()
    model = str(body.get("model") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_model_management_service().delete_model(model, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/models/check")
async def check_model_disk() -> dict[str, Any]:
    """磁盘级检测模型文件是否存在，同步真实状态。"""

    from agent_service.core.model_status import ModelState, set_model_state, get_model_status
    from agent_service.scripts.download_model import get_download_progress, is_model_available, model_target_dir

    svc = _require_settings_service()
    config = svc.config

    models = {
        "embedding": config.model.embedding_model_name,
        "rerank": config.model.rerank_model_name,
        "local_qwen": config.model.local_model_name,
    }
    dirs = {
        "embedding": config.storage.embedding_model_dir,
        "rerank": config.storage.rerank_model_dir,
        "local_qwen": config.storage.local_model_dir,
    }

    for key in ("embedding", "rerank", "local_qwen"):
        progress = get_download_progress(key)
        if progress.get("status") == "downloading":
            set_model_state(key, ModelState.DOWNLOADING)
            continue
        target = model_target_dir(models[key], dirs[key])
        available = is_model_available(target)
        if available:
            current = get_model_status().to_dict().get(key)
            if current in ("ready", "loading", "downloading", "verifying"):
                continue
            set_model_state(key, ModelState.DOWNLOADED)
        else:
            set_model_state(key, ModelState.NOT_DOWNLOADED)

    from agent_service.scripts.download_model import is_paddleocr_pipeline_available
    paddleocr_available = is_paddleocr_pipeline_available(
        Path(config.storage.paddleocr_model_dir),
        config.ocr.pipeline_model_names,
    )
    current_ocr = get_model_status().to_dict().get("paddleocr")
    if current_ocr not in ("ready", "loading", "downloading", "verifying"):
        set_model_state(
            "paddleocr",
            ModelState.DOWNLOADED if paddleocr_available else ModelState.NOT_DOWNLOADED,
        )

    return get_model_status().to_dict()


@router.get("/settings/profile")
async def get_user_profile(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取或初始化用户设置档案。"""
    svc = _require_settings_service()
    try:
        return svc.ensure_user_profile(user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/profile")
async def ensure_user_profile(body: dict[str, Any]) -> dict[str, Any]:
    """根据 user_id 获取或初始化用户设置档案。"""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    try:
        return svc.ensure_user_profile(user_id=str(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/settings/profile/knowledge-dir")
async def update_user_knowledge_dir(body: dict[str, Any]) -> dict[str, Any]:
    """
    更新用户 active 知识库目录并持久化。

    body: user_id 必填,knowledge_dir 必填,name 可选。该接口只更新设置,不执行灌库。
    """

    user_id = str(body.get("user_id") or "").strip()
    knowledge_dir = str(body.get("knowledge_dir") or "").strip()
    name = str(body.get("name") or "").strip() or None
    if not user_id or not knowledge_dir:
        raise HTTPException(status_code=422, detail="user_id and knowledge_dir are required")
    svc = _require_settings_service()
    try:
        return svc.update_knowledge_dir(user_id=user_id, knowledge_dir=knowledge_dir, name=name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/appearance/font")
@router.put("/settings/appearance/font")
async def save_font_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户 editor 字体家族配置。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    ui_font_families = body.get("ui_font_families")
    text_font_families = body.get("text_font_families")
    ui_font_size_percent = body.get("ui_font_size_percent")
    text_font_size_percent = body.get("text_font_size_percent")
    font_size_percent = body.get("font_size_percent")
    if ui_font_families is not None and not isinstance(ui_font_families, list):
        raise HTTPException(status_code=422, detail="ui_font_families must be a list")
    if text_font_families is not None and not isinstance(text_font_families, list):
        raise HTTPException(status_code=422, detail="text_font_families must be a list")
    font_sizes = {
        "ui_font_size_percent": ui_font_size_percent,
        "text_font_size_percent": text_font_size_percent,
        "font_size_percent": font_size_percent,
    }
    for field_name, value in font_sizes.items():
        if value is not None and not isinstance(value, int):
            raise HTTPException(status_code=422, detail=f"{field_name} must be an integer")
    svc = _require_settings_service()
    try:
        return svc.save_font_config(
            user_id=user_id,
            ui_font_families=ui_font_families,
            text_font_families=text_font_families,
            ui_font_size_percent=ui_font_size_percent,
            text_font_size_percent=text_font_size_percent,
            font_size_percent=font_size_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/appearance/config")
@router.put("/settings/appearance/config")
async def save_appearance_config(body: dict[str, Any]) -> dict[str, Any]:
    """Persist editor appearance colors and backlinks visibility for a user."""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    try:
        return svc.save_appearance_config(
            user_id=user_id,
            theme_primary_color=body.get("theme_primary_color"),
            theme_soft_color=body.get("theme_soft_color"),
            tag_colors=body.get("tag_colors"),
            tag_colors_translucent=body.get("tag_colors_translucent"),
            reset_tag_colors_translucent=(
                "tag_colors_translucent" in body and body["tag_colors_translucent"] is None
            ),
            background_cover_url=body.get("background_cover_url"),
            show_backlinks=body.get("show_backlinks"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/editor/paste")
@router.put("/settings/editor/paste")
async def save_editor_paste_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存编辑器粘贴设置。body: user_id 必填,editor_image_assets_dir 可选。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    try:
        return svc.save_editor_paste_config(
            user_id=user_id,
            editor_image_assets_dir=body.get("editor_image_assets_dir"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings/profile/ingestion")
async def get_knowledge_ingestion_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取知识库灌库配置。"""

    svc = _require_settings_service()
    return svc.get_knowledge_ingestion_config(user_id=user_id)


@router.put("/settings/profile/ingestion")
async def save_knowledge_ingestion_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存知识库灌库、OCR 与本地识图配置。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    result = svc.save_knowledge_ingestion_config(
        user_id=user_id,
        auto_ingest_on_upload=body.get("auto_ingest_on_upload"),
        ocr_enabled=body.get("ocr_enabled"),
        vlm_enabled=body.get("vlm_enabled"),
        vision_understanding_enabled=body.get("vision_understanding_enabled"),
        dsh_coding_agent_enabled=body.get("dsh_coding_agent_enabled"),
        knowledge_ignore_patterns=body.get("knowledge_ignore_patterns"),
    )
    if result.get("dsh_coding_agent_enabled") is True:
        _require_dsh_runtime_manager().start_install()
    if "knowledge_ignore_patterns" in body:
        try:
            cleanup_result = _require_knowledge_library_service().cleanup_ignored_sources(user_id=user_id)
            result["ignore_cleanup"] = cleanup_result
        except RuntimeError:
            result["ignore_cleanup"] = {"files_seen": 0, "chunks_deleted": 0}
    return result


@router.get("/settings/vlm/config")
async def get_vlm_config(user_id: str = Query(..., min_length=1)) -> dict[str, object]:
    """返回用户生效的 MinerU 精准 API 配置。"""

    return _require_settings_service().get_vlm_config(user_id=user_id)


@router.put("/settings/vlm/config")
async def save_vlm_config(body: dict[str, Any]) -> dict[str, object]:
    """保存 MinerU 精准 API 与 OCR 用户设置。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_settings_service().save_vlm_config(
            user_id=user_id,
            enabled=body.get("enabled"),
            api_key=body.get("api_key"),
            model=body.get("model"),
            max_concurrency=body.get("max_concurrency"),
            max_file_bytes=body.get("max_file_bytes"),
            max_pages=body.get("max_pages"),
            submit_rate_per_minute=body.get("submit_rate_per_minute"),
            result_rate_per_minute=body.get("result_rate_per_minute"),
            ocr_enabled=body.get("ocr_enabled"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings/vlm/config/saved")
async def list_vlm_config_presets(user_id: str = Query(..., min_length=1)) -> dict[str, object]:
    """列出当前用户保存的 MinerU 配置。"""

    return {"configs": _require_settings_service().list_vlm_config_presets(user_id=user_id)}


@router.post("/settings/vlm/config/saved")
async def save_vlm_config_preset(body: dict[str, Any]) -> dict[str, object]:
    """保存一条可加载的 MinerU 模型与限制参数。"""

    try:
        return _require_settings_service().save_vlm_config_preset(
            user_id=str(body.get("user_id") or ""),
            label=str(body.get("label") or ""),
            api_key=str(body.get("api_key") or ""),
            model=str(body.get("model") or ""),
            max_concurrency=int(body.get("max_concurrency") or 0),
            max_file_bytes=int(body.get("max_file_bytes") or 0),
            max_pages=int(body.get("max_pages") or 0),
            submit_rate_per_minute=int(body.get("submit_rate_per_minute") or 0),
            result_rate_per_minute=int(body.get("result_rate_per_minute") or 0),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/settings/vlm/config/saved/{config_id}")
async def delete_vlm_config_preset(config_id: str, user_id: str = Query(..., min_length=1)) -> dict[str, bool]:
    """删除当前用户拥有的一条 MinerU 配置。"""

    deleted = _require_settings_service().delete_vlm_config_preset(config_id=config_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="VLM config preset not found")
    return {"ok": True}


@router.post("/settings/vlm/check")
async def check_vlm_connection(body: dict[str, Any]) -> dict[str, object]:
    """验证当前用户 MinerU 网络和 Token，供设置页与扫描器开关使用。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    config = _require_settings_service().get_vlm_config(user_id=user_id)
    if "api_key" in body:
        config = {**config, "api_key": str(body.get("api_key") or "").strip()}
    return await run_in_threadpool(MinerUClient(config).check)


@router.post("/settings/vlm/local-ocr/ensure")
async def ensure_local_ocr(body: dict[str, Any]) -> dict[str, object]:
    """用户显式选择本地 OCR 时同步下载并加载完整流水线。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        await run_in_threadpool(ImageOcrService(config=_require_settings_service().config, enabled=True).ensure_ready)
    except Exception as exc:
        logger.exception("本地 OCR 准备失败 | user=%s", user_id)
        raise HTTPException(status_code=503, detail="本地 OCR 模型下载或加载失败") from exc
    return {"ready": True}


@router.post("/settings/floating/config")
@router.put("/settings/floating/config")
async def save_floating_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户悬浮窗启动配置。body: user_id 必填,floating_launch_enabled 可选。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    try:
        return svc.save_floating_config(
            user_id=user_id,
            floating_launch_enabled=body.get("floating_launch_enabled"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/settings/graph/config")
async def save_graph_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户图谱配置。body: user_id 必填,graph_node_limit 可选。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    svc = _require_settings_service()
    result = svc.save_graph_config(
        user_id=user_id,
        graph_node_limit=body.get("graph_node_limit"),
    )
    return result


@router.get("/settings/memory/system-prompts")
async def list_system_prompt_entries(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """列出用户的所有系统提示词条目。"""
    svc = _require_settings_service()
    entries = svc.list_system_prompt_entries(user_id=user_id)
    return {"entries": entries}


@router.post("/settings/memory/system-prompts")
async def add_system_prompt_entry(body: dict[str, Any]) -> dict[str, Any]:
    """添加一条系统提示词条目。body: user_id, content。"""
    user_id = body.get("user_id")
    content = body.get("content")
    if not user_id or not content:
        raise HTTPException(status_code=422, detail="user_id and content are required")
    svc = _require_settings_service()
    return svc.add_system_prompt_entry(user_id=str(user_id), content=str(content))


@router.delete("/settings/memory/system-prompts/{prompt_id}")
async def delete_system_prompt_entry(prompt_id: str) -> dict[str, Any]:
    """删除指定的系统提示词条目。"""
    svc = _require_settings_service()
    deleted = svc.delete_system_prompt_entry(prompt_id=prompt_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


# ---- 用户 LLM 配置 ----

@router.get("/settings/llm/config")
async def get_llm_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取用户的 LLM 配置（返回明文 API Key）。"""
    svc = _require_settings_service()
    return svc.get_llm_config(user_id=user_id)


@router.put("/settings/llm/config")
async def save_llm_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户的 LLM 配置。body: user_id 必填，其余字段可选。"""
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    def _unwrap(field: str) -> str | None:
        if field not in body:
            return None
        value = body.get(field)
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip()
        return s

    def _unwrap_nonnegative_int(field: str) -> int | None:
        if field not in body:
            return None
        value = body.get(field)
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{field} must be an integer") from exc
        if parsed < 0:
            raise HTTPException(status_code=422, detail=f"{field} must be nonnegative")
        return parsed

    svc = _require_settings_service()
    return svc.save_llm_config(
        user_id=user_id,
        api_key=_unwrap("api_key"),
        base_url=_unwrap("base_url"),
        model_name=_unwrap("model_name"),
        small_api_key=_unwrap("small_api_key"),
        small_base_url=_unwrap("small_base_url"),
        small_model_name=_unwrap("small_model_name"),
        model_context_window_tokens=_unwrap_nonnegative_int("model_context_window_tokens"),
        model_max_output_tokens=_unwrap_nonnegative_int("model_max_output_tokens"),
        small_model_context_window_tokens=_unwrap_nonnegative_int("small_model_context_window_tokens"),
        small_model_max_output_tokens=_unwrap_nonnegative_int("small_model_max_output_tokens"),
    )


# ---- 联网搜索配置 ----

@router.get("/settings/llm/config/saved")
async def list_llm_config_presets(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """列出用户保存的可复用 LLM 配置。"""

    svc = _require_settings_service()
    return {"configs": svc.list_llm_config_presets(user_id=user_id)}


@router.post("/settings/llm/config/saved")
async def save_llm_config_preset(body: dict[str, Any]) -> dict[str, Any]:
    """保存一条可复用的单模型 LLM 配置。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")

    def _unwrap(value: Any) -> str | None:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip()
        return s if s else None

    svc = _require_settings_service()
    try:
        return svc.save_llm_config_preset(
            user_id=user_id,
            label=_unwrap(body.get("label")),
            api_key=_unwrap(body.get("api_key")),
            base_url=_unwrap(body.get("base_url")),
            model_name=_unwrap(body.get("model_name")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/settings/llm/config/saved/{config_id}")
async def delete_llm_config_preset(config_id: str) -> dict[str, Any]:
    """删除一条已保存的 LLM 配置。"""

    svc = _require_settings_service()
    deleted = svc.delete_llm_config_preset(config_id=config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"ok": True}


@router.get("/settings/web-search/config")
async def get_web_search_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取用户的联网搜索配置（代理地址 + 开关状态）。"""
    svc = _require_settings_service()
    return svc.get_web_search_config(user_id=user_id)


@router.put("/settings/web-search/config")
async def save_web_search_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户的联网搜索配置。body: user_id 必填，其余字段可选。"""
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")

    def _unwrap(value: Any) -> str | None:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip()
        return s if s else None

    svc = _require_settings_service()
    raw_max = body.get("web_search_max_results")
    web_search_max_results: int | None = (
        int(raw_max) if raw_max is not None and not isinstance(raw_max, bool) else None
    )

    svc = _require_settings_service()
    return svc.save_web_search_config(
        user_id=user_id,
        proxy_url=_unwrap(body.get("proxy_url")),
        browser_proxy_url=(
            str(body.get("browser_proxy_url") or "").strip()
            if "browser_proxy_url" in body
            else None
        ),
        browser_home_url=(
            str(body.get("browser_home_url") or "").strip()
            if "browser_home_url" in body
            else None
        ),
        web_search_enabled=body.get("web_search_enabled"),
        web_search_max_results=web_search_max_results,
    )


# ---- 可开关工具 ----

@router.get("/settings/tools/disabled")
async def get_disabled_tools(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取用户关闭的工具名称列表。"""
    svc = _require_settings_service()
    return {"disabled_tools": svc.get_disabled_tools(user_id=user_id)}


@router.put("/settings/tools/disabled")
async def save_disabled_tools(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户关闭的工具列表。body: user_id 必填, tool_names 为关闭的工具名称数组。"""
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    raw_tool_names = body.get("tool_names", [])
    tool_names = [str(name) for name in raw_tool_names if isinstance(name, str) and name.strip()]
    svc = _require_settings_service()
    return {"disabled_tools": svc.save_disabled_tools(user_id=user_id, tool_names=tool_names)}


@router.get("/settings/tools/available")
async def list_available_tools(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """列出全部内置工具及当前用户的开关状态。"""
    svc = _require_settings_service()
    return svc.list_available_tools(user_id=user_id)


@router.get("/settings/terminal/sandbox")
async def get_terminal_sandbox_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取用户的 Agent 终端沙盒配置和支持的结构化指令段目录。"""

    svc = _require_settings_service()
    return svc.get_terminal_sandbox_config(user_id=user_id)


@router.put("/settings/terminal/sandbox")
async def save_terminal_sandbox_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户的 Agent 终端沙盒配置。body: user_id 必填,config 为配置对象。"""

    user_id = str(body.get("user_id") or "").strip()
    config_payload = body.get("config")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    if not isinstance(config_payload, dict):
        raise HTTPException(status_code=422, detail="config must be an object")
    svc = _require_settings_service()
    try:
        return svc.save_terminal_sandbox_config(user_id=user_id, config_payload=config_payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

# ---- 长期记忆配置与自定义内容 ----

@router.get("/settings/memory/config")
async def get_memory_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """获取用户的长期记忆总开关。"""
    return _require_settings_service().get_memory_config(user_id=user_id)


@router.put("/settings/memory/config")
async def save_memory_config(body: dict[str, Any]) -> dict[str, Any]:
    """保存用户的长期记忆总开关。"""
    user_id = str(body.get("user_id") or "").strip()
    if not user_id or not isinstance(body.get("long_term_memory_enabled"), bool):
        raise HTTPException(status_code=422, detail="user_id and long_term_memory_enabled are required")
    return _require_settings_service().save_memory_config(
        user_id=user_id,
        long_term_memory_enabled=body["long_term_memory_enabled"],
    )


# ---- 自定义长期记忆 ----

@router.get("/settings/memory/memories")
async def list_memories(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> list[dict[str, Any]]:
    """列出用户的自定义长期记忆。"""
    svc = _require_settings_service()
    return svc.list_memories(user_id=user_id)


@router.post("/settings/memory/memories")
async def add_memory(body: dict[str, Any]) -> dict[str, Any]:
    """添加一条自定义长期记忆。body: user_id, content, importance (可选)。"""
    user_id = body.get("user_id")
    content = body.get("content")
    if not user_id or not content:
        raise HTTPException(status_code=422, detail="user_id and content are required")
    svc = _require_settings_service()
    return svc.add_memory(
        user_id=str(user_id),
        content=str(content),
        importance=float(body.get("importance", 0.5)),
    )


@router.delete("/settings/memory/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    """删除指定的自定义长期记忆。"""
    svc = _require_settings_service()
    deleted = svc.remove_memory(memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


# ---- 安全配置（敏感词库） ----


@router.get("/settings/safety/sensitive-words")
async def get_sensitive_words() -> dict[str, Any]:
    """读取敏感词库 JSON。"""
    sensitive_words_path = _require_settings_service().config.storage.sensitive_words_path
    try:
        data = json.loads(sensitive_words_path.read_text(encoding="utf-8"))
        return data
    except FileNotFoundError:
        return {"_description": "敏感词库,按类别分组。支持 exact 精确匹配 + regex 正则匹配", "categories": {}}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取敏感词库失败: {exc}") from exc


@router.post("/settings/safety/sensitive-words")
async def save_sensitive_words(body: dict[str, Any]) -> dict[str, Any]:
    """保存敏感词库 JSON,并触发 SafetyService 热重载。"""
    sensitive_words_path = _require_settings_service().config.storage.sensitive_words_path
    try:
        sensitive_words_path.parent.mkdir(parents=True, exist_ok=True)
        sensitive_words_path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            _require_agent().safety_service.reload_sensitive_words()
        except Exception:
            logger.warning("敏感词库已保存,但 SafetyService 热重载失败", exc_info=True)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存敏感词库失败: {exc}") from exc


# ---- 存储管理 ----

@router.get("/settings/storage/config")
def get_storage_config(user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID")) -> dict[str, Any]:
    """返回所有存储路径的当前值、大小和元数据。"""

    svc = _require_settings_service()
    from agent_service.services.storage.service import StorageService
    storage_svc = StorageService(config=svc.config, settings_service=svc)
    return storage_svc.get_storage_config(user_id=user_id)


@router.put("/settings/storage/config")
async def save_storage_config(body: dict[str, Any]) -> dict[str, Any]:
    """兼容旧客户端的写入请求；所有存储路径均为只读并返回 422。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    paths = body.get("paths", {})
    if not isinstance(paths, dict):
        raise HTTPException(status_code=422, detail="paths must be a dict")
    svc = _require_settings_service()
    from agent_service.services.storage.service import StorageService
    storage_svc = StorageService(config=svc.config, settings_service=svc)
    try:
        return storage_svc.save_storage_config(user_id=user_id, paths=paths)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/storage/clear")
async def clear_storage_path(body: dict[str, Any]) -> dict[str, Any]:
    """清空指定存储路径的内容，保留目录本身。"""

    path_key = str(body.get("path_key") or "").strip()
    user_id = str(body.get("user_id") or "").strip()
    if not path_key or not user_id:
        raise HTTPException(status_code=422, detail="user_id and path_key are required")
    svc = _require_settings_service()
    from agent_service.services.storage.service import StorageService
    storage_svc = StorageService(config=svc.config, settings_service=svc)
    try:
        return storage_svc.clear_path(path_key=path_key, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- LaTeX 运行环境 ----


# ---- SDK 与运行组件 ----

@router.post("/settings/sdks/dsh/initialize")
async def initialize_dsh_coding_agent(body: dict[str, Any]) -> dict[str, Any]:
    """界面启动后按用户开关异步安装 DSH Runtime，不阻塞应用启动。"""

    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    if not _require_settings_service().is_dsh_coding_agent_enabled_for_user(user_id=user_id):
        return {"status": "disabled", "enabled": False}
    status = _require_dsh_runtime_manager().start_install()
    return {"status": status["status"], "enabled": True}

@router.get("/settings/sdks/dsh/management")
def get_dsh_sdk_management(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),  # noqa: ARG001
) -> dict[str, Any]:
    """返回 DSH SDK客户端与 Windows Runtime 的真实管理状态。"""

    return _require_dsh_runtime_manager().get_management_status()


@router.post("/settings/sdks/dsh/install")
async def install_dsh_sdk(body: dict[str, Any]) -> dict[str, Any]:
    """在用户确认后异步安装当前 MW固定的 Windows Runtime。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_dsh_runtime_manager().start_install()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/sdks/dsh/install/cancel")
async def cancel_dsh_sdk_install(body: dict[str, Any]) -> dict[str, Any]:
    """取消当前 DSH Runtime校验或解压安装任务。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    return _require_dsh_runtime_manager().cancel_install()


@router.post("/settings/sdks/dsh/repair")
async def repair_dsh_sdk(body: dict[str, Any]) -> dict[str, Any]:
    """重新校验内置 SDK并原子替换损坏的 DSH Runtime。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_dsh_runtime_manager().start_install(repair=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/sdks/dsh/uninstall")
async def uninstall_dsh_sdk(body: dict[str, Any]) -> dict[str, Any]:
    """卸载 DSH Runtime，保留独立的 Child Agent Conversation历史。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_dsh_runtime_manager().uninstall()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/settings/latex/status")
async def get_latex_status(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),  # noqa: ARG001
) -> dict[str, Any]:
    """检测系统或 MetaWeave 托管的 LaTeX 编译环境。"""

    return _require_latex_service().get_status()


@router.get("/settings/latex/management")
def get_latex_management(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户 ID"),  # noqa: ARG001
) -> dict[str, Any]:
    """返回编译管理区需要的发行版、来源、引擎、路径和磁盘详情。"""

    return _require_latex_service().get_management_status()


@router.post("/settings/latex/install")
async def install_latex_runtime(body: dict[str, Any]) -> dict[str, Any]:
    """在用户确认后异步安装当前用户范围的托管 MiKTeX。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_latex_service().start_install()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/latex/install/cancel")
async def cancel_latex_install(body: dict[str, Any]) -> dict[str, Any]:
    """取消当前 MiKTeX 下载或安装任务。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    return _require_latex_service().cancel_install()


@router.post("/settings/latex/uninstall")
async def uninstall_latex_runtime(body: dict[str, Any]) -> dict[str, Any]:
    """只卸载 MetaWeave 自己部署的 MiKTeX，不操作系统 TeX。"""

    if not str(body.get("user_id") or "").strip():
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        return _require_latex_service().uninstall_managed()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
