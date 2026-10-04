"""Generated from agent_service.proto; regenerate with scripts/generate_grpc.py."""
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union
DESCRIPTOR: _descriptor.FileDescriptor

from ._agent_service_types_0 import GitUserRequest, GitInitRequest, GitHistoryRequest, GitDiffRequest, GitPathsRequest, GitCommitRequest, GitPushRequest, GitBranchRequest, GitRemoteRequest, GitPullRequest, RunRequest, RunResult, ToolCall, TraceEntry, ChunkMessage, SessionCreateRequest, SessionIdRequest, ListSessionsRequest, SessionUpdateRequest, SessionResponse, ListSessionsResponse, DeleteResponse, DeleteAllSessionsRequest, FavoriteListRequest, FavoriteCreateRequest, FavoriteDeleteRequest, FavoriteEntryResponse, FavoriteListResponse, PrivacyListRequest, PrivacyCreateRequest, PrivacyDeleteRequest, PrivacyEntryResponse, PrivacyListResponse, FeedbackCreateRequest, FeedbackListRequest, FeedbackUpdateRequest, FeedbackDeleteRequest, FeedbackEntryResponse, FeedbackListResponse, ListMessagesRequest, MessageEntry, ListMessagesResponse, EventsRequest, EventEntry, EventsResponse, RecallDetailsRequest, RecallDetailsResponse, TaskSuggestionsRequest, TaskSuggestionsResponse, TokenUsageRequest, ActivityHeatmapRequest, ToolListRequest
from ._agent_service_types_1 import ToolInfo, ToolListResponse, CancelRequest, CancelResponse, ChildAgentListRequest, ChildAgentRecord, ChildAgentListResponse, ChildAgentControlRequest, ChildAgentUpdateRequest, ChildAgentControlResponse, UserProfileRequest, UserKnowledgeDirUpdateRequest, UserProfileResponse, AttachmentRawRequest, AttachmentRawResponse, LLMConfigRequest, LLMConfigSaveRequest, LLMConfigResponse, LLMConfigPresetSaveRequest, LLMConfigPresetDeleteRequest, LLMConfigPresetResponse, LLMConfigPresetListResponse, KnowledgeLibraryEntry, KnowledgeRebuildRequest, KnowledgeFileUploadRequest, KnowledgeRebuildResponse, KnowledgeFileTreeRequest, KnowledgeFileNode, KnowledgeFileTreeResponse, KnowledgeFileContentRequest, KnowledgeFileContentResponse, KnowledgePdfPageRequest, KnowledgePdfPageResponse, KnowledgeFileWriteRequest, KnowledgeFileCreateRequest, KnowledgeFolderCreateRequest, KnowledgePathCopyRequest, KnowledgePathDeleteRequest, KnowledgePathRenameRequest, SystemPromptRequest, SystemPromptEntryResponse, SystemPromptEntriesResponse, SystemPromptAddRequest, SystemPromptDeleteRequest, MemoryListRequest, MemoryEntryResponse

class MemoryListResponse(_message.Message):
    __slots__ = ('entries',)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[MemoryEntryResponse]

    def __init__(self, entries: _Optional[_Iterable[_Union[MemoryEntryResponse, _Mapping]]]=...) -> None:
        ...

class MemoryAddRequest(_message.Message):
    __slots__ = ('user_id', 'content', 'importance')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IMPORTANCE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    content: str
    importance: float

    def __init__(self, user_id: _Optional[str]=..., content: _Optional[str]=..., importance: _Optional[float]=...) -> None:
        ...

class MemoryDeleteRequest(_message.Message):
    __slots__ = ('memory_id',)
    MEMORY_ID_FIELD_NUMBER: _ClassVar[int]
    memory_id: str

    def __init__(self, memory_id: _Optional[str]=...) -> None:
        ...
