"""
数据库模型导出模块。

功能说明:
本文件集中导出数据库模型,方便业务层和初始化脚本统一导入。初始化数据库前
导入本模块可以确保 SQLModel metadata 已注册全部表模型。
向量列由 ChromaDB 独立管理,不直接声明在 SQLModel 中。
"""

from agent_service.models.longterm_memory_spec import LongTermMemorySpec, LongTermMemorySpecBase
from agent_service.models.attachment import SessionAttachmentRecord
from agent_service.models.agent_change import AgentChangeSnapshotRecord
from agent_service.models.agent_queue import AgentQueueSettingsRecord, AgentQueueTaskRecord
from agent_service.models.activity import ActivityEventRecord
from agent_service.models.automation import AutomationRunRecord, AutomationTaskRecord
from agent_service.models.component_library import ComponentLibraryMetadata
from agent_service.models.favorite import FavoriteRecord
from agent_service.models.privacy import PrivacyRecord
from agent_service.models.feedback import FeedbackRecord
from agent_service.models.knowledge_ingestion_job import KnowledgeIngestionJobRecord
from agent_service.models.scanner import ScannerRecord
from agent_service.models.knowledge_graph import KnowledgeGraphDedupDecision, KnowledgeGraphDocumentStatus, KnowledgeGraphEdge, KnowledgeGraphNode, KnowledgeGraphSectionCache
from agent_service.models.library import LibraryAsset, LibraryItem, LibraryItemTag, LibraryTag
from agent_service.models.message import MessageBase, MessageRecord
from agent_service.models.session import SessionBase, SessionRecord
from agent_service.models.smart_form import LiteratureReadingStateRecord, SmartFormCellRecord, SmartFormColumnRecord, SmartFormRecord, SmartFormRowRecord
from agent_service.models.token_usage import TokenUsageRecord
from agent_service.models.todo import TodoImportRecord, TodoRecord
from agent_service.models.user_settings import (
    UserKnowledgeLibrary,
    UserLLMConfig,
    UserLLMConfigPreset,
    UserSettingsRecord,
    UserSystemPromptEntry,
    UserVlmConfigPreset,
)
from agent_service.models.vault import VaultAsset, VaultItem, VaultItemTag, VaultProfile, VaultTag

__all__ = [
    "LongTermMemorySpec",
    "LongTermMemorySpecBase",
    "SessionAttachmentRecord",
    "AgentChangeSnapshotRecord",
    "AgentQueueSettingsRecord",
    "AgentQueueTaskRecord",
    "ActivityEventRecord",
    "AutomationRunRecord",
    "AutomationTaskRecord",
    "ComponentLibraryMetadata",
    "FavoriteRecord",
    "PrivacyRecord",
    "FeedbackRecord",
    "KnowledgeIngestionJobRecord",
    "KnowledgeGraphDocumentStatus",
    "KnowledgeGraphDedupDecision",
    "KnowledgeGraphEdge",
    "KnowledgeGraphNode",
    "KnowledgeGraphSectionCache",
    "LibraryAsset",
    "LibraryItem",
    "LibraryItemTag",
    "LibraryTag",
    "MessageBase",
    "MessageRecord",
    "SessionBase",
    "SessionRecord",
    "SmartFormCellRecord",
    "SmartFormColumnRecord",
    "SmartFormRecord",
    "SmartFormRowRecord",
    "TokenUsageRecord",
    "TodoImportRecord",
    "TodoRecord",
    "UserKnowledgeLibrary",
    "UserLLMConfig",
    "UserLLMConfigPreset",
    "UserSettingsRecord",
    "UserSystemPromptEntry",
    "UserVlmConfigPreset",
    "VaultAsset",
    "VaultItem",
    "VaultItemTag",
    "VaultProfile",
    "VaultTag",
]
