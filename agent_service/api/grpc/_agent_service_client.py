"""Generated from agent_service.proto; regenerate with scripts/generate_grpc.py."""
'Client and server classes corresponding to protobuf-defined services.'
import grpc
import warnings
from agent_service.api.grpc import agent_service_pb2 as agent__service__pb2
from google.protobuf import struct_pb2 as google_dot_protobuf_dot_struct__pb2
GRPC_GENERATED_VERSION = '1.68.1'
GRPC_VERSION = grpc.__version__
_version_not_supported = False
try:
    from grpc._utilities import first_version_is_lower
    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_GENERATED_VERSION)
except ImportError:
    _version_not_supported = True
if _version_not_supported:
    raise RuntimeError(f'The grpc package installed is at version {GRPC_VERSION},' + f' but the generated code in agent_service_pb2_grpc.py depends on' + f' grpcio>={GRPC_GENERATED_VERSION}.' + f' Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}' + f' or downgrade your generated code using grpcio-tools<={GRPC_VERSION}.')

class AgentService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def GetSafetyConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetSafetyConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveSafetyConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveSafetyConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetMemoryConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetMemoryConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveMemoryConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveMemoryConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetMcpClient(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetMcpClient', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveMcpClient(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveMcpClient', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateMcpConnection(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateMcpConnection', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateMcpConnection(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateMcpConnection', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteMcpConnection(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteMcpConnection', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ReconnectMcpConnection(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ReconnectMcpConnection', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def TestMcpConnection(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/TestMcpConnection', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ExportMcpConnections(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ExportMcpConnections', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def PreviewMcpImport(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/PreviewMcpImport', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetMcpServer(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetMcpServer', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveMcpServer(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveMcpServer', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateMcpCredential(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateMcpCredential', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RevokeMcpCredential(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RevokeMcpCredential', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RotateMcpCredential(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RotateMcpCredential', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetMcpAccessRecords(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetMcpAccessRecords', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def StreamRun(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_stream(request, target, '/agent_service.AgentService/StreamRun', agent__service__pb2.RunRequest.SerializeToString, agent__service__pb2.ChunkMessage.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RunOnce(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RunOnce', agent__service__pb2.RunRequest.SerializeToString, agent__service__pb2.RunResult.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def StreamSessionPrompt(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_stream(request, target, '/agent_service.AgentService/StreamSessionPrompt', agent__service__pb2.RunRequest.SerializeToString, agent__service__pb2.ChunkMessage.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RunSessionPrompt(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RunSessionPrompt', agent__service__pb2.RunRequest.SerializeToString, agent__service__pb2.RunResult.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateSession(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateSession', agent__service__pb2.SessionCreateRequest.SerializeToString, agent__service__pb2.SessionResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetSession(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetSession', agent__service__pb2.SessionIdRequest.SerializeToString, agent__service__pb2.SessionResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListUserSessions(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListUserSessions', agent__service__pb2.ListSessionsRequest.SerializeToString, agent__service__pb2.ListSessionsResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateSessionName(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateSessionName', agent__service__pb2.SessionUpdateRequest.SerializeToString, agent__service__pb2.SessionResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteSession(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteSession', agent__service__pb2.SessionIdRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteAllSessions(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteAllSessions', agent__service__pb2.DeleteAllSessionsRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListMessages(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListMessages', agent__service__pb2.ListMessagesRequest.SerializeToString, agent__service__pb2.ListMessagesResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CancelSession(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CancelSession', agent__service__pb2.CancelRequest.SerializeToString, agent__service__pb2.CancelResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListChildAgents(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListChildAgents', agent__service__pb2.ChildAgentListRequest.SerializeToString, agent__service__pb2.ChildAgentListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def StopChildAgent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/StopChildAgent', agent__service__pb2.ChildAgentControlRequest.SerializeToString, agent__service__pb2.ChildAgentControlResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateChildAgent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateChildAgent', agent__service__pb2.ChildAgentUpdateRequest.SerializeToString, agent__service__pb2.ChildAgentControlResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetEvents(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetEvents', agent__service__pb2.EventsRequest.SerializeToString, agent__service__pb2.EventsResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetRecallDetails(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetRecallDetails', agent__service__pb2.RecallDetailsRequest.SerializeToString, agent__service__pb2.RecallDetailsResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetTaskSuggestions(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetTaskSuggestions', agent__service__pb2.TaskSuggestionsRequest.SerializeToString, agent__service__pb2.TaskSuggestionsResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetTokenUsage(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetTokenUsage', agent__service__pb2.TokenUsageRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetActivityHeatmap(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetActivityHeatmap', agent__service__pb2.ActivityHeatmapRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetRegisteredTools(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetRegisteredTools', agent__service__pb2.ToolListRequest.SerializeToString, agent__service__pb2.ToolListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetSessionAttachment(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetSessionAttachment', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetSessionAttachmentRaw(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetSessionAttachmentRaw', agent__service__pb2.AttachmentRawRequest.SerializeToString, agent__service__pb2.AttachmentRawResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def EnsureUserProfile(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/EnsureUserProfile', agent__service__pb2.UserProfileRequest.SerializeToString, agent__service__pb2.UserProfileResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateUserKnowledgeDir(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateUserKnowledgeDir', agent__service__pb2.UserKnowledgeDirUpdateRequest.SerializeToString, agent__service__pb2.UserProfileResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetLLMConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetLLMConfig', agent__service__pb2.LLMConfigRequest.SerializeToString, agent__service__pb2.LLMConfigResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveLLMConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveLLMConfig', agent__service__pb2.LLMConfigSaveRequest.SerializeToString, agent__service__pb2.LLMConfigResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListLLMConfigPresets(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListLLMConfigPresets', agent__service__pb2.LLMConfigRequest.SerializeToString, agent__service__pb2.LLMConfigPresetListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveLLMConfigPreset(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveLLMConfigPreset', agent__service__pb2.LLMConfigPresetSaveRequest.SerializeToString, agent__service__pb2.LLMConfigPresetResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteLLMConfigPreset(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteLLMConfigPreset', agent__service__pb2.LLMConfigPresetDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetWebSearchConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetWebSearchConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveWebSearchConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveWebSearchConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetFontConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetFontConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveFontConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveFontConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetAppearanceConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetAppearanceConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveAppearanceConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveAppearanceConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetKnowledgeIngestionConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetKnowledgeIngestionConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveKnowledgeIngestionConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveKnowledgeIngestionConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetVlmConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetVlmConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveVlmConfig(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveVlmConfig', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListVlmConfigPresets(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListVlmConfigPresets', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveVlmConfigPreset(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveVlmConfigPreset', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteVlmConfigPreset(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteVlmConfigPreset', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RebuildKnowledge(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RebuildKnowledge', agent__service__pb2.KnowledgeRebuildRequest.SerializeToString, agent__service__pb2.KnowledgeRebuildResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UploadKnowledgeFile(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UploadKnowledgeFile', agent__service__pb2.KnowledgeFileUploadRequest.SerializeToString, agent__service__pb2.KnowledgeRebuildResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListKnowledgeFiles(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListKnowledgeFiles', agent__service__pb2.KnowledgeFileTreeRequest.SerializeToString, agent__service__pb2.KnowledgeFileTreeResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ReadKnowledgeFile(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ReadKnowledgeFile', agent__service__pb2.KnowledgeFileContentRequest.SerializeToString, agent__service__pb2.KnowledgeFileContentResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def PreviewKnowledgePdfPage(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/PreviewKnowledgePdfPage', agent__service__pb2.KnowledgePdfPageRequest.SerializeToString, agent__service__pb2.KnowledgePdfPageResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def WriteKnowledgeFile(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/WriteKnowledgeFile', agent__service__pb2.KnowledgeFileWriteRequest.SerializeToString, agent__service__pb2.KnowledgeFileNode.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateKnowledgeFile(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateKnowledgeFile', agent__service__pb2.KnowledgeFileCreateRequest.SerializeToString, agent__service__pb2.KnowledgeFileNode.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateKnowledgeFolder(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateKnowledgeFolder', agent__service__pb2.KnowledgeFolderCreateRequest.SerializeToString, agent__service__pb2.KnowledgeFileNode.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CopyKnowledgePath(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CopyKnowledgePath', agent__service__pb2.KnowledgePathCopyRequest.SerializeToString, agent__service__pb2.KnowledgeFileNode.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteKnowledgePath(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteKnowledgePath', agent__service__pb2.KnowledgePathDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RenameKnowledgePath(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RenameKnowledgePath', agent__service__pb2.KnowledgePathRenameRequest.SerializeToString, agent__service__pb2.KnowledgeFileNode.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateKnowledgeIngestionJobs(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateKnowledgeIngestionJobs', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListKnowledgeIngestionJobs(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListKnowledgeIngestionJobs', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CancelKnowledgeIngestionJob(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CancelKnowledgeIngestionJob', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SearchAllLibraries(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SearchAllLibraries', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetGitStatus(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetGitStatus', agent__service__pb2.GitUserRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def InitGitRepository(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/InitGitRepository', agent__service__pb2.GitInitRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetGitHistory(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetGitHistory', agent__service__pb2.GitHistoryRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetGitDiff(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetGitDiff', agent__service__pb2.GitDiffRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RestoreGitPaths(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RestoreGitPaths', agent__service__pb2.GitPathsRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CommitGitPaths(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CommitGitPaths', agent__service__pb2.GitCommitRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def PushGitBranch(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/PushGitBranch', agent__service__pb2.GitPushRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateGitBranch(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateGitBranch', agent__service__pb2.GitBranchRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddGitRemote(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddGitRemote', agent__service__pb2.GitRemoteRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SwitchGitBranch(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SwitchGitBranch', agent__service__pb2.GitBranchRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def PullGitBranch(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/PullGitBranch', agent__service__pb2.GitPullRequest.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListSystemPromptEntries(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListSystemPromptEntries', agent__service__pb2.SystemPromptRequest.SerializeToString, agent__service__pb2.SystemPromptEntriesResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddSystemPromptEntry(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddSystemPromptEntry', agent__service__pb2.SystemPromptAddRequest.SerializeToString, agent__service__pb2.SystemPromptEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteSystemPromptEntry(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteSystemPromptEntry', agent__service__pb2.SystemPromptDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListCustomMemories(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListCustomMemories', agent__service__pb2.MemoryListRequest.SerializeToString, agent__service__pb2.MemoryListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddCustomMemory(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddCustomMemory', agent__service__pb2.MemoryAddRequest.SerializeToString, agent__service__pb2.MemoryEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteCustomMemory(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteCustomMemory', agent__service__pb2.MemoryDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListFavorites(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListFavorites', agent__service__pb2.FavoriteListRequest.SerializeToString, agent__service__pb2.FavoriteListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddFavorite(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddFavorite', agent__service__pb2.FavoriteCreateRequest.SerializeToString, agent__service__pb2.FavoriteEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteFavorite(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteFavorite', agent__service__pb2.FavoriteDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListPrivacy(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListPrivacy', agent__service__pb2.PrivacyListRequest.SerializeToString, agent__service__pb2.PrivacyListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddPrivacy(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddPrivacy', agent__service__pb2.PrivacyCreateRequest.SerializeToString, agent__service__pb2.PrivacyEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeletePrivacy(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeletePrivacy', agent__service__pb2.PrivacyDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListFeedback(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListFeedback', agent__service__pb2.FeedbackListRequest.SerializeToString, agent__service__pb2.FeedbackListResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AddFeedback(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AddFeedback', agent__service__pb2.FeedbackCreateRequest.SerializeToString, agent__service__pb2.FeedbackEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateFeedback(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateFeedback', agent__service__pb2.FeedbackUpdateRequest.SerializeToString, agent__service__pb2.FeedbackEntryResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteFeedback(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteFeedback', agent__service__pb2.FeedbackDeleteRequest.SerializeToString, agent__service__pb2.DeleteResponse.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultStatus(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultStatus', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultListItems(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultListItems', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultGetItem(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultGetItem', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultCreateItem(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultCreateItem', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultUpdateItem(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultUpdateItem', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultMoveToTrash(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultMoveToTrash', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultRestoreItems(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultRestoreItems', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultPurgeItems(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultPurgeItems', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultExportItems(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultExportItems', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultImportItems(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultImportItems', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def VaultListTags(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/VaultListTags', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListComponentLibraryComponents(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListComponentLibraryComponents', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateComponentLibraryComponent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateComponentLibraryComponent', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def RenameComponentLibraryComponent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/RenameComponentLibraryComponent', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteComponentLibraryComponent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteComponentLibraryComponent', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetSessionChanges(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetSessionChanges', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UndoSessionChange(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UndoSessionChange', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListAgentQueueTasks(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListAgentQueueTasks', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateAgentQueueTask(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateAgentQueueTask', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateAgentQueueTask(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateAgentQueueTask', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ContinueAgentQueueTask(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ContinueAgentQueueTask', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def TransitionAgentQueueTask(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/TransitionAgentQueueTask', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteAgentQueueTask(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteAgentQueueTask', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UpdateAgentQueueSettings(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UpdateAgentQueueSettings', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetLatexStatus(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetLatexStatus', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def StartLatexInstall(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/StartLatexInstall', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CancelLatexInstall(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CancelLatexInstall', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def UninstallManagedLatex(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/UninstallManagedLatex', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CompileLatex(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CompileLatex', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ClearLatexStorage(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ClearLatexStorage', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetLatexManagement(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetLatexManagement', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetModelManagement(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetModelManagement', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def GetModelPreferences(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/GetModelPreferences', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def SaveModelPreferences(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/SaveModelPreferences', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def InitializeModels(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/InitializeModels', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def StartModelDownload(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/StartModelDownload', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteManagedModel(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteManagedModel', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListAutomations(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListAutomations', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def CreateAutomation(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/CreateAutomation', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ToggleAutomation(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ToggleAutomation', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListAutomationRuns(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListAutomationRuns', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteAutomation(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteAutomation', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteSmartForm(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteSmartForm', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def ListLiteratureEntries(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/ListLiteratureEntries', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def TouchLiteratureEntry(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/TouchLiteratureEntry', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def PatchLiteratureRow(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/PatchLiteratureRow', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DuplicateLiteratureRow(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DuplicateLiteratureRow', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def DeleteLiteratureRow(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/DeleteLiteratureRow', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthRegister(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthRegister', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthLogin(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthLogin', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthCurrent(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthCurrent', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthLogout(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthLogout', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthChangePassword(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthChangePassword', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)

    @staticmethod
    def AuthAdvanceOnboarding(request, target, options=(), channel_credentials=None, call_credentials=None, insecure=False, compression=None, wait_for_ready=None, timeout=None, metadata=None):
        return grpc.experimental.unary_unary(request, target, '/agent_service.AgentService/AuthAdvanceOnboarding', google_dot_protobuf_dot_struct__pb2.Struct.SerializeToString, google_dot_protobuf_dot_struct__pb2.Struct.FromString, options, channel_credentials, insecure, call_credentials, compression, wait_for_ready, timeout, metadata, _registered_method=True)
