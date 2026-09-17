"""创建并连接 AgentService 的全部运行时业务服务。

``create_application_services`` 是唯一应用级装配入口。返回的
``ApplicationServices`` 保存运行时对象和后台调度器，供 REST Depends、gRPC 和
lifespan 共用；它不会写入 ``AgentConfig`` 或模块级 Service 全局变量。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from agent_service.agent_core import AgentCore
from agent_service.core.agent_config import AgentConfig
from agent_service.core.bootstrap.models_bootstrap import create_model_services
from agent_service.services.activity.service import ActivityService
from agent_service.services.agent_change.service import AgentChangeService
from agent_service.services.agent_queue.scheduler import AgentQueueScheduler
from agent_service.services.agent_queue.service import AgentQueueService
from agent_service.services.automation.scheduler import AutomationScheduler
from agent_service.services.automation.service import AutomationService
from agent_service.services.component_library.service import ComponentLibraryService
from agent_service.services.dsh_runtime import DshRuntimePackageManager
from agent_service.services.dsh_adapter import DshChildAgentExecutor
from agent_service.services.favorite.service import FavoriteService
from agent_service.services.feedback.service import FeedbackService
from agent_service.services.git.service import GitService
from agent_service.services.knowledge_graph import KnowledgeGraphQueueService, KnowledgeGraphService
from agent_service.services.knowledge_ingestion_job.service import KnowledgeIngestionJobService
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.latex.service import LatexService
from agent_service.services.library.service import LibraryService
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.memory.retrieval_service import MemoryRetrievalService
from agent_service.services.message.service import MessageService
from agent_service.services.model_management.service import ModelManagementService
from agent_service.services.privacy.service import PrivacyService
from agent_service.services.scanner import ScannerService
from agent_service.services.session_attachment.service import SessionAttachmentService
from agent_service.services.session.service import SessionService
from agent_service.services.settings.service import SettingsService
from agent_service.services.skill.service import SkillService
from agent_service.services.smart_form.service import SmartFormService
from agent_service.services.structured_generation.service import StructuredGenerationService
from agent_service.services.task_list.service import TaskListService
from agent_service.services.todo.service import TodoService
from agent_service.services.unified_search import UnifiedSearchService
from agent_service.services.vault.service import VaultService
from agent_service.services.vision.service import VisionModelService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationServices:
    """保存一个 FastAPI 应用实例拥有的全部运行时服务。

    字段按原 ``main.py`` 的依赖装配结果命名，REST 依赖函数可以用同一名称直接
    取值。``shutdown_background_services`` 按原关闭顺序清理后台组件。
    """

    config: AgentConfig
    agent: AgentCore
    session_service: SessionService
    message_service: MessageService
    settings_service: SettingsService
    model_management_service: ModelManagementService
    dsh_runtime_manager: DshRuntimePackageManager
    dsh_executor: DshChildAgentExecutor
    attachment_service: SessionAttachmentService
    skill_service: SkillService
    knowledge_library_service: KnowledgeLibraryService
    latex_service: LatexService
    knowledge_ingestion_job_service: KnowledgeIngestionJobService
    knowledge_graph_service: KnowledgeGraphService
    knowledge_graph_queue_service: KnowledgeGraphQueueService
    git_service: GitService
    library_service: LibraryService
    component_library_service: ComponentLibraryService
    unified_search_service: UnifiedSearchService
    vault_service: VaultService
    favorite_service: FavoriteService
    scanner_service: ScannerService
    privacy_service: PrivacyService
    feedback_service: FeedbackService
    activity_service: ActivityService
    smart_form_service: SmartFormService
    structured_generation_service: StructuredGenerationService
    agent_change_service: AgentChangeService
    task_list_service: TaskListService
    retrieval_service: MemoryRetrievalService
    todo_service: TodoService
    automation_service: AutomationService
    agent_queue_service: AgentQueueService
    memory_service: LongTermMemoryService
    automation_scheduler: AutomationScheduler
    agent_queue_scheduler: AgentQueueScheduler
    vision_service: VisionModelService
    database_engine: Engine

    def start_background_services(self) -> None:
        """按原启动顺序启动 Agent 队列和自动化调度器。"""

        self.agent_queue_scheduler.start()
        self.automation_scheduler.start()

    def shutdown_background_services(self) -> None:
        """按原关闭顺序停止自动化、入库任务和 Agent 队列。"""

        self.automation_scheduler.shutdown()
        self.knowledge_ingestion_job_service.stop()
        self.scanner_service.stop()
        self.knowledge_graph_queue_service.stop()
        self.agent_queue_scheduler.shutdown()
        self.dsh_executor.shutdown()
        self.dsh_runtime_manager.shutdown()


def create_application_services(config: AgentConfig, *, database_engine: Engine) -> ApplicationServices:
    """创建全部业务服务、连接既有依赖并返回应用级容器。"""

    message_service = MessageService(config=config, engine=database_engine, create_tables=False)
    session_service = SessionService(config=config, engine=database_engine, create_tables=False)
    task_list_service = TaskListService(session_service=session_service)
    memory_service = LongTermMemoryService(config=config, engine=database_engine, create_tables=False)
    settings_service = SettingsService(config=config, memory_service=memory_service)
    model_management_service = create_model_services(
        config=config,
        settings_service=settings_service,
    )
    vision_service = VisionModelService(config=config, settings_service=settings_service)
    dsh_runtime_manager = DshRuntimePackageManager(config=config)
    activity_service = ActivityService(engine=database_engine, config=config, create_tables=False)
    knowledge_graph_service = KnowledgeGraphService(config=config, engine=database_engine, create_tables=False)
    knowledge_library_service = KnowledgeLibraryService(
        config=config,
        memory_service=memory_service,
        settings_service=settings_service,
        knowledge_graph_service=knowledge_graph_service,
    )
    agent_change_service = AgentChangeService(
        config=config,
        knowledge_library_service=knowledge_library_service,
        engine=database_engine,
        create_tables=False,
    )
    agent = AgentCore(
        config=config,
        message_service=message_service,
        session_service=session_service,
        task_list_service=task_list_service,
        change_service=agent_change_service,
        settings_service=settings_service,
    )
    logger.info("AgentCore 初始化完成 | graph_diagram=%s", agent.graph_diagram_path)
    skill_service = SkillService(config=config, settings_service=settings_service)
    agent.skill_service = skill_service
    agent.activity_service = activity_service
    attachment_service = SessionAttachmentService(
        config=config,
        settings_service=settings_service,
    )
    agent.attachment_service = attachment_service
    agent.attachment_runtime.bind(service=attachment_service, context_builder=agent.context_builder)

    git_service = GitService(knowledge_library_service=knowledge_library_service, config=config)
    library_service = LibraryService(
        config=config,
        settings_service=settings_service,
        knowledge_library_service=knowledge_library_service,
        knowledge_graph_service=knowledge_graph_service,
    )
    latex_service = LatexService(
        config=config,
        settings_service=settings_service,
        knowledge_library_service=knowledge_library_service,
    )
    knowledge_ingestion_job_service = KnowledgeIngestionJobService(
        engine=memory_service.engine,
        config=config,
        knowledge_library_service=knowledge_library_service,
    )
    knowledge_graph_queue_service = KnowledgeGraphQueueService(
        max_concurrency=config.limits.knowledge_graph_queue_worker_count,
    )
    component_library_service = ComponentLibraryService(
        settings_service=settings_service,
        legacy_engine=settings_service.engine,
    )
    vault_service = VaultService(config=config, engine=settings_service.engine)
    favorite_service = FavoriteService(engine=database_engine, create_tables=False)
    scanner_service = ScannerService(
        engine=database_engine,
        config=config,
        settings_service=settings_service,
        knowledge_library_service=knowledge_library_service,
    )
    privacy_service = PrivacyService(engine=database_engine, create_tables=False)
    feedback_service = FeedbackService(engine=database_engine, create_tables=False)
    smart_form_service = SmartFormService(engine=database_engine, create_tables=False)
    structured_generation_service = StructuredGenerationService(
        config=config,
        settings_service=settings_service,
    )
    dsh_executor = DshChildAgentExecutor(
        config=config,
        settings_service=settings_service,
        runtime_manager=dsh_runtime_manager,
    )
    agent.dsh_executor = dsh_executor
    retrieval_service = MemoryRetrievalService(config=config, memory_service=memory_service)
    unified_search_service = UnifiedSearchService(
        settings_service=settings_service,
        knowledge_library_service=knowledge_library_service,
        library_service=library_service,
        component_library_service=component_library_service,
        smart_form_service=smart_form_service,
        retrieval_service=retrieval_service,
    )
    agent.unified_search_service = unified_search_service
    todo_service = TodoService(
        engine=memory_service.engine,
        config=config,
        legacy_data_dir=str(config.storage.base_data_dir),
    )
    automation_service = AutomationService(
        engine=memory_service.engine,
        todo_service=todo_service,
        config=config,
    )
    agent_queue_service = AgentQueueService(
        engine=memory_service.engine,
        session_service=session_service,
        config=config,
    )
    agent_queue_scheduler = AgentQueueScheduler(queue_service=agent_queue_service, agent=agent)
    automation_scheduler = AutomationScheduler(
        automation_service=automation_service,
        agent=agent,
        session_service=session_service,
    )
    agent.tool_services = {
        "knowledge_library": knowledge_library_service,
        "knowledge_graph": knowledge_graph_service,
        "git": git_service,
        "library": library_service,
        "skill": skill_service,
        "feedback": feedback_service,
        "component_library": component_library_service,
        "favorite": favorite_service,
        "smart_form": smart_form_service,
        "structured_generation": structured_generation_service,
        "vision": vision_service,
        "session_attachment": attachment_service,
    }
    return ApplicationServices(
        config=config,
        agent=agent,
        session_service=session_service,
        message_service=message_service,
        settings_service=settings_service,
        model_management_service=model_management_service,
        dsh_runtime_manager=dsh_runtime_manager,
        dsh_executor=dsh_executor,
        attachment_service=attachment_service,
        skill_service=skill_service,
        knowledge_library_service=knowledge_library_service,
        latex_service=latex_service,
        knowledge_ingestion_job_service=knowledge_ingestion_job_service,
        knowledge_graph_service=knowledge_graph_service,
        knowledge_graph_queue_service=knowledge_graph_queue_service,
        git_service=git_service,
        library_service=library_service,
        component_library_service=component_library_service,
        unified_search_service=unified_search_service,
        vault_service=vault_service,
        favorite_service=favorite_service,
        scanner_service=scanner_service,
        privacy_service=privacy_service,
        feedback_service=feedback_service,
        activity_service=activity_service,
        smart_form_service=smart_form_service,
        structured_generation_service=structured_generation_service,
        agent_change_service=agent_change_service,
        task_list_service=task_list_service,
        retrieval_service=retrieval_service,
        todo_service=todo_service,
        automation_service=automation_service,
        agent_queue_service=agent_queue_service,
        memory_service=memory_service,
        automation_scheduler=automation_scheduler,
        agent_queue_scheduler=agent_queue_scheduler,
        vision_service=vision_service,
        database_engine=database_engine,
    )
