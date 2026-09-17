"""动态上下文预算、历史选择和工具结果表示的核心回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_service.agent_core.nodes.model_decision import ModelDecisionNode
from agent_service.core.agent_config import AgentConfig
from agent_service.core.context_budget import ContextBudget, ModelCapacity
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.tools.builtin.utility import read_tool_result
from agent_service.tools.result_envelope import build_tool_result_envelope


def test_context_budget_uses_model_capacity_below_service_ceiling() -> None:
    """实际模型窗口小于服务 ceiling 时，所有预算必须随模型窗口收紧。"""

    config = AgentConfig()
    capacity = ModelCapacity(
        model_name="small-context-model",
        context_window_tokens=131_072,
        max_output_tokens=16_384,
        source="explicit",
    )

    budget = ContextBudget.from_config(config=config, capacity=capacity)

    assert budget.effective_window_tokens == 131_072
    assert budget.output_reserve_tokens == 8_520
    assert budget.safety_margin_tokens == 2_622
    assert budget.input_budget_tokens == 119_930


def test_context_budget_never_exceeds_service_ceiling() -> None:
    """模型能力大于 100 万时仍只能使用服务允许的 ceiling。"""

    config = AgentConfig()
    capacity = ModelCapacity(
        model_name="large-context-model",
        context_window_tokens=2_000_000,
        max_output_tokens=100_000,
        source="explicit",
    )

    budget = ContextBudget.from_config(config=config, capacity=capacity)

    assert budget.effective_window_tokens == config.memory.context_window_tokens
    assert budget.input_budget_tokens < budget.effective_window_tokens


def test_unknown_model_uses_service_ceiling_instead_of_128k_fallback() -> None:
    """未登记模型不得再暗中降到 128K，应直接使用 100 万服务窗口。"""

    config = AgentConfig()
    capacity = ModelCapacity.resolve(
        config=config,
        model_name="deepseek-v4-flash",
        model_tier="large",
    )
    budget = ContextBudget.from_config(config=config, capacity=capacity)

    assert capacity.context_window_tokens == 1_000_000
    assert capacity.source == "service_ceiling_default"
    assert budget.effective_window_tokens == 1_000_000
    assert budget.input_budget_tokens == 971_808
    usage = ContextBuilder.context_usage_from_serialized(
        [{"role": "user", "content": "hello"}],
        config=config,
        model_name="deepseek-v4-flash",
    )
    assert usage["max_context_tokens"] == 1_000_000
    assert usage["input_budget_tokens"] == 971_808


def test_history_selection_skips_oversized_message_and_keeps_earlier_context() -> None:
    """一条超大最近消息不得通过 break 连带清空它之前仍可容纳的历史。"""

    older = HumanMessage(content="必须保留的较早事实")
    oversized = AIMessage(content="x" * 20_000)
    budget = ContextBuilder.estimate_messages_tokens([older]) + 8

    selected = ContextBuilder.select_recent_messages_within_budget(
        [older, oversized],
        token_budget=budget,
    )

    assert older in selected
    assert oversized not in selected


def test_model_boundary_no_longer_applies_fixed_character_tool_truncation() -> None:
    """主模型边界只能按统一 token 预算装配，不能把普通工具结果固定裁成 900 字。"""

    system = SystemMessage(content="system")
    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "generic_tool", "args": {}}],
    )
    result = ToolMessage(
        content="a" * 5_000 + "TAIL_MARKER",
        tool_call_id="call_1",
        name="generic_tool",
    )

    prepared = ModelDecisionNode._prepare_messages_for_llm(
        system,
        [HumanMessage(content="run"), assistant, result],
    )

    assert str(prepared[-1].content).endswith("TAIL_MARKER")
    assert "工具返回内容已压缩" not in str(prepared[-1].content)


def test_tool_pair_is_atomic_when_recent_history_is_selected() -> None:
    """预算选择不得只保留 ToolMessage 或只保留发起调用的 AIMessage。"""

    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "generic_tool", "args": {}}],
    )
    result = ToolMessage(content="ok", tool_call_id="call_1", name="generic_tool")
    pair_budget = ContextBuilder.estimate_messages_tokens([assistant, result]) + 8

    selected = ContextBuilder.select_recent_messages_within_budget(
        [HumanMessage(content="old"), assistant, result],
        token_budget=pair_budget,
    )

    assert selected[-2:] == [assistant, result]


def test_dynamic_assembly_uses_head_tail_and_content_reference() -> None:
    """超大工具结果必须保留头尾、标明原始大小并提供可续读引用。"""

    config = AgentConfig()
    config.memory.context_window_tokens = 2_000
    config.memory.context_output_reserve_ratio = 0.1
    config.memory.context_safety_margin_ratio = 0.05
    config.memory.context_max_single_block_ratio = 0.2
    capacity = ModelCapacity("tiny", 2_000, 400, "explicit")
    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call_large", "name": "generic_tool", "args": {}}],
    )
    result = ToolMessage(
        content="HEAD" + (" middle" * 3_000) + " TAIL",
        tool_call_id="call_large",
        name="generic_tool",
    )

    assembled, report = ContextBuilder.assemble_request_messages(
        system_message=SystemMessage(content="system"),
        messages=[HumanMessage(content="earlier request"), assistant, result, HumanMessage(content="inspect")],
        config=config,
        capacity=capacity,
    )

    represented = next(message for message in assembled if isinstance(message, ToolMessage))
    assert isinstance(represented, ToolMessage)
    assert "HEAD" in str(represented.content)
    assert "TAIL" in str(represented.content)
    assert "tool-result://call_large" in str(represented.content)
    assert represented.additional_kwargs["tool_result"]["continuation"]["supported"] is True
    assert report["final_input_tokens"] <= report["input_budget_tokens"]


def test_dynamic_assembly_prefers_structured_tool_envelope_before_head_tail() -> None:
    """完整结果放不下时，应先使用确定性结构化结论而不是重新裁正文。"""

    config = AgentConfig()
    config.memory.context_window_tokens = 2_000
    config.memory.context_output_reserve_ratio = 0.1
    config.memory.context_safety_margin_ratio = 0.05
    config.memory.context_max_single_block_ratio = 0.2
    capacity = ModelCapacity("tiny", 2_000, 400, "explicit")
    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call_structured", "name": "generic_tool", "args": {}}],
    )
    envelope = build_tool_result_envelope(
        tool_call_id="call_structured",
        tool_name="generic_tool",
        content="HEAD" + (" middle" * 3_000) + " TAIL",
        failed=False,
    ).to_dict()
    result = ToolMessage(
        content="HEAD" + (" middle" * 3_000) + " TAIL",
        tool_call_id="call_structured",
        name="generic_tool",
        additional_kwargs={"tool_result": envelope},
    )

    assembled, report = ContextBuilder.assemble_request_messages(
        system_message=SystemMessage(content="system"),
        messages=[HumanMessage(content="inspect"), assistant, result],
        config=config,
        capacity=capacity,
    )

    represented = assembled[-1]
    assert isinstance(represented, ToolMessage)
    assert "工具 generic_tool 已完成" in str(represented.content)
    assert " middle" not in str(represented.content)
    assert represented.additional_kwargs["tool_result"]["representation"] == "structured"
    assert report["representations"][0]["representation"] == "structured"


def test_dynamic_assembly_reports_reference_when_only_reference_fits() -> None:
    """结构化结论本身过大时，必须明确降级为可续读引用。"""

    config = AgentConfig()
    config.memory.context_window_tokens = 600
    config.memory.context_output_reserve_ratio = 0.1
    config.memory.context_safety_margin_ratio = 0.05
    config.memory.context_max_single_block_ratio = 0.12
    capacity = ModelCapacity("tiny", 600, 100, "explicit")
    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call_reference", "name": "generic_tool", "args": {}}],
    )
    result = ToolMessage(
        content="body " * 4_000,
        tool_call_id="call_reference",
        name="generic_tool",
        additional_kwargs={"tool_result": {
            "tool_name": "generic_tool",
            "status": "success",
            "summary": "oversized summary " * 2_000,
            "content_ref": "tool-result://call_reference",
            "continuation": {"supported": True, "method": "read_tool_result"},
        }},
    )

    assembled, report = ContextBuilder.assemble_request_messages(
        system_message=SystemMessage(content="system"),
        messages=[HumanMessage(content="earlier request"), assistant, result, HumanMessage(content="inspect")],
        config=config,
        capacity=capacity,
    )

    represented = next(message for message in assembled if isinstance(message, ToolMessage))
    assert isinstance(represented, ToolMessage)
    assert "tool-result://call_reference" in str(represented.content)
    assert represented.additional_kwargs["tool_result"]["representation"] == "reference"
    assert report["representations"][0]["representation"] == "reference"


def test_terminal_envelope_exposes_status_and_continuation() -> None:
    """Terminal 结果必须提供确定性状态、关键事实和续读入口。"""

    content = json.dumps({
        "segments": [{"returncode": 0}, {"returncode": 1}],
        "truncated": True,
    })

    envelope = build_tool_result_envelope(
        tool_call_id="call_terminal",
        tool_name="run_terminal_command",
        content=content,
        failed=False,
    ).to_dict()

    assert envelope["status"] == "error"
    assert "failed_segments=1" in envelope["key_facts"]
    assert envelope["content_ref"] == "tool-result://call_terminal"
    assert envelope["continuation"]["method"] == "read_tool_result"


def test_read_tool_result_continues_persisted_result(monkeypatch) -> None:
    """续读工具必须按 cursor 返回正式消息中的后续内容，不能重跑原工具。"""

    message = SimpleNamespace(
        role="tool",
        tool_call_id="call_saved",
        content="\n".join(f"line-{index}" for index in range(12)),
    )
    message_service = SimpleNamespace(list_session_messages=lambda **_kwargs: [message])
    runtime = SimpleNamespace(
        user_id="u1",
        session_id="s1",
        message_service=message_service,
        config=SimpleNamespace(limits=SimpleNamespace(
            terminal_read_default_lines=4,
            terminal_read_max_lines=10,
        )),
    )
    monkeypatch.setattr(
        "agent_service.tools.builtin.utility.get_tool_runtime",
        lambda: runtime,
    )

    payload = json.loads(read_tool_result("tool-result://call_saved", cursor=4))

    assert payload["content"].splitlines() == ["line-4", "line-5", "line-6", "line-7"]
    assert payload["next_cursor"] == 8


def test_model_visible_character_budget_fields_and_compactors_are_removed() -> None:
    """动态预算上线后不得保留可重新启用旧字符截断的配置或死代码。"""

    obsolete_fields = {
        "agent_tool_registry_result_chars",
        "agent_tool_large_result_chars",
        "agent_tool_recent_result_chars",
        "agent_tool_old_result_chars",
        "agent_observation_tool_result_chars",
        "agent_planner_history_preview_chars",
        "attachment_context_max_chars",
        "attachment_single_max_chars",
        "skill_body_max_chars",
        "web_fetch_max_chars",
        "tool_markdown_projection_max_chars",
        "local_vision_ocr_context_chars",
        "graph_single_section_max_chars",
        "structured_prompt_source_chars",
    }
    limits = AgentConfig.BusinessLimitsConfig()
    assert all(not hasattr(limits, field) for field in obsolete_fields)
    assert not hasattr(AgentConfig.MemoryConfig(), "context_unknown_model_fallback_tokens")
    source = (
        Path(__file__).resolve().parents[1]
        / "agent_service"
        / "agent_core"
        / "nodes"
        / "model_decision.py"
    ).read_text(encoding="utf-8")
    assert "_compact_tool_message" not in source
    assert "agent_tool_recent_result_chars" not in source


def test_model_input_producers_do_not_reintroduce_fixed_prefix_slices() -> None:
    """发送给模型的关键生产路径不得重新出现旧字符前缀截断。"""

    root = Path(__file__).resolve().parents[1]
    forbidden_by_file = {
        "agent_service/agent_core/nodes/observation.py": ["content[:self.config.limits"],
        "agent_service/agent_core/nodes/planner.py": ["content[:preview_chars"],
        "agent_service/tools/builtin/knowledge.py": ["content[:max_chars"],
        "agent_service/tools/builtin/web.py": ["text[:limits.web_fetch"],
        "agent_service/services/skill/service.py": ["read_text(encoding=\"utf-8\")[:"],
        "agent_service/services/knowledge_graph/service.py": ["content[:self.config.limits"],
        "agent_service/services/structured_generation/service.py": ["request.source.content[:"],
    }
    violations: list[str] = []
    for relative_path, forbidden_tokens in forbidden_by_file.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        violations.extend(
            f"{relative_path}: {token}"
            for token in forbidden_tokens
            if token in source
        )
    assert violations == []
