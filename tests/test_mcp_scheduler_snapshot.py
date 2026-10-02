"""Remote MCP schemas must survive local worker/Redis request serialization and model binding."""
from types import SimpleNamespace
from langchain_core.messages import HumanMessage
from agent_service.services.scheduler.redis_backend import SerializedChatRequest
from agent_service.tools import ToolRegistry
from agent_service.tools.builtin import BuiltinToolDefinition


def test_mcp_schemas_survive_request_boundary(monkeypatch):
    """A worker without Agent thread-local state still receives the same complete remote schema."""
    registry = ToolRegistry()
    schema = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}}, "required": ["queries"]}
    registry.register(BuiltinToolDefinition(name="mcp__fixture__search", description="remote", args_schema=schema, function=lambda **args: ""))
    monkeypatch.setattr("agent_service.tools.runtime_context.get_tool_runtime", lambda: SimpleNamespace(tool_registry=registry))
    request = SerializedChatRequest.from_messages(task_id="test", task_type="foreground_agent",
        messages=[HumanMessage(content="search")], tool_names=["mcp__fixture__search"], timeout_seconds=5, max_retries=0)
    restored = SerializedChatRequest.from_stream_entry(request.to_stream_fields())
    assert restored.tool_definitions == [{"type": "function", "function": {"name": "mcp__fixture__search", "description": "remote", "parameters": schema}}]


def test_knowledge_results_use_the_domain_result_score():
    """The exported RAG response uses RetrievedMemory.final_score rather than an invented score attribute."""
    from agent_service.services.mcp_server.catalog import execute_business
    result = SimpleNamespace(memory=SimpleNamespace(content="evidence", source_uri="note.md"), final_score=0.73)
    services = SimpleNamespace(knowledge_library_service=None, library_service=None,
        retrieval_service=SimpleNamespace(retrieve_knowledge=lambda **arguments: [result]))
    assert execute_business(services, "owner", "get_knowledge_context", {"query": "evidence"})[0]["score"] == 0.73
