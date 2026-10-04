"""
AgentService gRPC Servicer 实现。

功能说明:
本文件实现 agent_service.proto 定义的 AgentServiceServicer。
1. AgentCore 流式 / 非流式 RPC。
2. SessionService CRUD RPC。
3. 消息历史与 trace 事件 RPC。

由 main.py 注入 AgentCore + SessionService + MessageService:
    servicer = AgentServiceServicer(agent=agent, session_service=session_service, message_service=message_service)
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
from agent_service.services.unified_search import UnifiedSearchService
from agent_service.services.smart_form.service import SmartFormService
from agent_service.services.latex.service import LatexService
from agent_service.services.model_management.service import ModelManagementService
from agent_service.services.session_attachment.service import SessionAttachmentService
from agent_service.services.storage.service import StorageService

logger = logging.getLogger(__name__)


from agent_service.api.grpc.handlers.agent import AgentGrpcHandlerMixin
from agent_service.api.grpc.handlers.auth import AuthGrpcHandlerMixin
from agent_service.api.grpc.handlers.agent_queue import AgentQueueGrpcHandlerMixin
from agent_service.api.grpc.handlers.automation import AutomationGrpcHandlerMixin
from agent_service.api.grpc.handlers.component_library import ComponentLibraryGrpcHandlerMixin
from agent_service.api.grpc.handlers.git import GitGrpcHandlerMixin
from agent_service.api.grpc.handlers.knowledge import KnowledgeGrpcHandlerMixin
from agent_service.api.grpc.handlers.latex import LatexGrpcHandlerMixin
from agent_service.api.grpc.handlers.sessions import SessionsGrpcHandlerMixin
from agent_service.api.grpc.handlers.settings import SettingsGrpcHandlerMixin
from agent_service.api.grpc.handlers.smart_forms import SmartFormsGrpcHandlerMixin
from agent_service.api.grpc.handlers.user_data import UserDataGrpcHandlerMixin
from agent_service.api.grpc.handlers.vault import VaultGrpcHandlerMixin

from agent_service.api.grpc.mappers import GrpcErrorMapperMixin, GrpcResponseMapperMixin
from agent_service.api.grpc.mappers.responses import (
    _build_tool_call_list, _feedback_to_response, _favorite_to_response,
    _knowledge_file_node_to_response, _knowledge_library_to_response,
    _knowledge_rebuild_to_response, _llm_config_preset_to_response,
    _llm_config_to_response, _privacy_to_response, _to_iso,
)

from agent_service.api.grpc.handlers.mcp import McpGrpcHandlerMixin

class AgentServiceServicer(AuthGrpcHandlerMixin, McpGrpcHandlerMixin, GrpcErrorMapperMixin, GrpcResponseMapperMixin, AgentGrpcHandlerMixin, AgentQueueGrpcHandlerMixin, AutomationGrpcHandlerMixin, ComponentLibraryGrpcHandlerMixin, GitGrpcHandlerMixin, KnowledgeGrpcHandlerMixin, LatexGrpcHandlerMixin, SessionsGrpcHandlerMixin, SettingsGrpcHandlerMixin, SmartFormsGrpcHandlerMixin, UserDataGrpcHandlerMixin, VaultGrpcHandlerMixin, BaseServicer):
    """AgentService gRPC Servicer。"""

    def __init__(
        self,
        *,
        agent: AgentCore,
        session_service: SessionService,
        message_service: MessageService | None = None,
        settings_service: SettingsService | None = None,
        knowledge_library_service: KnowledgeLibraryService | None = None,
        knowledge_ingestion_job_service: KnowledgeIngestionJobService | None = None,
        git_service: GitService | None = None,
        favorite_service: FavoriteService | None = None,
        privacy_service: PrivacyService | None = None,
        feedback_service: FeedbackService | None = None,
        vault_service: VaultService | None = None,
        auth_service: Any = None,
        agent_change_service: AgentChangeService | None = None,
        agent_queue_service: AgentQueueService | None = None,
        automation_service: AutomationService | None = None,
        activity_service: ActivityService | None = None,
        component_library_service: ComponentLibraryService | None = None,
        unified_search_service: UnifiedSearchService | None = None,
        smart_form_service: SmartFormService | None = None,
        latex_service: LatexService | None = None,
        model_management_service: ModelManagementService | None = None,
        attachment_service: SessionAttachmentService | None = None,
        mcp_client_service: Any = None,
        mcp_server_service: Any = None,
    ) -> None:
        self._mcp_client_service = mcp_client_service
        self._mcp_server_service = mcp_server_service
        self._agent = agent
        self._limits = getattr(getattr(agent, "config", None), "limits", DEFAULT_BUSINESS_LIMITS)
        self._session_service = session_service
        self._message_service = message_service
        self._settings_service = settings_service
        self._knowledge_library_service = knowledge_library_service
        self._knowledge_ingestion_job_service = knowledge_ingestion_job_service
        self._git_service = git_service
        self._favorite_service = favorite_service
        self._privacy_service = privacy_service
        self._feedback_service = feedback_service
        self._vault_service = vault_service
        self._auth_service = auth_service
        self._agent_change_service = agent_change_service
        self._agent_queue_service = agent_queue_service
        self._automation_service = automation_service
        self._activity_service = activity_service
        self._component_library_service = component_library_service
        self._unified_search_service = unified_search_service
        self._smart_form_service = smart_form_service
        self._latex_service = latex_service
        self._model_management_service = model_management_service
        self._attachment_service = attachment_service
        # Auth-less instances support isolated handler unit checks only. The
        # generated registration boundary refuses to expose them as a transport.
        if auth_service is not None:
            self._install_rpc_auth()

    def shutdown(self) -> None:
        self._agent.close()

    # ------------------------------------------------------------------
    # Agent 流式 RPC
    # ------------------------------------------------------------------



    # ------------------------------------------------------------------
    # Agent 非流式 RPC
    # ------------------------------------------------------------------



    # ------------------------------------------------------------------
    # Session 管理 RPC
    # ------------------------------------------------------------------







    # ------------------------------------------------------------------
    # 用户收藏 RPC
    # ------------------------------------------------------------------





























    # ------------------------------------------------------------------
    # 取消执行 RPC
    # ------------------------------------------------------------------





    # ------------------------------------------------------------------
    # 消息历史 RPC
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # 观测 / trace 事件 RPC
    # ------------------------------------------------------------------







    # ------------------------------------------------------------------
    # 用户设置 — 系统提示词条目
    # ------------------------------------------------------------------




























    # ------------------------------------------------------------------
    # 知识库 Git 管理 RPC
    # ------------------------------------------------------------------















    # ------------------------------------------------------------------
    # 用户设置 — 自定义长期记忆
    # ------------------------------------------------------------------




    # ------------------------------------------------------------------
    # 持久任务队列 RPC
    # ------------------------------------------------------------------








    # ------------------------------------------------------------------
    # LaTeX 运行时与编译 RPC
    # ------------------------------------------------------------------









    # ------------------------------------------------------------------
    # 定时自动化 RPC
    # ------------------------------------------------------------------
















    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
