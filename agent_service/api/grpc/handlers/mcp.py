"""MCP management gRPC adapters; share the same validated services and secret-free DTOs as REST."""
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct


class McpGrpcHandlerMixin:
    """Adapt named management RPCs to application-owned MCP services."""

    def _mcp_result(self, context, function, *arguments):
        """Map errors without exposing secrets or raw SDK exceptions."""
        peer = context.peer()
        if not (peer.startswith("ipv4:127.0.0.1:") or peer.startswith("ipv6:[::1]:")):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "MCP management is local-only")
        try:
            result = function(*arguments)
            if result is None:
                result = {"ok": True}
            elif isinstance(result, list):
                result = {"items": result}
            return ParseDict(result, Struct())
        except KeyError:
            context.abort(grpc.StatusCode.NOT_FOUND, "MCP resource not found")
        except PermissionError:
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "MCP access denied")
        except (ValueError, TypeError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid MCP configuration")
        except Exception:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP operation failed")

    def GetMcpClient(self, request: Struct, context) -> Struct:
        """GetMcpClient: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.list, user_id)

    def SaveMcpClient(self, request: Struct, context) -> Struct:
        """SaveMcpClient: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.set_enabled, user_id, payload.get("enabled"))

    def CreateMcpConnection(self, request: Struct, context) -> Struct:
        """CreateMcpConnection: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.save, user_id, payload.get("config", {}))

    def UpdateMcpConnection(self, request: Struct, context) -> Struct:
        """UpdateMcpConnection: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.save, user_id, payload.get("config", {}), str(payload.get("connection_id", "")), int(payload.get("revision", 0)))

    def DeleteMcpConnection(self, request: Struct, context) -> Struct:
        """DeleteMcpConnection: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.delete, user_id, str(payload.get("connection_id", "")))

    def ReconnectMcpConnection(self, request: Struct, context) -> Struct:
        """ReconnectMcpConnection: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.apply, user_id, str(payload.get("connection_id", "")), True)

    def TestMcpConnection(self, request: Struct, context) -> Struct:
        """TestMcpConnection: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.test, user_id, payload.get("config", {}), str(payload.get("connection_id", "")))

    def ExportMcpConnections(self, request: Struct, context) -> Struct:
        """ExportMcpConnections: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.export, user_id)

    def PreviewMcpImport(self, request: Struct, context) -> Struct:
        """PreviewMcpImport: persisted client management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_client_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.import_preview, user_id, payload.get("config"))

    def GetMcpServer(self, request: Struct, context) -> Struct:
        """GetMcpServer: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.status, user_id)

    def SaveMcpServer(self, request: Struct, context) -> Struct:
        """SaveMcpServer: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.save_sync, user_id, payload.get("config", {}))

    def CreateMcpCredential(self, request: Struct, context) -> Struct:
        """CreateMcpCredential: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.create_credential, user_id, payload.get("config", {}))

    def RevokeMcpCredential(self, request: Struct, context) -> Struct:
        """RevokeMcpCredential: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.revoke, user_id, str(payload.get("credential_id", "")))

    def RotateMcpCredential(self, request: Struct, context) -> Struct:
        """RotateMcpCredential: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.rotate, user_id, str(payload.get("credential_id", "")))

    def GetMcpAccessRecords(self, request: Struct, context) -> Struct:
        """GetMcpAccessRecords: persisted server management using the shared application service."""
        payload = MessageToDict(request)
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        service = self._mcp_server_service
        if service is None:
            context.abort(grpc.StatusCode.UNAVAILABLE, "MCP service unavailable")
        return self._mcp_result(context, service.records, user_id)
