"""Main-agent DSH provider catalog and per-user availability prompt tests."""

from agent_service.core.agent_config import AgentConfig
from agent_service.tools.definitions import CHILD_AGENT_TOOL_DEFINITIONS


def test_main_agent_prompt_describes_dsh_when_enabled() -> None:
    """Enabled users must see the provider name, purpose and required workspace root."""

    prompt = AgentConfig.PromptConfig().resolve_child_agent_type_prompt(dsh_enabled=True)

    assert "explore：" in prompt
    assert "dsh：deepseek-harness代码 Agent" in prompt
    assert "coding：MW原生代码 Agent" in prompt
    assert "agent_type=dsh" in prompt
    assert "禁止使用coding" in prompt
    assert "workspace_root" in prompt


def test_main_agent_prompt_forbids_dsh_when_disabled() -> None:
    """Disabled users must receive an explicit native fallback instead of guessing."""

    prompt = AgentConfig.PromptConfig().resolve_child_agent_type_prompt(dsh_enabled=False)

    assert "agent_type=coding" in prompt
    assert "禁止使用dsh" in prompt


def test_dsh_prompt_matches_readonly_and_command_capabilities() -> None:
    """只读无 Shell；环境盘点应选择 sandbox，并如实区分终态与任务完成。"""

    prompt = AgentConfig.PromptConfig().resolve_child_agent_type_prompt(dsh_enabled=True)
    assert "readonly仅提供 read / read_image" in prompt
    assert "python --version" in prompt and "git status" in prompt
    assert "应选择 access_mode=sandbox" in prompt
    assert "不能突破父 Agent 的访问权限" in prompt
    assert "completed只表示本轮结束" in prompt


def test_static_prompt_does_not_duplicate_dynamic_dsh_rules() -> None:
    """DSH provider和状态规则只能由每轮动态提示维护。"""

    static_prompt = AgentConfig.PromptConfig().agent_system_prompt
    assert "provider=dsh" not in static_prompt
    assert "DSH" not in static_prompt
    assert "禁止使用以下说辞" not in static_prompt


def test_spawn_tool_exposes_one_real_agent_type_dimension() -> None:
    """模型工具 schema不得再次暴露 category/provider内部维度。"""

    definition = next(item for item in CHILD_AGENT_TOOL_DEFINITIONS if item.name == "spawn_child_agent")
    properties = definition.args_schema["properties"]
    assert properties["agent_type"]["enum"] == ["explore", "dsh", "coding"]
    assert "agent_type" in definition.args_schema["required"]
    assert "workspace_root" in properties
    assert "category" not in properties
    assert "provider" not in properties
