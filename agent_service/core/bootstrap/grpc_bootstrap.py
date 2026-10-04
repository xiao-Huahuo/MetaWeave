"""管理 AgentService gRPC server 的创建、启动和关闭。

``GrpcRuntime`` 持有 gRPC server 与 servicer，保留原 Windows IPv6 wildcard
兼容和 HTTP 独立存活行为。lifespan 负责调用 ``start`` 与 ``stop``。
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import grpc

from agent_service.api.grpc.agent_service_pb2_grpc import add_AgentServiceServicer_to_server
from agent_service.api.grpc.servicer import AgentServiceServicer
from agent_service.core.bootstrap.services_bootstrap import ApplicationServices

logger = logging.getLogger(__name__)


class GrpcRuntime:
    """封装一个应用实例对应的 gRPC server、servicer 和运行状态。"""

    def __init__(self) -> None:
        """创建尚未启动的空运行时。"""

        self.server: grpc.Server | None = None
        self.servicer: AgentServiceServicer | None = None
        self.running = False

    def start(self, services: ApplicationServices) -> None:
        """使用应用服务容器构造 servicer 并启动 gRPC server。"""

        if services.auth_service is None:
            raise RuntimeError("AuthService is required before starting gRPC")
        self.servicer = AgentServiceServicer(
            agent=services.agent,
            session_service=services.session_service,
            message_service=services.message_service,
            settings_service=services.settings_service,
            knowledge_library_service=services.knowledge_library_service,
            knowledge_ingestion_job_service=services.knowledge_ingestion_job_service,
            git_service=services.git_service,
            favorite_service=services.favorite_service,
            privacy_service=services.privacy_service,
            feedback_service=services.feedback_service,
            vault_service=services.vault_service,
            auth_service=services.auth_service,
            agent_change_service=services.agent_change_service,
            agent_queue_service=services.agent_queue_service,
            automation_service=services.automation_service,
            activity_service=services.activity_service,
            component_library_service=services.component_library_service,
            unified_search_service=services.unified_search_service,
            smart_form_service=services.smart_form_service,
            latex_service=services.latex_service,
            model_management_service=services.model_management_service,
            attachment_service=services.attachment_service,
            mcp_client_service=services.mcp_client_service,
            mcp_server_service=services.mcp_server_service,
        )
        grpc_host = services.config.server.grpc_host
        if grpc_host == "[::]" and sys.platform == "win32":
            grpc_host = "0.0.0.0"
        grpc_address = f"{grpc_host}:{services.config.server.grpc_port}"
        try:
            self.server = grpc.server(
                ThreadPoolExecutor(max_workers=services.config.limits.grpc_max_workers)
            )
            add_AgentServiceServicer_to_server(self.servicer, self.server)
            self.server.add_insecure_port(grpc_address)
            self.server.start()
            self.running = True
            logger.info("gRPC server 已启动 | address=%s", grpc_address)
        except RuntimeError as exc:
            logger.warning("gRPC server 启动失败，HTTP 服务继续运行 | address=%s error=%s", grpc_address, exc)
            self.server = None
            self.running = False

    def stop(self) -> None:
        """停止 server，并关闭 servicer 持有的 AgentCore 资源。"""

        if self.server is not None:
            self.server.stop(0)
            logger.info("gRPC server 已停止")
        self.server = None
        self.running = False
        if self.servicer is not None:
            self.servicer.shutdown()
            logger.info("AgentCore 资源已释放")
        self.servicer = None
