"""Execute a real compiled Agent graph against the real stdio SDK, replacing only the billable LLM provider."""
import sys
from pathlib import Path
from langchain_core.messages import AIMessageChunk, ToolMessage
from agent_service.agent_core import AgentCore
from agent_service.services.scheduler import LLMTaskScheduler
from agent_service.tools.runtime_context import child_tool_scope
from tests.mcp_test_support import make_mcp_services


def test_compiled_agent_calls_remote_tool_and_respects_child_scope(tmp_path, monkeypatch):
    """Provider-bound schemas, tool execution and final streamed/buffered answers share the same turn snapshot."""
    class Provider:
        """Deterministic LLM transport fixture; MCP/graph/services remain their real implementations."""
        def __init__(self, **kwargs):
            self.bound = []
        def bind_tools(self, tools):
            self.bound = tools
            return self
        def stream(self, messages):
            remote = next((tool for tool in self.bound if (tool.get("function", {}).get("name", "") if isinstance(tool, dict) else tool.name).endswith("__echo")), None)
            if remote is None:
                yield AIMessageChunk(content="no remote tools")
            elif isinstance(messages[-1], ToolMessage):
                assert "round trip" in messages[-1].content
                yield AIMessageChunk(content="SDK echo verified")
            else:
                name = remote["function"]["name"] if isinstance(remote, dict) else remote.name
                yield AIMessageChunk(content="", tool_call_chunks=[{"name": name, "args": '{"text":"round trip"}', "id": "call_fixture", "index": 0}])
    monkeypatch.setattr("agent_service.services.scheduler.runtime.ChatOpenAI", Provider)
    services = make_mcp_services(tmp_path)
    config = services.config
    config.storage.project_root = tmp_path
    config.model.model_name, config.model.api_key, config.model.base_url = "fixture-model", "fixture-key", "https://example.invalid/v1"
    client = services.mcp_client_service
    scheduler = LLMTaskScheduler(config=config, settings_service=services.settings_service)
    client.start()
    agent = None
    try:
        client.set_enabled("owner", True)
        client.save("owner", {"name": "SDK", "command": sys.executable,
            "args": [str(Path(__file__).with_name("mcp_stdio_fixture.py"))]})
        agent = AgentCore(config=config, settings_service=services.settings_service, task_scheduler=scheduler)
        agent.mcp_client_service = client
        first = agent.run_once(prompt="call echo", user_id="owner", session_id="mcp_turn", agent_mode="react")
        assert first["final_output"] == "SDK echo verified"
        streamed = list(agent.stream_run(prompt="call echo", user_id="owner", session_id="mcp_stream", agent_mode="react"))
        assert agent.extract_final_output(streamed) == "SDK echo verified"
        with child_tool_scope(frozenset()):
            restricted = agent.run_once(prompt="restricted child", user_id="owner", session_id="mcp_child", agent_mode="react")
        assert restricted["final_output"] == "no remote tools"
    finally:
        if agent:
            agent.close()
        scheduler.shutdown()
        client.shutdown()
        services.database_engine.dispose()
