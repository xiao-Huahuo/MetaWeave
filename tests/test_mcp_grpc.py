"""Real local gRPC management uses the same persisted MCP settings/credential services as REST."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from agent_service.api.grpc import agent_service_pb2_grpc as protocol
from agent_service.api.grpc.handlers.mcp import McpGrpcHandlerMixin
from tests.mcp_test_support import make_mcp_services


def test_real_mcp_grpc_settings_and_credentials(tmp_path):
    """Verify DTO serialization and the worker-to-application-loop bridge over a real channel."""
    async def verify():
        services = make_mcp_services(tmp_path)
        client, server = services.mcp_client_service, services.mcp_server_service
        client.start()
        server.runtime.loop = asyncio.get_running_loop()
        class Handler(McpGrpcHandlerMixin, protocol.AgentServiceServicer):
            """Test protocol host with real MCP domain services, without unrelated Agent/model startup."""
            _mcp_client_service = client
            _mcp_server_service = server
        rpc_server = grpc.server(ThreadPoolExecutor(max_workers=1))
        protocol.add_AgentServiceServicer_to_server(Handler(), rpc_server)
        port = rpc_server.add_insecure_port("127.0.0.1:0")
        rpc_server.start()
        def call_requests():
            """Exercise generated stubs from a different thread while the listener owner loop runs."""
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = protocol.AgentServiceStub(channel)
                saved = MessageToDict(stub.SaveMcpClient(ParseDict({"user_id": "rpc-user", "enabled": True}, Struct()), timeout=10))
                assert saved["config"]["enabled"] is True
                status = MessageToDict(stub.SaveMcpServer(ParseDict({"user_id": "rpc-user", "config": {"enabled": False}}, Struct()), timeout=10))
                assert status["state"] == "stopped"
                profile = services.settings_service.ensure_user_profile(user_id="rpc-user")
                issued = MessageToDict(stub.CreateMcpCredential(ParseDict({"user_id": "rpc-user", "config": {
                    "name": "RPC reader", "library_id": profile["active_library_id"], "tools": ["read_file"],
                }}, Struct()), timeout=10))
                assert issued["token"].startswith("mw_mcp_")
                status = MessageToDict(stub.GetMcpServer(ParseDict({"user_id": "rpc-user"}, Struct()), timeout=10))
                assert issued["token"] not in str(status)
                stub.RevokeMcpCredential(ParseDict({"user_id": "rpc-user", "credential_id": issued["credential_id"]}, Struct()), timeout=10)
        try:
            await asyncio.to_thread(call_requests)
        finally:
            rpc_server.stop(0).wait(timeout=5)
            await server.runtime.shutdown()
            client.shutdown()
            services.database_engine.dispose()
    asyncio.run(verify())
