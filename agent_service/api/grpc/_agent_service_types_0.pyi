"""Generated from agent_service.proto; regenerate with scripts/generate_grpc.py."""
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union
DESCRIPTOR: _descriptor.FileDescriptor

from ._agent_service_types_1 import ToolInfo, ToolListResponse, CancelRequest, CancelResponse, ChildAgentListRequest, ChildAgentRecord, ChildAgentListResponse, ChildAgentControlRequest, ChildAgentUpdateRequest, ChildAgentControlResponse, UserProfileRequest, UserKnowledgeDirUpdateRequest, UserProfileResponse, AttachmentRawRequest, AttachmentRawResponse, LLMConfigRequest, LLMConfigSaveRequest, LLMConfigResponse, LLMConfigPresetSaveRequest, LLMConfigPresetDeleteRequest, LLMConfigPresetResponse, LLMConfigPresetListResponse, KnowledgeLibraryEntry, KnowledgeRebuildRequest, KnowledgeFileUploadRequest, KnowledgeRebuildResponse, KnowledgeFileTreeRequest, KnowledgeFileNode, KnowledgeFileTreeResponse, KnowledgeFileContentRequest, KnowledgeFileContentResponse, KnowledgePdfPageRequest, KnowledgePdfPageResponse, KnowledgeFileWriteRequest, KnowledgeFileCreateRequest, KnowledgeFolderCreateRequest, KnowledgePathCopyRequest, KnowledgePathDeleteRequest, KnowledgePathRenameRequest, SystemPromptRequest, SystemPromptEntryResponse, SystemPromptEntriesResponse, SystemPromptAddRequest, SystemPromptDeleteRequest, MemoryListRequest, MemoryEntryResponse
from ._agent_service_types_2 import MemoryListResponse, MemoryAddRequest, MemoryDeleteRequest

class GitUserRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class GitInitRequest(_message.Message):
    __slots__ = ('user_id', 'initial_branch')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    INITIAL_BRANCH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    initial_branch: str

    def __init__(self, user_id: _Optional[str]=..., initial_branch: _Optional[str]=...) -> None:
        ...

class GitHistoryRequest(_message.Message):
    __slots__ = ('user_id', 'limit')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    limit: int

    def __init__(self, user_id: _Optional[str]=..., limit: _Optional[int]=...) -> None:
        ...

class GitDiffRequest(_message.Message):
    __slots__ = ('user_id', 'path', 'staged')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    STAGED_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str
    staged: bool

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=..., staged: bool=...) -> None:
        ...

class GitPathsRequest(_message.Message):
    __slots__ = ('user_id', 'paths')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATHS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    paths: _containers.RepeatedScalarFieldContainer[str]

    def __init__(self, user_id: _Optional[str]=..., paths: _Optional[_Iterable[str]]=...) -> None:
        ...

class GitCommitRequest(_message.Message):
    __slots__ = ('user_id', 'paths', 'message')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATHS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    paths: _containers.RepeatedScalarFieldContainer[str]
    message: str

    def __init__(self, user_id: _Optional[str]=..., paths: _Optional[_Iterable[str]]=..., message: _Optional[str]=...) -> None:
        ...

class GitPushRequest(_message.Message):
    __slots__ = ('user_id', 'local_branch', 'remote', 'remote_branch', 'force_with_lease', 'set_upstream', 'all_branches')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LOCAL_BRANCH_FIELD_NUMBER: _ClassVar[int]
    REMOTE_FIELD_NUMBER: _ClassVar[int]
    REMOTE_BRANCH_FIELD_NUMBER: _ClassVar[int]
    FORCE_WITH_LEASE_FIELD_NUMBER: _ClassVar[int]
    SET_UPSTREAM_FIELD_NUMBER: _ClassVar[int]
    ALL_BRANCHES_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    local_branch: str
    remote: str
    remote_branch: str
    force_with_lease: bool
    set_upstream: bool
    all_branches: bool

    def __init__(self, user_id: _Optional[str]=..., local_branch: _Optional[str]=..., remote: _Optional[str]=..., remote_branch: _Optional[str]=..., force_with_lease: bool=..., set_upstream: bool=..., all_branches: bool=...) -> None:
        ...

class GitBranchRequest(_message.Message):
    __slots__ = ('user_id', 'name', 'checkout')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CHECKOUT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    name: str
    checkout: bool

    def __init__(self, user_id: _Optional[str]=..., name: _Optional[str]=..., checkout: bool=...) -> None:
        ...

class GitRemoteRequest(_message.Message):
    __slots__ = ('user_id', 'name', 'url')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    name: str
    url: str

    def __init__(self, user_id: _Optional[str]=..., name: _Optional[str]=..., url: _Optional[str]=...) -> None:
        ...

class GitPullRequest(_message.Message):
    __slots__ = ('user_id', 'remote', 'branch')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    REMOTE_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    remote: str
    branch: str

    def __init__(self, user_id: _Optional[str]=..., remote: _Optional[str]=..., branch: _Optional[str]=...) -> None:
        ...

class RunRequest(_message.Message):
    __slots__ = ('prompt', 'user_id', 'session_id', 'reference', 'agent_mode', 'agent_access_mode')
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    AGENT_MODE_FIELD_NUMBER: _ClassVar[int]
    AGENT_ACCESS_MODE_FIELD_NUMBER: _ClassVar[int]
    prompt: str
    user_id: str
    session_id: str
    reference: str
    agent_mode: str
    agent_access_mode: str

    def __init__(self, prompt: _Optional[str]=..., user_id: _Optional[str]=..., session_id: _Optional[str]=..., reference: _Optional[str]=..., agent_mode: _Optional[str]=..., agent_access_mode: _Optional[str]=...) -> None:
        ...

class RunResult(_message.Message):
    __slots__ = ('graph_diagram', 'final_output', 'events', 'graph_diagram_path')
    GRAPH_DIAGRAM_FIELD_NUMBER: _ClassVar[int]
    FINAL_OUTPUT_FIELD_NUMBER: _ClassVar[int]
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    GRAPH_DIAGRAM_PATH_FIELD_NUMBER: _ClassVar[int]
    graph_diagram: str
    final_output: str
    events: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    graph_diagram_path: str

    def __init__(self, graph_diagram: _Optional[str]=..., final_output: _Optional[str]=..., events: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]]=..., graph_diagram_path: _Optional[str]=...) -> None:
        ...

class ToolCall(_message.Message):
    __slots__ = ('name', 'args', 'id')
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    args: _struct_pb2.Struct
    id: str

    def __init__(self, name: _Optional[str]=..., args: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., id: _Optional[str]=...) -> None:
        ...

class TraceEntry(_message.Message):
    __slots__ = ('node', 'event', 'error_type', 'message')
    NODE_FIELD_NUMBER: _ClassVar[int]
    EVENT_FIELD_NUMBER: _ClassVar[int]
    ERROR_TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    node: str
    event: str
    error_type: str
    message: str

    def __init__(self, node: _Optional[str]=..., event: _Optional[str]=..., error_type: _Optional[str]=..., message: _Optional[str]=...) -> None:
        ...

class ChunkMessage(_message.Message):
    __slots__ = ('node', 'content', 'tool_calls', 'trace', 'done', 'model_name', 'type', 'context_messages', 'metadata', 'error')
    NODE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    TRACE_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    node: str
    content: str
    tool_calls: _containers.RepeatedCompositeFieldContainer[ToolCall]
    trace: _containers.RepeatedCompositeFieldContainer[TraceEntry]
    done: bool
    model_name: str
    type: str
    context_messages: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    metadata: _struct_pb2.Struct
    error: str

    def __init__(self, node: _Optional[str]=..., content: _Optional[str]=..., tool_calls: _Optional[_Iterable[_Union[ToolCall, _Mapping]]]=..., trace: _Optional[_Iterable[_Union[TraceEntry, _Mapping]]]=..., done: bool=..., model_name: _Optional[str]=..., type: _Optional[str]=..., context_messages: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]]=..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., error: _Optional[str]=...) -> None:
        ...

class SessionCreateRequest(_message.Message):
    __slots__ = ('user_id', 'session_name')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_name: str

    def __init__(self, user_id: _Optional[str]=..., session_name: _Optional[str]=...) -> None:
        ...

class SessionIdRequest(_message.Message):
    __slots__ = ('session_id',)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str

    def __init__(self, session_id: _Optional[str]=...) -> None:
        ...

class ListSessionsRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class SessionUpdateRequest(_message.Message):
    __slots__ = ('session_id', 'session_name')
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_NAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    session_name: str

    def __init__(self, session_id: _Optional[str]=..., session_name: _Optional[str]=...) -> None:
        ...

class SessionResponse(_message.Message):
    __slots__ = ('session_id', 'user_id', 'session_name', 'created_at', 'updated_at')
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_NAME_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    session_name: str
    created_at: str
    updated_at: str

    def __init__(self, session_id: _Optional[str]=..., user_id: _Optional[str]=..., session_name: _Optional[str]=..., created_at: _Optional[str]=..., updated_at: _Optional[str]=...) -> None:
        ...

class ListSessionsResponse(_message.Message):
    __slots__ = ('sessions',)
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    sessions: _containers.RepeatedCompositeFieldContainer[SessionResponse]

    def __init__(self, sessions: _Optional[_Iterable[_Union[SessionResponse, _Mapping]]]=...) -> None:
        ...

class DeleteResponse(_message.Message):
    __slots__ = ('ok', 'deleted_count')
    OK_FIELD_NUMBER: _ClassVar[int]
    DELETED_COUNT_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    deleted_count: int

    def __init__(self, ok: bool=..., deleted_count: _Optional[int]=...) -> None:
        ...

class DeleteAllSessionsRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class FavoriteListRequest(_message.Message):
    __slots__ = ('user_id', 'target_type', 'library_id', 'filter_library')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    FILTER_LIBRARY_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    target_type: str
    library_id: str
    filter_library: bool

    def __init__(self, user_id: _Optional[str]=..., target_type: _Optional[str]=..., library_id: _Optional[str]=..., filter_library: bool=...) -> None:
        ...

class FavoriteCreateRequest(_message.Message):
    __slots__ = ('user_id', 'library_id', 'target_type', 'target_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    library_id: str
    target_type: str
    target_id: str

    def __init__(self, user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=...) -> None:
        ...

class FavoriteDeleteRequest(_message.Message):
    __slots__ = ('user_id', 'library_id', 'target_type', 'target_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    library_id: str
    target_type: str
    target_id: str

    def __init__(self, user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=...) -> None:
        ...

class FavoriteEntryResponse(_message.Message):
    __slots__ = ('favorite_id', 'user_id', 'library_id', 'target_type', 'target_id', 'created_at')
    FAVORITE_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    favorite_id: str
    user_id: str
    library_id: str
    target_type: str
    target_id: str
    created_at: str

    def __init__(self, favorite_id: _Optional[str]=..., user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=..., created_at: _Optional[str]=...) -> None:
        ...

class FavoriteListResponse(_message.Message):
    __slots__ = ('favorites',)
    FAVORITES_FIELD_NUMBER: _ClassVar[int]
    favorites: _containers.RepeatedCompositeFieldContainer[FavoriteEntryResponse]

    def __init__(self, favorites: _Optional[_Iterable[_Union[FavoriteEntryResponse, _Mapping]]]=...) -> None:
        ...

class PrivacyListRequest(_message.Message):
    __slots__ = ('user_id', 'target_type', 'library_id', 'filter_library')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    FILTER_LIBRARY_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    target_type: str
    library_id: str
    filter_library: bool

    def __init__(self, user_id: _Optional[str]=..., target_type: _Optional[str]=..., library_id: _Optional[str]=..., filter_library: bool=...) -> None:
        ...

class PrivacyCreateRequest(_message.Message):
    __slots__ = ('user_id', 'library_id', 'target_type', 'target_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    library_id: str
    target_type: str
    target_id: str

    def __init__(self, user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=...) -> None:
        ...

class PrivacyDeleteRequest(_message.Message):
    __slots__ = ('user_id', 'library_id', 'target_type', 'target_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    library_id: str
    target_type: str
    target_id: str

    def __init__(self, user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=...) -> None:
        ...

class PrivacyEntryResponse(_message.Message):
    __slots__ = ('privacy_id', 'user_id', 'library_id', 'target_type', 'target_id', 'created_at')
    PRIVACY_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    privacy_id: str
    user_id: str
    library_id: str
    target_type: str
    target_id: str
    created_at: str

    def __init__(self, privacy_id: _Optional[str]=..., user_id: _Optional[str]=..., library_id: _Optional[str]=..., target_type: _Optional[str]=..., target_id: _Optional[str]=..., created_at: _Optional[str]=...) -> None:
        ...

class PrivacyListResponse(_message.Message):
    __slots__ = ('privacy',)
    PRIVACY_FIELD_NUMBER: _ClassVar[int]
    privacy: _containers.RepeatedCompositeFieldContainer[PrivacyEntryResponse]

    def __init__(self, privacy: _Optional[_Iterable[_Union[PrivacyEntryResponse, _Mapping]]]=...) -> None:
        ...

class FeedbackCreateRequest(_message.Message):
    __slots__ = ('user_id', 'content', 'source', 'page')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    content: str
    source: str
    page: str

    def __init__(self, user_id: _Optional[str]=..., content: _Optional[str]=..., source: _Optional[str]=..., page: _Optional[str]=...) -> None:
        ...

class FeedbackListRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class FeedbackUpdateRequest(_message.Message):
    __slots__ = ('feedback_id', 'content')
    FEEDBACK_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    feedback_id: str
    content: str

    def __init__(self, feedback_id: _Optional[str]=..., content: _Optional[str]=...) -> None:
        ...

class FeedbackDeleteRequest(_message.Message):
    __slots__ = ('feedback_id',)
    FEEDBACK_ID_FIELD_NUMBER: _ClassVar[int]
    feedback_id: str

    def __init__(self, feedback_id: _Optional[str]=...) -> None:
        ...

class FeedbackEntryResponse(_message.Message):
    __slots__ = ('feedback_id', 'user_id', 'content', 'source', 'page', 'created_at')
    FEEDBACK_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    feedback_id: str
    user_id: str
    content: str
    source: str
    page: str
    created_at: str

    def __init__(self, feedback_id: _Optional[str]=..., user_id: _Optional[str]=..., content: _Optional[str]=..., source: _Optional[str]=..., page: _Optional[str]=..., created_at: _Optional[str]=...) -> None:
        ...

class FeedbackListResponse(_message.Message):
    __slots__ = ('feedback',)
    FEEDBACK_FIELD_NUMBER: _ClassVar[int]
    feedback: _containers.RepeatedCompositeFieldContainer[FeedbackEntryResponse]

    def __init__(self, feedback: _Optional[_Iterable[_Union[FeedbackEntryResponse, _Mapping]]]=...) -> None:
        ...

class ListMessagesRequest(_message.Message):
    __slots__ = ('user_id', 'session_id', 'limit')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_id: str
    limit: int

    def __init__(self, user_id: _Optional[str]=..., session_id: _Optional[str]=..., limit: _Optional[int]=...) -> None:
        ...

class MessageEntry(_message.Message):
    __slots__ = ('message_id', 'session_id', 'user_id', 'role', 'content', 'tool_calls', 'metadata', 'created_at')
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    session_id: str
    user_id: str
    role: str
    content: str
    tool_calls: _containers.RepeatedCompositeFieldContainer[ToolCall]
    metadata: _struct_pb2.Struct
    created_at: str

    def __init__(self, message_id: _Optional[str]=..., session_id: _Optional[str]=..., user_id: _Optional[str]=..., role: _Optional[str]=..., content: _Optional[str]=..., tool_calls: _Optional[_Iterable[_Union[ToolCall, _Mapping]]]=..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., created_at: _Optional[str]=...) -> None:
        ...

class ListMessagesResponse(_message.Message):
    __slots__ = ('messages',)
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    messages: _containers.RepeatedCompositeFieldContainer[MessageEntry]

    def __init__(self, messages: _Optional[_Iterable[_Union[MessageEntry, _Mapping]]]=...) -> None:
        ...

class EventsRequest(_message.Message):
    __slots__ = ('user_id', 'session_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_id: str

    def __init__(self, user_id: _Optional[str]=..., session_id: _Optional[str]=...) -> None:
        ...

class EventEntry(_message.Message):
    __slots__ = ('message_id', 'role', 'node', 'content', 'tool_calls', 'created_at', 'metadata')
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    NODE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    role: str
    node: str
    content: str
    tool_calls: _containers.RepeatedCompositeFieldContainer[ToolCall]
    created_at: str
    metadata: _struct_pb2.Struct

    def __init__(self, message_id: _Optional[str]=..., role: _Optional[str]=..., node: _Optional[str]=..., content: _Optional[str]=..., tool_calls: _Optional[_Iterable[_Union[ToolCall, _Mapping]]]=..., created_at: _Optional[str]=..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=...) -> None:
        ...

class EventsResponse(_message.Message):
    __slots__ = ('session_id', 'user_id', 'event_count', 'events')
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    event_count: int
    events: _containers.RepeatedCompositeFieldContainer[EventEntry]

    def __init__(self, session_id: _Optional[str]=..., user_id: _Optional[str]=..., event_count: _Optional[int]=..., events: _Optional[_Iterable[_Union[EventEntry, _Mapping]]]=...) -> None:
        ...

class RecallDetailsRequest(_message.Message):
    __slots__ = ('user_id', 'session_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_id: str

    def __init__(self, user_id: _Optional[str]=..., session_id: _Optional[str]=...) -> None:
        ...

class RecallDetailsResponse(_message.Message):
    __slots__ = ('session_id', 'user_id', 'created_at', 'query', 'rag_metrics', 'memory_recall', 'knowledge_recall')
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    RAG_METRICS_FIELD_NUMBER: _ClassVar[int]
    MEMORY_RECALL_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_RECALL_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    created_at: str
    query: str
    rag_metrics: _struct_pb2.Struct
    memory_recall: _struct_pb2.Struct
    knowledge_recall: _struct_pb2.Struct

    def __init__(self, session_id: _Optional[str]=..., user_id: _Optional[str]=..., created_at: _Optional[str]=..., query: _Optional[str]=..., rag_metrics: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., memory_recall: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., knowledge_recall: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=...) -> None:
        ...

class TaskSuggestionsRequest(_message.Message):
    __slots__ = ('user_id', 'session_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_id: str

    def __init__(self, user_id: _Optional[str]=..., session_id: _Optional[str]=...) -> None:
        ...

class TaskSuggestionsResponse(_message.Message):
    __slots__ = ('suggestions',)
    SUGGESTIONS_FIELD_NUMBER: _ClassVar[int]
    suggestions: _containers.RepeatedScalarFieldContainer[str]

    def __init__(self, suggestions: _Optional[_Iterable[str]]=...) -> None:
        ...

class TokenUsageRequest(_message.Message):
    __slots__ = ('user_id', 'session_id', 'interval', 'limit')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    session_id: str
    interval: str
    limit: int

    def __init__(self, user_id: _Optional[str]=..., session_id: _Optional[str]=..., interval: _Optional[str]=..., limit: _Optional[int]=...) -> None:
        ...

class ActivityHeatmapRequest(_message.Message):
    __slots__ = ('user_id', 'days', 'timezone')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    DAYS_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    days: int
    timezone: str

    def __init__(self, user_id: _Optional[str]=..., days: _Optional[int]=..., timezone: _Optional[str]=...) -> None:
        ...

class ToolListRequest(_message.Message):
    __slots__ = ()

    def __init__(self) -> None:
        ...
