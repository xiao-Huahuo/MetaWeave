"""vault 领域 gRPC RPC handlers。

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

class VaultGrpcHandlerMixin:
    def VaultStatus(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """读取密码库设置状态。"""

        payload = MessageToDict(request)
        return self._vault_struct(context, self._require_vault_service(context).status, session=self._vault_session_from_payload(context, payload))
    def VaultListItems(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """列出密码库条目。"""

        payload = MessageToDict(request)
        session = self._vault_session_from_payload(context, payload)
        return self._vault_struct(
            context,
            self._require_vault_service(context).list_items,
            session=session,
            query=str(payload.get("query", "")),
            tag=str(payload.get("tag", "")),
            item_type=str(payload.get("item_type", "")),
            trash=bool(payload.get("trash", False)),
        )
    def VaultGetItem(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """读取密码库条目。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            self._require_vault_service(context).get_item,
            session=self._vault_session_from_payload(context, payload),
            item_id=str(payload.get("item_id", "")),
        )
    def VaultCreateItem(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """创建密码库条目。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            self._require_vault_service(context).create_item,
            session=self._vault_session_from_payload(context, payload),
            item_type=str(payload.get("item_type", "")),
            fields=dict(payload.get("fields", {}) or {}),
            tags=[str(item) for item in payload.get("tags", [])],
            asset_ids=[str(item) for item in payload.get("asset_ids", [])],
        )
    def VaultUpdateItem(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """更新密码库条目。"""

        payload = MessageToDict(request)
        item_id = str(payload.pop("item_id", ""))
        token = str(payload.pop("token", ""))
        return self._vault_struct(
            context,
            self._require_vault_service(context).update_item,
            session=self._vault_session_from_payload(context, {"token": token}),
            item_id=item_id,
            payload=payload,
        )
    def VaultMoveToTrash(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """密码库条目移入回收站。"""

        return self._vault_item_ids_call(request, context, self._require_vault_service(context).move_to_trash)
    def VaultRestoreItems(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """恢复密码库回收站条目。"""

        return self._vault_item_ids_call(request, context, self._require_vault_service(context).restore_items)
    def VaultPurgeItems(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """永久删除密码库条目。"""

        return self._vault_item_ids_call(request, context, self._require_vault_service(context).purge_items)
    def VaultExportItems(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """导出密码库条目。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            self._require_vault_service(context).export_items,
            session=self._vault_session_from_payload(context, payload),
            item_ids=[str(item) for item in payload.get("item_ids", [])] or None,
        )
    def VaultImportItems(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """导入密码库条目。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            self._require_vault_service(context).import_items,
            session=self._vault_session_from_payload(context, payload),
            raw_items=list(payload.get("items", []) or []),
        )
    def VaultListTags(self, request: Struct, context: grpc.ServicerContext) -> Struct:  # noqa: N802
        """列出密码库标签。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            self._require_vault_service(context).list_tags,
            session=self._vault_session_from_payload(context, payload),
        )
