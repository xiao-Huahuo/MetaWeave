"""FastAPI 应用生命周期实现。

``agent_service_lifespan`` 依次加载配置、创建业务服务、启动后台调度器、加载模型
并启动 gRPC；关闭时按原顺序释放资源。运行时容器保存在 ``app.state``。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from agent_service.core.bootstrap.config_bootstrap import load_startup_config
from agent_service.core.bootstrap.grpc_bootstrap import GrpcRuntime
from agent_service.core.bootstrap.services_bootstrap import create_application_services
from agent_service.core.db.engine import create_database_engine
from agent_service.core.db.migration import upgrade_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def agent_service_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理当前 FastAPI app 独占的服务容器、后台任务和 gRPC 运行时。"""

    config = load_startup_config()
    database_engine = create_database_engine(config)
    upgrade_database(config=config, engine=database_engine)
    services = create_application_services(config, database_engine=database_engine)
    grpc_runtime = GrpcRuntime()
    app.state.services = services
    app.state.grpc_runtime = grpc_runtime
    try:
        services.mcp_client_service.start()
        import asyncio
        services.mcp_server_service.runtime.loop = asyncio.get_running_loop()
        from sqlmodel import Session, select
        from agent_service.models.user_settings import UserSettingsRecord
        with Session(database_engine) as db:
            mcp_users = [r.user_id for r in db.exec(select(UserSettingsRecord)).all() if r.mcp_settings]
        for user_id in mcp_users:
            server_config = services.settings_service.get_mcp_settings(user_id=user_id, role="server")["config"]
            await services.mcp_server_service.runtime.apply(user_id, server_config)
        services.start_background_services()
        logger.info("SettingsService 初始化完成")
        grpc_runtime.start(services)

        static_dir = getattr(app.state, "static_dir", None)
        if static_dir is not None:
            logger.info("前端静态文件已挂载 | path=%s", static_dir)
        else:
            logger.info("未找到前端静态文件,开发时请单独启动 editor Vite dev server (npm run dev:electron --prefix editor)")
        yield
    finally:
        logger.info("AgentService 正在关闭...")
        services.shutdown_background_services()
        grpc_runtime.stop()
        await services.mcp_server_service.runtime.shutdown()
        services.mcp_client_service.shutdown()
        app.state.services = None
        app.state.grpc_runtime = None
        logger.info("AgentService 已关闭")
