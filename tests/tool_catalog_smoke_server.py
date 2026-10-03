"""Agent 工具展示与 Debug 注册表的真实接口验收服务。

使用说明：python -X utf8 -m uvicorn tests.tool_catalog_smoke_server:app --port 18072。
复用隔离 SQLite、正式设置服务及 Agent 的注册表序列化，不启动模型或修改生产数据。
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from agent_service.agent_core.runtime.graph_runner import GraphRunnerMixin
from agent_service.api.rest.agent import router as agent_router
from agent_service.api.rest.deps import bind_application_services
from agent_service.api.rest.settings import router as settings_router
from agent_service.tools.tool_registry import ToolRegistry
from tests.knowledge_url_smoke_server import lifespan as knowledge_lifespan


class _CatalogAgent(GraphRunnerMixin):
    """复用正式 Agent 注册表读取方法；本验收不调用图执行或语言模型。"""

    def __init__(self) -> None:
        """保存实际内置工具注册表，供正式 /agent/tools 路由读取。"""

        self.tool_registry = ToolRegistry.with_builtin_tools()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """临时业务数据、服务和注册表归本测试应用所有，退出时由原生命周期回收。"""

    async with knowledge_lifespan(app):
        app.state.services.agent = _CatalogAgent()
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(agent_router, dependencies=[Depends(bind_application_services)])
app.include_router(settings_router, dependencies=[Depends(bind_application_services)])


@app.get("/knowledge/tool-catalog-smoke/fixture")
def fixture() -> dict:
    """返回实际测试用户及目录，供页面入口和测试结束后的清理使用。"""

    return app.state.fixture
