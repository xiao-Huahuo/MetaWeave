"""gRPC protobuf、Struct 和领域响应转换。

方法体由主 servicer 机械迁移。
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

def _to_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
def _knowledge_rebuild_to_response(result: KnowledgeLibraryRebuildResult) -> KnowledgeRebuildResponse:
    """将知识库重建结果转换为 gRPC 响应。"""

    return KnowledgeRebuildResponse(
        user_id=result.user_id,
        knowledge_dir=result.knowledge_dir,
        frontmatter_dir=result.frontmatter_dir,
        frontmatter_files_seen=result.frontmatter_files_seen,
        frontmatter_files_written=result.frontmatter_files_written,
        frontmatter_files_skipped=result.frontmatter_files_skipped,
        files_seen=result.files_seen,
        files_ingested=result.files_ingested,
        files_skipped=result.files_skipped,
        chunks_created=result.chunks_created,
        chunks_deleted=result.chunks_deleted,
        uploaded_path=result.uploaded_path,
        library_id=result.library_id,
    )
def _favorite_to_response(favorite: Any) -> FavoriteEntryResponse:
    """将收藏 DTO 转换为 gRPC 响应。"""

    return FavoriteEntryResponse(
        favorite_id=str(favorite.favorite_id),
        user_id=str(favorite.user_id),
        library_id=str(favorite.library_id),
        target_type=str(favorite.target_type),
        target_id=str(favorite.target_id),
        created_at=_to_iso(favorite.created_at),
    )
def _privacy_to_response(record: Any) -> PrivacyEntryResponse:
    """将隐私 DTO 转换为 gRPC 响应。"""

    return PrivacyEntryResponse(
        privacy_id=str(record.privacy_id),
        user_id=str(record.user_id),
        library_id=str(record.library_id),
        target_type=str(record.target_type),
        target_id=str(record.target_id),
        created_at=_to_iso(record.created_at),
    )
def _feedback_to_response(feedback: Any) -> FeedbackEntryResponse:
    """将反馈 DTO 转换为 gRPC 响应。"""

    return FeedbackEntryResponse(
        feedback_id=str(feedback.feedback_id),
        user_id=str(feedback.user_id),
        content=str(feedback.content),
        source=str(feedback.source),
        page=str(feedback.page),
        created_at=_to_iso(feedback.created_at),
    )
def _llm_config_to_response(payload: dict[str, Any]) -> LLMConfigResponse:
    """将 LLM 配置字典转换为 gRPC 响应。"""

    return LLMConfigResponse(
        user_id=str(payload.get("user_id", "")),
        api_key=str(payload.get("api_key", "")),
        base_url=str(payload.get("base_url", "")),
        model_name=str(payload.get("model_name", "")),
        small_api_key=str(payload.get("small_api_key", "")),
        small_base_url=str(payload.get("small_base_url", "")),
        small_model_name=str(payload.get("small_model_name", "")),
        vision_api_key=str(payload.get("vision_api_key", "")),
        vision_base_url=str(payload.get("vision_base_url", "")),
        vision_model_name=str(payload.get("vision_model_name", "")),
        effective_small_api_key=str(payload.get("effective_small_api_key", "")),
        effective_small_base_url=str(payload.get("effective_small_base_url", "")),
        effective_small_model_name=str(payload.get("effective_small_model_name", "")),
        updated_at=str(payload.get("updated_at", "")),
        effective_api_key=str(payload.get("effective_api_key", "")),
        effective_base_url=str(payload.get("effective_base_url", "")),
        effective_model_name=str(payload.get("effective_model_name", "")),
        effective_model_source=str(payload.get("effective_model_source", "")),
        effective_small_model_source=str(payload.get("effective_small_model_source", "")),
        effective_vision_api_key=str(payload.get("effective_vision_api_key", "")),
        effective_vision_base_url=str(payload.get("effective_vision_base_url", "")),
        effective_vision_model_name=str(payload.get("effective_vision_model_name", "")),
        effective_vision_model_source=str(payload.get("effective_vision_model_source", "")),
        model_context_window_tokens=int(payload.get("model_context_window_tokens", 0)),
        model_max_output_tokens=int(payload.get("model_max_output_tokens", 0)),
        small_model_context_window_tokens=int(payload.get("small_model_context_window_tokens", 0)),
        small_model_max_output_tokens=int(payload.get("small_model_max_output_tokens", 0)),
    )
def _llm_config_preset_to_response(payload: dict[str, Any]) -> LLMConfigPresetResponse:
    """将已保存 LLM 配置字典转换为 gRPC 响应。"""

    return LLMConfigPresetResponse(
        config_id=str(payload.get("config_id", "")),
        user_id=str(payload.get("user_id", "")),
        label=str(payload.get("label", "")),
        api_key=str(payload.get("api_key", "")),
        base_url=str(payload.get("base_url", "")),
        model_name=str(payload.get("model_name", "")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )
def _knowledge_library_to_response(payload: dict[str, Any]) -> KnowledgeLibraryEntry:
    """将知识库配置字典转换为 gRPC 响应。"""

    return KnowledgeLibraryEntry(
        library_id=str(payload.get("library_id", "")),
        user_id=str(payload.get("user_id", "")),
        name=str(payload.get("name", "")),
        knowledge_dir=str(payload.get("knowledge_dir", "")),
        is_active=bool(payload.get("is_active", False)),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )
def _knowledge_file_node_to_response(payload: dict[str, Any]) -> KnowledgeFileNode:
    """将文件树节点字典转换为 gRPC 响应。"""

    return KnowledgeFileNode(
        name=str(payload.get("name", "")),
        path=str(payload.get("path", "")),
        is_dir=bool(payload.get("isDir", False)),
        mtime=str(payload.get("mtime", "")),
        index_status=str(payload.get("indexStatus", "")),
        size=int(payload.get("size", 0)),
        children=[
            _knowledge_file_node_to_response(child)
            for child in payload.get("children", [])
        ],
        graph_status=str(payload.get("graphStatus", "")),
        created_at=str(payload.get("createdAt", "")),
    )
def _build_tool_call_list(tool_calls: list | None) -> list:
    """将数据库中的 tool_calls JSON 列表转换为 proto ToolCall 消息列表。"""
    result = []
    for tc in (tool_calls or []):
        if isinstance(tc, dict):
            result.append(
                ToolCall(
                    name=tc.get("name", ""),
                    args=tc.get("args", {}),
                    id=tc.get("id", ""),
                )
            )
    return result

class GrpcResponseMapperMixin:
    @staticmethod
    def _component_library_struct(
        context: grpc.ServicerContext,
        function: Any,
        **kwargs: Any,
    ) -> Struct:
        """Run a component library operation and map validation to gRPC errors."""

        try:
            payload = function(**kwargs)
        except FileNotFoundError as exc:
            context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(payload, Struct())
    def _vault_session_from_payload(self, context: grpc.ServicerContext, payload: dict[str, Any]) -> Any:
        """从 Struct payload 中校验 vault token。"""

        try:
            return self._require_vault_service(context).verify_token(str(payload.get("token", "")))
        except ValueError as exc:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, str(exc))
    def _vault_item_ids_call(self, request: Struct, context: grpc.ServicerContext, function: Any) -> Struct:
        """执行只需要 token 和 item_ids 的密码库方法。"""

        payload = MessageToDict(request)
        return self._vault_struct(
            context,
            function,
            session=self._vault_session_from_payload(context, payload),
            item_ids=[str(item) for item in payload.get("item_ids", [])],
        )
    @staticmethod
    def _vault_struct(context: grpc.ServicerContext, function: Any, **kwargs: Any) -> Struct:
        """执行密码库方法并转换为 protobuf Struct。"""

        try:
            payload = function(**kwargs)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(payload, Struct())
    @staticmethod
    def _git_struct(
        context: grpc.ServicerContext,
        function: Any,
        **kwargs: Any,
    ) -> Struct:
        """执行 Git 领域方法并转换为 protobuf Struct。"""

        try:
            payload = function(**kwargs)
        except (GitServiceError, ValueError) as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return ParseDict(payload, Struct())
    @staticmethod
    def _stream_from_dicts(events_iter: Any) -> Any:
        """将 dict 事件流转换为 ChunkMessage 流,客户端断开时传播取消信号。"""
        try:
            for payload in events_iter:
                tool_calls = []
                for tc in payload.get("tool_calls", []) or []:
                    tool_calls.append(
                        ToolCall(
                            name=tc.get("name", ""),
                            args=tc.get("args", {}),
                            id=tc.get("id", ""),
                        )
                    )

                trace_entries = []
                for te in payload.get("trace", []) or []:
                    trace_entries.append(
                        TraceEntry(
                            node=te.get("node", ""),
                            event=te.get("event", ""),
                            error_type=te.get("error_type", ""),
                            message=te.get("message", ""),
                        )
                    )

                yield ChunkMessage(
                    node=payload.get("node", ""),
                    content=payload.get("content", ""),
                    tool_calls=tool_calls,
                    trace=trace_entries,
                    done=False,
                    model_name=payload.get("model_name", ""),
                    type=payload.get("type", ""),
                    context_messages=payload.get("context_messages", []),
                    metadata=payload.get("metadata", {}),
                    error=payload.get("error", ""),
                )

            yield ChunkMessage(done=True)
        except GeneratorExit:
            try:
                events_iter.close()
            except GeneratorExit:
                pass
            raise
    @staticmethod
    def _build_run_result(result: dict[str, Any]) -> RunResult:
        return RunResult(
            graph_diagram=result.get("graph_diagram", ""),
            final_output=result.get("final_output", ""),
            events=result.get("events", []),
            graph_diagram_path=result.get("graph_diagram_path", ""),
        )
    @staticmethod
    def _session_to_response(session: Any) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            session_name=session.session_name or "",
            created_at=_to_iso(session.created_at),
            updated_at=_to_iso(session.updated_at),
        )
