"""settings 领域 gRPC RPC handlers。

方法体由主 servicer 机械迁移，协议行为不变。
"""

from __future__ import annotations
import logging
import json
from datetime import datetime, timezone
from typing import Any
from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from pydantic import ValidationError
from agent_service.agent_core.agent_core import AgentCore
from agent_service.api.recall_details import build_recall_details_payload
from agent_service.schemas.automation import (
    AutomationCreateRequest,
    AutomationDeleteRequest,
    AutomationToggleRequest,
)
from agent_service.api.grpc.agent_service_pb2 import (
    CancelRequest,
    CancelResponse,
    ChildAgentControlRequest,
    ChildAgentControlResponse,
    ChildAgentListRequest,
    ChildAgentListResponse,
    ChildAgentRecord,
    ChildAgentUpdateRequest,
    ChunkMessage,
    DeleteAllSessionsRequest,
    DeleteResponse,
    EventEntry,
    EventsRequest,
    EventsResponse,
    FavoriteCreateRequest,
    FavoriteDeleteRequest,
    FavoriteEntryResponse,
    FavoriteListRequest,
    FavoriteListResponse,
    PrivacyCreateRequest,
    PrivacyDeleteRequest,
    PrivacyEntryResponse,
    PrivacyListRequest,
    PrivacyListResponse,
    FeedbackCreateRequest,
    FeedbackDeleteRequest,
    FeedbackEntryResponse,
    FeedbackListRequest,
    FeedbackListResponse,
    FeedbackUpdateRequest,
    GitBranchRequest,
    GitCommitRequest,
    GitDiffRequest,
    GitHistoryRequest,
    GitInitRequest,
    GitPathsRequest,
    GitPullRequest,
    GitPushRequest,
    GitRemoteRequest,
    GitUserRequest,
    KnowledgeFileContentRequest,
    KnowledgeFileContentResponse,
    KnowledgeFileCreateRequest,
    KnowledgeFileNode,
    KnowledgeFileTreeRequest,
    KnowledgeFileTreeResponse,
    KnowledgeFileUploadRequest,
    KnowledgeFileWriteRequest,
    KnowledgeFolderCreateRequest,
    KnowledgeLibraryEntry,
    KnowledgePathCopyRequest,
    KnowledgePathDeleteRequest,
    KnowledgePathRenameRequest,
    KnowledgePdfPageRequest,
    KnowledgePdfPageResponse,
    KnowledgeRebuildRequest,
    KnowledgeRebuildResponse,
    LLMConfigPresetDeleteRequest,
    LLMConfigPresetListResponse,
    LLMConfigPresetResponse,
    LLMConfigPresetSaveRequest,
    LLMConfigRequest,
    LLMConfigResponse,
    LLMConfigSaveRequest,
    MemoryAddRequest,
    MemoryDeleteRequest,
    MemoryEntryResponse,
    MemoryListRequest,
    MemoryListResponse,
    RecallDetailsRequest,
    RecallDetailsResponse,
    ListMessagesRequest,
    ListMessagesResponse,
    ListSessionsRequest,
    ListSessionsResponse,
    MessageEntry,
    RunRequest,
    RunResult,
    SessionCreateRequest,
    SessionIdRequest,
    SessionResponse,
    SessionUpdateRequest,
    SystemPromptAddRequest,
    SystemPromptDeleteRequest,
    SystemPromptEntriesResponse,
    SystemPromptEntryResponse,
    SystemPromptRequest,
    TaskSuggestionsRequest,
    TaskSuggestionsResponse,
    TokenUsageRequest,
    ActivityHeatmapRequest,
    ToolInfo,
    ToolListRequest,
    ToolListResponse,
    ToolCall,
    TraceEntry,
    UserKnowledgeDirUpdateRequest,
    UserProfileRequest,
    UserProfileResponse,
)
from agent_service.api.grpc.agent_service_pb2_grpc import AgentServiceServicer as BaseServicer
from agent_service.schemas.session import SessionCreate, SessionUpdate
from agent_service.schemas.favorite import FavoriteCreate
from agent_service.schemas.privacy import PrivacyCreate
from agent_service.schemas.feedback import FeedbackCreate, FeedbackUpdate
from agent_service.services.message.service import MessageService
from agent_service.services.session.service import SessionService
from agent_service.services.settings.service import SettingsService
from agent_service.services.knowledge_library import KnowledgeLibraryService, KnowledgeLibraryRebuildResult
from agent_service.services.knowledge_ingestion_job.service import KnowledgeIngestionJobService
from agent_service.services.git.service import GitService, GitServiceError
from agent_service.services.task_suggestion.service import TaskSuggestionService
from agent_service.services.token_usage.service import SUPPORTED_INTERVALS, TokenUsageService
from agent_service.services.favorite.service import FavoriteService
from agent_service.services.privacy.service import PrivacyService
from agent_service.services.feedback.service import FeedbackService
from agent_service.services.vault.service import VaultService
from agent_service.services.agent_change.service import AgentChangeService
from agent_service.services.agent_queue.service import AgentQueueService
from agent_service.services.automation.service import AutomationService
from agent_service.services.activity.service import ActivityService
from agent_service.services.component_library.service import ComponentLibraryService
from agent_service.services.smart_form.service import SmartFormService
from agent_service.services.latex.service import LatexService
from agent_service.services.model_management.service import ModelManagementService
from agent_service.services.storage.service import StorageService

from agent_service.api.grpc.mappers.responses import (
    _build_tool_call_list, _feedback_to_response, _favorite_to_response,
    _knowledge_file_node_to_response, _knowledge_library_to_response,
    _knowledge_rebuild_to_response, _llm_config_preset_to_response,
    _llm_config_to_response, _privacy_to_response, _to_iso,
)

logger = logging.getLogger(__name__)

class SettingsGrpcHandlerMixin:
    def EnsureUserProfile(  # noqa: N802
        self, request: UserProfileRequest, context: grpc.ServicerContext,
    ) -> UserProfileResponse:
        logger.info("EnsureUserProfile user=%s", request.user_id)
        svc = self._require_settings_service(context)
        try:
            profile = svc.ensure_user_profile(user_id=request.user_id)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return UserProfileResponse(
            user_id=profile["user_id"],
            knowledge_dir=profile["knowledge_dir"],
            created_at=profile["created_at"],
            updated_at=profile["updated_at"],
            active_library_id=profile.get("active_library_id", ""),
            active_knowledge_library=_knowledge_library_to_response(
                profile.get("active_knowledge_library") or {}
            ),
            knowledge_libraries=[
                _knowledge_library_to_response(item)
                for item in profile.get("knowledge_libraries", [])
            ],
            ocr_enabled=bool(profile.get("ocr_enabled")),
            vision_understanding_enabled=bool(profile.get("vision_understanding_enabled")),
            auto_ingest_on_upload=bool(profile.get("auto_ingest_on_upload")),
            vlm_enabled=bool(profile.get("vlm_enabled")),
        )

    def GetKnowledgeIngestionConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """返回与 REST相同的基础开关，包括 DSH coding agent。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict(
            self._require_settings_service(context).get_knowledge_ingestion_config(user_id=user_id),
            Struct(),
        )

    def SaveKnowledgeIngestionConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """保存与 REST相同的基础开关，包括 DSH coding agent。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        result = self._require_settings_service(context).save_knowledge_ingestion_config(
            user_id=user_id,
            auto_ingest_on_upload=(bool(payload["auto_ingest_on_upload"]) if "auto_ingest_on_upload" in payload else None),
            ocr_enabled=(bool(payload["ocr_enabled"]) if "ocr_enabled" in payload else None),
            vlm_enabled=(bool(payload["vlm_enabled"]) if "vlm_enabled" in payload else None),
            vision_understanding_enabled=(
                bool(payload["vision_understanding_enabled"])
                if "vision_understanding_enabled" in payload else None
            ),
            dsh_coding_agent_enabled=(
                bool(payload["dsh_coding_agent_enabled"])
                if "dsh_coding_agent_enabled" in payload else None
            ),
            knowledge_ignore_patterns=(
                str(payload["knowledge_ignore_patterns"])
                if "knowledge_ignore_patterns" in payload else None
            ),
        )
        return ParseDict(result, Struct())

    def GetVlmConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """返回与 REST 相同的 MinerU 精准 API 生效配置。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict(self._require_settings_service(context).get_vlm_config(user_id=user_id), Struct())

    def SaveVlmConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """保存与 REST 相同的 MinerU 与 OCR 用户覆盖。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        result = self._require_settings_service(context).save_vlm_config(
            user_id=user_id,
            enabled=(bool(payload["enabled"]) if "enabled" in payload else None),
            api_key=(str(payload["api_key"]) if "api_key" in payload else None),
            model=(str(payload["model"]) if "model" in payload else None),
            max_concurrency=(int(payload["max_concurrency"]) if "max_concurrency" in payload else None),
            max_file_bytes=(int(payload["max_file_bytes"]) if "max_file_bytes" in payload else None),
            max_pages=(int(payload["max_pages"]) if "max_pages" in payload else None),
            submit_rate_per_minute=(int(payload["submit_rate_per_minute"]) if "submit_rate_per_minute" in payload else None),
            result_rate_per_minute=(int(payload["result_rate_per_minute"]) if "result_rate_per_minute" in payload else None),
            ocr_enabled=(bool(payload["ocr_enabled"]) if "ocr_enabled" in payload else None),
        )
        return ParseDict(result, Struct())

    def ListVlmConfigPresets(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """列出当前用户保存的 MinerU 配置。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict({"configs": self._require_settings_service(context).list_vlm_config_presets(user_id=user_id)}, Struct())

    def SaveVlmConfigPreset(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """保存一条 MinerU 模型与限制预设。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        result = self._require_settings_service(context).save_vlm_config_preset(
            user_id=user_id,
            label=str(payload.get("label") or ""),
            api_key=str(payload.get("api_key") or ""),
            model=str(payload.get("model") or ""),
            max_concurrency=int(payload.get("max_concurrency") or 0),
            max_file_bytes=int(payload.get("max_file_bytes") or 0),
            max_pages=int(payload.get("max_pages") or 0),
            submit_rate_per_minute=int(payload.get("submit_rate_per_minute") or 0),
            result_rate_per_minute=int(payload.get("result_rate_per_minute") or 0),
        )
        return ParseDict(result, Struct())

    def DeleteVlmConfigPreset(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """删除当前用户拥有的一条 MinerU 配置。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        deleted = self._require_settings_service(context).delete_vlm_config_preset(
            config_id=str(payload.get("config_id") or ""),
            user_id=user_id,
        )
        return ParseDict({"ok": deleted}, Struct())
    def GetLLMConfig(  # noqa: N802
        self, request: LLMConfigRequest, context: grpc.ServicerContext,
    ) -> LLMConfigResponse:
        logger.info("GetLLMConfig user=%s", request.user_id)
        svc = self._require_settings_service(context)
        try:
            return _llm_config_to_response(svc.get_llm_config(user_id=request.user_id))
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    def SaveLLMConfig(  # noqa: N802
        self, request: LLMConfigSaveRequest, context: grpc.ServicerContext,
    ) -> LLMConfigResponse:
        logger.info("SaveLLMConfig user=%s", request.user_id)
        svc = self._require_settings_service(context)
        try:
            payload = svc.save_llm_config(
                user_id=request.user_id,
                api_key=request.api_key,
                base_url=request.base_url,
                model_name=request.model_name,
                small_api_key=request.small_api_key,
                small_base_url=request.small_base_url,
                small_model_name=request.small_model_name,
                model_context_window_tokens=request.model_context_window_tokens,
                model_max_output_tokens=request.model_max_output_tokens,
                small_model_context_window_tokens=request.small_model_context_window_tokens,
                small_model_max_output_tokens=request.small_model_max_output_tokens,
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return _llm_config_to_response(payload)
    def GetWebSearchConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Return web-search and embedded-browser networking settings."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).get_web_search_config(
                user_id=str(payload.get("user_id") or ""),
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def GetFontConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Return the REST-equivalent independent UI and editor text font settings."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).get_font_config(
                user_id=str(payload.get("user_id") or ""),
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def SaveFontConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Persist the REST-equivalent independent UI and editor text font settings."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).save_font_config(
                user_id=str(payload.get("user_id") or ""),
                ui_font_families=payload.get("ui_font_families"),
                text_font_families=payload.get("text_font_families"),
                ui_font_size_percent=(
                    int(payload["ui_font_size_percent"])
                    if "ui_font_size_percent" in payload
                    else None
                ),
                text_font_size_percent=(
                    int(payload["text_font_size_percent"])
                    if "text_font_size_percent" in payload
                    else None
                ),
                font_size_percent=(
                    int(payload["font_size_percent"])
                    if "font_size_percent" in payload
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def GetAppearanceConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Return REST-equivalent appearance and backlinks visibility settings."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).get_appearance_config(
                user_id=str(payload.get("user_id") or ""),
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def SaveAppearanceConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Persist REST-equivalent appearance and backlinks visibility settings."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).save_appearance_config(
                user_id=str(payload.get("user_id") or ""),
                theme_primary_color=(
                    str(payload["theme_primary_color"])
                    if "theme_primary_color" in payload
                    else None
                ),
                theme_soft_color=(
                    str(payload["theme_soft_color"])
                    if "theme_soft_color" in payload
                    else None
                ),
                tag_colors=(
                    payload["tag_colors"]
                    if "tag_colors" in payload
                    else None
                ),
                tag_colors_translucent=(
                    payload["tag_colors_translucent"]
                    if "tag_colors_translucent" in payload
                    else None
                ),
                reset_tag_colors_translucent=(
                    "tag_colors_translucent" in payload and payload["tag_colors_translucent"] is None
                ),
                background_cover_url=(
                    str(payload["background_cover_url"])
                    if "background_cover_url" in payload
                    else None
                ),
                show_backlinks=(
                    bool(payload["show_backlinks"])
                    if "show_backlinks" in payload
                    else None
                ),
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def SaveWebSearchConfig(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """Persist the REST-equivalent web-search and browser settings payload."""

        payload = MessageToDict(request)
        try:
            result = self._require_settings_service(context).save_web_search_config(
                user_id=str(payload.get("user_id") or ""),
                proxy_url=str(payload["proxy_url"]).strip() if "proxy_url" in payload else None,
                browser_proxy_url=(
                    str(payload["browser_proxy_url"]).strip()
                    if "browser_proxy_url" in payload
                    else None
                ),
                browser_home_url=(
                    str(payload["browser_home_url"]).strip()
                    if "browser_home_url" in payload
                    else None
                ),
                web_search_enabled=(
                    bool(payload["web_search_enabled"])
                    if "web_search_enabled" in payload
                    else None
                ),
                web_search_max_results=(
                    int(payload["web_search_max_results"])
                    if "web_search_max_results" in payload
                    else None
                ),
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
    def ListLLMConfigPresets(  # noqa: N802
        self, request: LLMConfigRequest, context: grpc.ServicerContext,
    ) -> LLMConfigPresetListResponse:
        logger.info("ListLLMConfigPresets user=%s", request.user_id)
        svc = self._require_settings_service(context)
        try:
            presets = svc.list_llm_config_presets(user_id=request.user_id)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return LLMConfigPresetListResponse(
            configs=[_llm_config_preset_to_response(item) for item in presets],
        )
    def SaveLLMConfigPreset(  # noqa: N802
        self, request: LLMConfigPresetSaveRequest, context: grpc.ServicerContext,
    ) -> LLMConfigPresetResponse:
        logger.info("SaveLLMConfigPreset user=%s label=%s", request.user_id, request.label)
        svc = self._require_settings_service(context)
        try:
            preset = svc.save_llm_config_preset(
                user_id=request.user_id,
                label=request.label,
                api_key=request.api_key,
                base_url=request.base_url,
                model_name=request.model_name,
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return _llm_config_preset_to_response(preset)
    def DeleteLLMConfigPreset(  # noqa: N802
        self, request: LLMConfigPresetDeleteRequest, context: grpc.ServicerContext,
    ) -> DeleteResponse:
        logger.info("DeleteLLMConfigPreset config=%s", request.config_id)
        svc = self._require_settings_service(context)
        deleted = svc.delete_llm_config_preset(config_id=request.config_id)
        if not deleted:
            context.abort(grpc.StatusCode.NOT_FOUND, "LLM config preset not found")
        return DeleteResponse(ok=True, deleted_count=1)
    def ListSystemPromptEntries(  # noqa: N802
        self, request: SystemPromptRequest, context: grpc.ServicerContext,
    ) -> SystemPromptEntriesResponse:
        logger.info("ListSystemPromptEntries user=%s", request.user_id)
        svc = self._require_settings_service(context)
        entries = svc.list_system_prompt_entries(user_id=request.user_id)
        return SystemPromptEntriesResponse(
            entries=[SystemPromptEntryResponse(
                prompt_id=e["prompt_id"],
                content=e["content"],
                created_at=e["created_at"],
            ) for e in entries]
        )
    def AddSystemPromptEntry(  # noqa: N802
        self, request: SystemPromptAddRequest, context: grpc.ServicerContext,
    ) -> SystemPromptEntryResponse:
        logger.info("AddSystemPromptEntry user=%s", request.user_id)
        svc = self._require_settings_service(context)
        entry = svc.add_system_prompt_entry(user_id=request.user_id, content=request.content)
        return SystemPromptEntryResponse(
            prompt_id=entry["prompt_id"],
            content=entry["content"],
            created_at=entry["created_at"],
        )
    def DeleteSystemPromptEntry(  # noqa: N802
        self, request: SystemPromptDeleteRequest, context: grpc.ServicerContext,
    ) -> DeleteResponse:
        logger.info("DeleteSystemPromptEntry prompt=%s", request.prompt_id)
        svc = self._require_settings_service(context)
        success = svc.delete_system_prompt_entry(prompt_id=request.prompt_id)
        if not success:
            context.abort(grpc.StatusCode.NOT_FOUND, f"prompt entry {request.prompt_id} not found")
        return DeleteResponse(ok=True, deleted_count=1)
    def ListCustomMemories(  # noqa: N802
        self, request: MemoryListRequest, context: grpc.ServicerContext,
    ) -> MemoryListResponse:
        logger.info("ListCustomMemories user=%s", request.user_id)
        svc = self._require_settings_service(context)
        entries = svc.list_memories(user_id=request.user_id)
        return MemoryListResponse(
            entries=[MemoryEntryResponse(
                memory_id=e["memory_id"],
                content=e["content"],
                importance=e.get("importance", 0.5),
                created_at=e["created_at"],
            ) for e in entries]
        )
    def AddCustomMemory(  # noqa: N802
        self, request: MemoryAddRequest, context: grpc.ServicerContext,
    ) -> MemoryEntryResponse:
        logger.info("AddCustomMemory user=%s", request.user_id)
        svc = self._require_settings_service(context)
        entry = svc.add_memory(
            user_id=request.user_id,
            content=request.content,
            importance=request.importance or 0.5,
        )
        return MemoryEntryResponse(
            memory_id=entry["memory_id"],
            content=entry["content"],
            importance=entry.get("importance", 0.5),
            created_at=entry["created_at"],
        )
    def DeleteCustomMemory(  # noqa: N802
        self, request: MemoryDeleteRequest, context: grpc.ServicerContext,
    ) -> DeleteResponse:
        logger.info("DeleteCustomMemory memory=%s", request.memory_id)
        svc = self._require_settings_service(context)
        success = svc.remove_memory(memory_id=request.memory_id)
        if not success:
            context.abort(grpc.StatusCode.NOT_FOUND, f"memory {request.memory_id} not found")
        return DeleteResponse(ok=True, deleted_count=1)
    def GetModelManagement(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """返回与 REST `/settings/models/management` 相同的模型管理详情。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict(
            self._require_model_management_service(context).get_management_status(user_id=user_id),
            Struct(),
        )

    def GetModelPreferences(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """返回与 REST 模型偏好接口相同的持久化设置。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict(
            self._require_settings_service(context).get_model_preferences(user_id=user_id),
            Struct(),
        )

    def SaveModelPreferences(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """保存模型自动下载偏好。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        if "auto_download_enabled" not in payload:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "auto_download_enabled is required")
        result = self._require_settings_service(context).save_model_preferences(
            user_id=user_id,
            auto_download_enabled=bool(payload["auto_download_enabled"]),
        )
        if result["auto_download_enabled"]:
            self._require_model_management_service(context).initialize_after_startup(user_id=user_id)
        return ParseDict(result, Struct())

    def InitializeModels(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """在客户端界面已启动后触发独立模型任务。"""

        user_id = self._require_struct_user_id(request=request, context=context)
        return ParseDict(
            self._require_model_management_service(context).initialize_after_startup(user_id=user_id),
            Struct(),
        )

    def StartModelDownload(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """在用户确认后启动一个模型下载。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        model = str(payload.get("model") or "")
        try:
            started = self._require_model_management_service(context).start_download(
                model,
                user_id=user_id,
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(
            {"status": "started" if started else "already_running", "model": model},
            Struct(),
        )

    def DeleteManagedModel(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """删除一个受管模型并设置本进程自动下载抑制。"""

        payload = MessageToDict(request)
        user_id = self._require_struct_user_id(request=request, context=context)
        try:
            result = self._require_model_management_service(context).delete_model(
                str(payload.get("model") or ""),
                user_id=user_id,
            )
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(result, Struct())
