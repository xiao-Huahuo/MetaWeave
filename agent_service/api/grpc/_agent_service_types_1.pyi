"""Generated from agent_service.proto; regenerate with scripts/generate_grpc.py."""
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union
DESCRIPTOR: _descriptor.FileDescriptor

from ._agent_service_types_0 import GitUserRequest, GitInitRequest, GitHistoryRequest, GitDiffRequest, GitPathsRequest, GitCommitRequest, GitPushRequest, GitBranchRequest, GitRemoteRequest, GitPullRequest, RunRequest, RunResult, ToolCall, TraceEntry, ChunkMessage, SessionCreateRequest, SessionIdRequest, ListSessionsRequest, SessionUpdateRequest, SessionResponse, ListSessionsResponse, DeleteResponse, DeleteAllSessionsRequest, FavoriteListRequest, FavoriteCreateRequest, FavoriteDeleteRequest, FavoriteEntryResponse, FavoriteListResponse, PrivacyListRequest, PrivacyCreateRequest, PrivacyDeleteRequest, PrivacyEntryResponse, PrivacyListResponse, FeedbackCreateRequest, FeedbackListRequest, FeedbackUpdateRequest, FeedbackDeleteRequest, FeedbackEntryResponse, FeedbackListResponse, ListMessagesRequest, MessageEntry, ListMessagesResponse, EventsRequest, EventEntry, EventsResponse, RecallDetailsRequest, RecallDetailsResponse, TaskSuggestionsRequest, TaskSuggestionsResponse, TokenUsageRequest, ActivityHeatmapRequest, ToolListRequest
from ._agent_service_types_2 import MemoryListResponse, MemoryAddRequest, MemoryDeleteRequest

class ToolInfo(_message.Message):
    __slots__ = ('name', 'display_name', 'description', 'args_schema', 'argument_count')
    NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ARGS_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    ARGUMENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    display_name: str
    description: str
    args_schema: _struct_pb2.Struct
    argument_count: int

    def __init__(self, name: _Optional[str]=..., display_name: _Optional[str]=..., description: _Optional[str]=..., args_schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=..., argument_count: _Optional[int]=...) -> None:
        ...

class ToolListResponse(_message.Message):
    __slots__ = ('tool_count', 'tools')
    TOOL_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOOLS_FIELD_NUMBER: _ClassVar[int]
    tool_count: int
    tools: _containers.RepeatedCompositeFieldContainer[ToolInfo]

    def __init__(self, tool_count: _Optional[int]=..., tools: _Optional[_Iterable[_Union[ToolInfo, _Mapping]]]=...) -> None:
        ...

class CancelRequest(_message.Message):
    __slots__ = ('session_id',)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str

    def __init__(self, session_id: _Optional[str]=...) -> None:
        ...

class CancelResponse(_message.Message):
    __slots__ = ('ok',)
    OK_FIELD_NUMBER: _ClassVar[int]
    ok: bool

    def __init__(self, ok: bool=...) -> None:
        ...

class ChildAgentListRequest(_message.Message):
    __slots__ = ('session_id',)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str

    def __init__(self, session_id: _Optional[str]=...) -> None:
        ...

class ChildAgentRecord(_message.Message):
    __slots__ = ('run_id', 'parent_run_id', 'goal', 'mode', 'status', 'access_mode', 'allowed_tools', 'summary', 'result_json', 'error', 'category', 'name')
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    GOAL_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ACCESS_MODE_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_TOOLS_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    parent_run_id: str
    goal: str
    mode: str
    status: str
    access_mode: str
    allowed_tools: _containers.RepeatedScalarFieldContainer[str]
    summary: str
    result_json: str
    error: str
    category: str
    name: str

    def __init__(self, run_id: _Optional[str]=..., parent_run_id: _Optional[str]=..., goal: _Optional[str]=..., mode: _Optional[str]=..., status: _Optional[str]=..., access_mode: _Optional[str]=..., allowed_tools: _Optional[_Iterable[str]]=..., summary: _Optional[str]=..., result_json: _Optional[str]=..., error: _Optional[str]=..., category: _Optional[str]=..., name: _Optional[str]=...) -> None:
        ...

class ChildAgentListResponse(_message.Message):
    __slots__ = ('session_id', 'children')
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    children: _containers.RepeatedCompositeFieldContainer[ChildAgentRecord]

    def __init__(self, session_id: _Optional[str]=..., children: _Optional[_Iterable[_Union[ChildAgentRecord, _Mapping]]]=...) -> None:
        ...

class ChildAgentControlRequest(_message.Message):
    __slots__ = ('run_id',)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str

    def __init__(self, run_id: _Optional[str]=...) -> None:
        ...

class ChildAgentUpdateRequest(_message.Message):
    __slots__ = ('run_id', 'update')
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    update: _struct_pb2.Struct

    def __init__(self, run_id: _Optional[str]=..., update: _Optional[_Union[_struct_pb2.Struct, _Mapping]]=...) -> None:
        ...

class ChildAgentControlResponse(_message.Message):
    __slots__ = ('ok', 'run_id')
    OK_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    run_id: str

    def __init__(self, ok: bool=..., run_id: _Optional[str]=...) -> None:
        ...

class UserProfileRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class UserKnowledgeDirUpdateRequest(_message.Message):
    __slots__ = ('user_id', 'knowledge_dir', 'name')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_DIR_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    knowledge_dir: str
    name: str

    def __init__(self, user_id: _Optional[str]=..., knowledge_dir: _Optional[str]=..., name: _Optional[str]=...) -> None:
        ...

class UserProfileResponse(_message.Message):
    __slots__ = ('user_id', 'knowledge_dir', 'created_at', 'updated_at', 'active_library_id', 'active_knowledge_library', 'knowledge_libraries', 'ocr_enabled', 'vision_understanding_enabled', 'auto_ingest_on_upload', 'vlm_enabled', 'theme_mode', 'safety_enabled', 'sensitive_words_enabled')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_DIR_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_KNOWLEDGE_LIBRARY_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_LIBRARIES_FIELD_NUMBER: _ClassVar[int]
    OCR_ENABLED_FIELD_NUMBER: _ClassVar[int]
    VISION_UNDERSTANDING_ENABLED_FIELD_NUMBER: _ClassVar[int]
    AUTO_INGEST_ON_UPLOAD_FIELD_NUMBER: _ClassVar[int]
    VLM_ENABLED_FIELD_NUMBER: _ClassVar[int]
    THEME_MODE_FIELD_NUMBER: _ClassVar[int]
    SAFETY_ENABLED_FIELD_NUMBER: _ClassVar[int]
    SENSITIVE_WORDS_ENABLED_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    knowledge_dir: str
    created_at: str
    updated_at: str
    active_library_id: str
    active_knowledge_library: KnowledgeLibraryEntry
    knowledge_libraries: _containers.RepeatedCompositeFieldContainer[KnowledgeLibraryEntry]
    ocr_enabled: bool
    vision_understanding_enabled: bool
    auto_ingest_on_upload: bool
    vlm_enabled: bool
    theme_mode: str
    safety_enabled: bool
    sensitive_words_enabled: bool

    def __init__(self, user_id: _Optional[str]=..., knowledge_dir: _Optional[str]=..., created_at: _Optional[str]=..., updated_at: _Optional[str]=..., active_library_id: _Optional[str]=..., active_knowledge_library: _Optional[_Union[KnowledgeLibraryEntry, _Mapping]]=..., knowledge_libraries: _Optional[_Iterable[_Union[KnowledgeLibraryEntry, _Mapping]]]=..., ocr_enabled: bool=..., vision_understanding_enabled: bool=..., auto_ingest_on_upload: bool=..., vlm_enabled: bool=..., theme_mode: _Optional[str]=..., safety_enabled: bool=..., sensitive_words_enabled: bool=...) -> None:
        ...

class AttachmentRawRequest(_message.Message):
    __slots__ = ('uri',)
    URI_FIELD_NUMBER: _ClassVar[int]
    uri: str

    def __init__(self, uri: _Optional[str]=...) -> None:
        ...

class AttachmentRawResponse(_message.Message):
    __slots__ = ('content', 'mime_type', 'filename')
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    mime_type: str
    filename: str

    def __init__(self, content: _Optional[bytes]=..., mime_type: _Optional[str]=..., filename: _Optional[str]=...) -> None:
        ...

class LLMConfigRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class LLMConfigSaveRequest(_message.Message):
    __slots__ = ('user_id', 'api_key', 'base_url', 'model_name', 'small_api_key', 'small_base_url', 'small_model_name', 'model_context_window_tokens', 'model_max_output_tokens', 'small_model_context_window_tokens', 'small_model_max_output_tokens', 'vision_api_key', 'vision_base_url', 'vision_model_name')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    SMALL_API_KEY_FIELD_NUMBER: _ClassVar[int]
    SMALL_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_CONTEXT_WINDOW_TOKENS_FIELD_NUMBER: _ClassVar[int]
    MODEL_MAX_OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_CONTEXT_WINDOW_TOKENS_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_MAX_OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    VISION_API_KEY_FIELD_NUMBER: _ClassVar[int]
    VISION_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    VISION_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    api_key: str
    base_url: str
    model_name: str
    small_api_key: str
    small_base_url: str
    small_model_name: str
    model_context_window_tokens: int
    model_max_output_tokens: int
    small_model_context_window_tokens: int
    small_model_max_output_tokens: int
    vision_api_key: str
    vision_base_url: str
    vision_model_name: str

    def __init__(self, user_id: _Optional[str]=..., api_key: _Optional[str]=..., base_url: _Optional[str]=..., model_name: _Optional[str]=..., small_api_key: _Optional[str]=..., small_base_url: _Optional[str]=..., small_model_name: _Optional[str]=..., model_context_window_tokens: _Optional[int]=..., model_max_output_tokens: _Optional[int]=..., small_model_context_window_tokens: _Optional[int]=..., small_model_max_output_tokens: _Optional[int]=..., vision_api_key: _Optional[str]=..., vision_base_url: _Optional[str]=..., vision_model_name: _Optional[str]=...) -> None:
        ...

class LLMConfigResponse(_message.Message):
    __slots__ = ('user_id', 'api_key', 'base_url', 'model_name', 'small_api_key', 'small_base_url', 'small_model_name', 'effective_small_api_key', 'effective_small_base_url', 'effective_small_model_name', 'updated_at', 'effective_api_key', 'effective_base_url', 'effective_model_name', 'effective_model_source', 'effective_small_model_source', 'model_context_window_tokens', 'model_max_output_tokens', 'small_model_context_window_tokens', 'small_model_max_output_tokens', 'vision_api_key', 'vision_base_url', 'vision_model_name', 'effective_vision_api_key', 'effective_vision_base_url', 'effective_vision_model_name', 'effective_vision_model_source')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    SMALL_API_KEY_FIELD_NUMBER: _ClassVar[int]
    SMALL_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_SMALL_API_KEY_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_SMALL_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_SMALL_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_API_KEY_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_MODEL_SOURCE_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_SMALL_MODEL_SOURCE_FIELD_NUMBER: _ClassVar[int]
    MODEL_CONTEXT_WINDOW_TOKENS_FIELD_NUMBER: _ClassVar[int]
    MODEL_MAX_OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_CONTEXT_WINDOW_TOKENS_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_MAX_OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    VISION_API_KEY_FIELD_NUMBER: _ClassVar[int]
    VISION_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    VISION_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_VISION_API_KEY_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_VISION_BASE_URL_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_VISION_MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_VISION_MODEL_SOURCE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    api_key: str
    base_url: str
    model_name: str
    small_api_key: str
    small_base_url: str
    small_model_name: str
    effective_small_api_key: str
    effective_small_base_url: str
    effective_small_model_name: str
    updated_at: str
    effective_api_key: str
    effective_base_url: str
    effective_model_name: str
    effective_model_source: str
    effective_small_model_source: str
    model_context_window_tokens: int
    model_max_output_tokens: int
    small_model_context_window_tokens: int
    small_model_max_output_tokens: int
    vision_api_key: str
    vision_base_url: str
    vision_model_name: str
    effective_vision_api_key: str
    effective_vision_base_url: str
    effective_vision_model_name: str
    effective_vision_model_source: str

    def __init__(self, user_id: _Optional[str]=..., api_key: _Optional[str]=..., base_url: _Optional[str]=..., model_name: _Optional[str]=..., small_api_key: _Optional[str]=..., small_base_url: _Optional[str]=..., small_model_name: _Optional[str]=..., effective_small_api_key: _Optional[str]=..., effective_small_base_url: _Optional[str]=..., effective_small_model_name: _Optional[str]=..., updated_at: _Optional[str]=..., effective_api_key: _Optional[str]=..., effective_base_url: _Optional[str]=..., effective_model_name: _Optional[str]=..., effective_model_source: _Optional[str]=..., effective_small_model_source: _Optional[str]=..., model_context_window_tokens: _Optional[int]=..., model_max_output_tokens: _Optional[int]=..., small_model_context_window_tokens: _Optional[int]=..., small_model_max_output_tokens: _Optional[int]=..., vision_api_key: _Optional[str]=..., vision_base_url: _Optional[str]=..., vision_model_name: _Optional[str]=..., effective_vision_api_key: _Optional[str]=..., effective_vision_base_url: _Optional[str]=..., effective_vision_model_name: _Optional[str]=..., effective_vision_model_source: _Optional[str]=...) -> None:
        ...

class LLMConfigPresetSaveRequest(_message.Message):
    __slots__ = ('user_id', 'label', 'api_key', 'base_url', 'model_name')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    label: str
    api_key: str
    base_url: str
    model_name: str

    def __init__(self, user_id: _Optional[str]=..., label: _Optional[str]=..., api_key: _Optional[str]=..., base_url: _Optional[str]=..., model_name: _Optional[str]=...) -> None:
        ...

class LLMConfigPresetDeleteRequest(_message.Message):
    __slots__ = ('config_id',)
    CONFIG_ID_FIELD_NUMBER: _ClassVar[int]
    config_id: str

    def __init__(self, config_id: _Optional[str]=...) -> None:
        ...

class LLMConfigPresetResponse(_message.Message):
    __slots__ = ('config_id', 'user_id', 'label', 'api_key', 'base_url', 'model_name', 'created_at', 'updated_at')
    CONFIG_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    config_id: str
    user_id: str
    label: str
    api_key: str
    base_url: str
    model_name: str
    created_at: str
    updated_at: str

    def __init__(self, config_id: _Optional[str]=..., user_id: _Optional[str]=..., label: _Optional[str]=..., api_key: _Optional[str]=..., base_url: _Optional[str]=..., model_name: _Optional[str]=..., created_at: _Optional[str]=..., updated_at: _Optional[str]=...) -> None:
        ...

class LLMConfigPresetListResponse(_message.Message):
    __slots__ = ('configs',)
    CONFIGS_FIELD_NUMBER: _ClassVar[int]
    configs: _containers.RepeatedCompositeFieldContainer[LLMConfigPresetResponse]

    def __init__(self, configs: _Optional[_Iterable[_Union[LLMConfigPresetResponse, _Mapping]]]=...) -> None:
        ...

class KnowledgeLibraryEntry(_message.Message):
    __slots__ = ('library_id', 'user_id', 'name', 'knowledge_dir', 'is_active', 'created_at', 'updated_at')
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_DIR_FIELD_NUMBER: _ClassVar[int]
    IS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    library_id: str
    user_id: str
    name: str
    knowledge_dir: str
    is_active: bool
    created_at: str
    updated_at: str

    def __init__(self, library_id: _Optional[str]=..., user_id: _Optional[str]=..., name: _Optional[str]=..., knowledge_dir: _Optional[str]=..., is_active: bool=..., created_at: _Optional[str]=..., updated_at: _Optional[str]=...) -> None:
        ...

class KnowledgeRebuildRequest(_message.Message):
    __slots__ = ('user_id', 'knowledge_dir')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_DIR_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    knowledge_dir: str

    def __init__(self, user_id: _Optional[str]=..., knowledge_dir: _Optional[str]=...) -> None:
        ...

class KnowledgeFileUploadRequest(_message.Message):
    __slots__ = ('user_id', 'filename', 'relative_dir', 'content')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    RELATIVE_DIR_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    filename: str
    relative_dir: str
    content: bytes

    def __init__(self, user_id: _Optional[str]=..., filename: _Optional[str]=..., relative_dir: _Optional[str]=..., content: _Optional[bytes]=...) -> None:
        ...

class KnowledgeRebuildResponse(_message.Message):
    __slots__ = ('user_id', 'knowledge_dir', 'frontmatter_dir', 'frontmatter_files_seen', 'frontmatter_files_written', 'frontmatter_files_skipped', 'files_seen', 'files_ingested', 'files_skipped', 'chunks_created', 'chunks_deleted', 'uploaded_path', 'library_id')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_DIR_FIELD_NUMBER: _ClassVar[int]
    FRONTMATTER_DIR_FIELD_NUMBER: _ClassVar[int]
    FRONTMATTER_FILES_SEEN_FIELD_NUMBER: _ClassVar[int]
    FRONTMATTER_FILES_WRITTEN_FIELD_NUMBER: _ClassVar[int]
    FRONTMATTER_FILES_SKIPPED_FIELD_NUMBER: _ClassVar[int]
    FILES_SEEN_FIELD_NUMBER: _ClassVar[int]
    FILES_INGESTED_FIELD_NUMBER: _ClassVar[int]
    FILES_SKIPPED_FIELD_NUMBER: _ClassVar[int]
    CHUNKS_CREATED_FIELD_NUMBER: _ClassVar[int]
    CHUNKS_DELETED_FIELD_NUMBER: _ClassVar[int]
    UPLOADED_PATH_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    knowledge_dir: str
    frontmatter_dir: str
    frontmatter_files_seen: int
    frontmatter_files_written: int
    frontmatter_files_skipped: int
    files_seen: int
    files_ingested: int
    files_skipped: int
    chunks_created: int
    chunks_deleted: int
    uploaded_path: str
    library_id: str

    def __init__(self, user_id: _Optional[str]=..., knowledge_dir: _Optional[str]=..., frontmatter_dir: _Optional[str]=..., frontmatter_files_seen: _Optional[int]=..., frontmatter_files_written: _Optional[int]=..., frontmatter_files_skipped: _Optional[int]=..., files_seen: _Optional[int]=..., files_ingested: _Optional[int]=..., files_skipped: _Optional[int]=..., chunks_created: _Optional[int]=..., chunks_deleted: _Optional[int]=..., uploaded_path: _Optional[str]=..., library_id: _Optional[str]=...) -> None:
        ...

class KnowledgeFileTreeRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class KnowledgeFileNode(_message.Message):
    __slots__ = ('name', 'path', 'is_dir', 'mtime', 'index_status', 'size', 'children', 'graph_status', 'created_at')
    NAME_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    IS_DIR_FIELD_NUMBER: _ClassVar[int]
    MTIME_FIELD_NUMBER: _ClassVar[int]
    INDEX_STATUS_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_FIELD_NUMBER: _ClassVar[int]
    GRAPH_STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    name: str
    path: str
    is_dir: bool
    mtime: str
    index_status: str
    size: int
    children: _containers.RepeatedCompositeFieldContainer[KnowledgeFileNode]
    graph_status: str
    created_at: str

    def __init__(self, name: _Optional[str]=..., path: _Optional[str]=..., is_dir: bool=..., mtime: _Optional[str]=..., index_status: _Optional[str]=..., size: _Optional[int]=..., children: _Optional[_Iterable[_Union[KnowledgeFileNode, _Mapping]]]=..., graph_status: _Optional[str]=..., created_at: _Optional[str]=...) -> None:
        ...

class KnowledgeFileTreeResponse(_message.Message):
    __slots__ = ('tree',)
    TREE_FIELD_NUMBER: _ClassVar[int]
    tree: _containers.RepeatedCompositeFieldContainer[KnowledgeFileNode]

    def __init__(self, tree: _Optional[_Iterable[_Union[KnowledgeFileNode, _Mapping]]]=...) -> None:
        ...

class KnowledgeFileContentRequest(_message.Message):
    __slots__ = ('user_id', 'path')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=...) -> None:
        ...

class KnowledgeFileContentResponse(_message.Message):
    __slots__ = ('path', 'content', 'mtime', 'size')
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MTIME_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    path: str
    content: str
    mtime: str
    size: int

    def __init__(self, path: _Optional[str]=..., content: _Optional[str]=..., mtime: _Optional[str]=..., size: _Optional[int]=...) -> None:
        ...

class KnowledgePdfPageRequest(_message.Message):
    __slots__ = ('user_id', 'path', 'page')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str
    page: int

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=..., page: _Optional[int]=...) -> None:
        ...

class KnowledgePdfPageResponse(_message.Message):
    __slots__ = ('content', 'mime_type')
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    mime_type: str

    def __init__(self, content: _Optional[bytes]=..., mime_type: _Optional[str]=...) -> None:
        ...

class KnowledgeFileWriteRequest(_message.Message):
    __slots__ = ('user_id', 'path', 'content')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str
    content: str

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=..., content: _Optional[str]=...) -> None:
        ...

class KnowledgeFileCreateRequest(_message.Message):
    __slots__ = ('user_id', 'path', 'content')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str
    content: str

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=..., content: _Optional[str]=...) -> None:
        ...

class KnowledgeFolderCreateRequest(_message.Message):
    __slots__ = ('user_id', 'path')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=...) -> None:
        ...

class KnowledgePathCopyRequest(_message.Message):
    __slots__ = ('user_id', 'source_path', 'target_path')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    TARGET_PATH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    source_path: str
    target_path: str

    def __init__(self, user_id: _Optional[str]=..., source_path: _Optional[str]=..., target_path: _Optional[str]=...) -> None:
        ...

class KnowledgePathDeleteRequest(_message.Message):
    __slots__ = ('user_id', 'path')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    path: str

    def __init__(self, user_id: _Optional[str]=..., path: _Optional[str]=...) -> None:
        ...

class KnowledgePathRenameRequest(_message.Message):
    __slots__ = ('user_id', 'source_path', 'target_path')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    TARGET_PATH_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    source_path: str
    target_path: str

    def __init__(self, user_id: _Optional[str]=..., source_path: _Optional[str]=..., target_path: _Optional[str]=...) -> None:
        ...

class SystemPromptRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class SystemPromptEntryResponse(_message.Message):
    __slots__ = ('prompt_id', 'content', 'created_at')
    PROMPT_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    prompt_id: str
    content: str
    created_at: str

    def __init__(self, prompt_id: _Optional[str]=..., content: _Optional[str]=..., created_at: _Optional[str]=...) -> None:
        ...

class SystemPromptEntriesResponse(_message.Message):
    __slots__ = ('entries',)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[SystemPromptEntryResponse]

    def __init__(self, entries: _Optional[_Iterable[_Union[SystemPromptEntryResponse, _Mapping]]]=...) -> None:
        ...

class SystemPromptAddRequest(_message.Message):
    __slots__ = ('user_id', 'content')
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    content: str

    def __init__(self, user_id: _Optional[str]=..., content: _Optional[str]=...) -> None:
        ...

class SystemPromptDeleteRequest(_message.Message):
    __slots__ = ('prompt_id',)
    PROMPT_ID_FIELD_NUMBER: _ClassVar[int]
    prompt_id: str

    def __init__(self, prompt_id: _Optional[str]=...) -> None:
        ...

class MemoryListRequest(_message.Message):
    __slots__ = ('user_id',)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str

    def __init__(self, user_id: _Optional[str]=...) -> None:
        ...

class MemoryEntryResponse(_message.Message):
    __slots__ = ('memory_id', 'content', 'importance', 'created_at')
    MEMORY_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IMPORTANCE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    memory_id: str
    content: str
    importance: float
    created_at: str

    def __init__(self, memory_id: _Optional[str]=..., content: _Optional[str]=..., importance: _Optional[float]=..., created_at: _Optional[str]=...) -> None:
        ...
