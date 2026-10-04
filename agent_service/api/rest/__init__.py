"""AgentService REST 接口层 — 按领域拆分路由模块。"""

from fastapi import APIRouter, Depends

from agent_service.api.rest.deps import bind_application_services

from agent_service.api.rest.health import router as health_router
from agent_service.api.rest.auth import router as auth_router
from agent_service.api.rest.sessions import router as sessions_router
from agent_service.api.rest.agent import router as agent_router
from agent_service.api.rest.debug import router as debug_router
from agent_service.api.rest.knowledge import router as knowledge_router
from agent_service.api.rest.unified_search import router as unified_search_router
from agent_service.api.rest.git import router as git_router
from agent_service.api.rest.library import router as library_router
from agent_service.api.rest.component_library import router as component_library_router
from agent_service.api.rest.vault import router as vault_router
from agent_service.api.rest.settings import router as settings_router
from agent_service.api.rest.skills import router as skills_router
from agent_service.api.rest.task_lists import router as task_lists_router
from agent_service.api.rest.token_usage import router as token_usage_router
from agent_service.api.rest.todo import router as todo_router
from agent_service.api.rest.automation import router as automation_router
from agent_service.api.rest.favorites import router as favorites_router
from agent_service.api.rest.scanner import router as scanner_router
from agent_service.api.rest.privacy import router as privacy_router
from agent_service.api.rest.feedback import router as feedback_router
from agent_service.api.rest.smart_forms import router as smart_forms_router
from agent_service.api.rest.structured_generation import router as structured_generation_router
from agent_service.api.rest.agent_changes import router as agent_changes_router
from agent_service.api.rest.agent_queue import router as agent_queue_router
from agent_service.api.rest.activity import router as activity_router

router = APIRouter(dependencies=[Depends(bind_application_services)])
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(sessions_router)
router.include_router(agent_router)
router.include_router(debug_router)
router.include_router(knowledge_router)
router.include_router(unified_search_router)
router.include_router(git_router)
router.include_router(library_router)
router.include_router(component_library_router)
router.include_router(vault_router)
from agent_service.api.rest.mcp import router as mcp_router
router.include_router(mcp_router)
router.include_router(settings_router)
router.include_router(skills_router)
router.include_router(task_lists_router)
router.include_router(token_usage_router)
router.include_router(todo_router)
router.include_router(automation_router)
router.include_router(favorites_router)
router.include_router(scanner_router)
router.include_router(privacy_router)
router.include_router(feedback_router)
router.include_router(smart_forms_router)
router.include_router(structured_generation_router)
router.include_router(agent_changes_router)
router.include_router(agent_queue_router)
router.include_router(activity_router)

__all__ = ["router"]
