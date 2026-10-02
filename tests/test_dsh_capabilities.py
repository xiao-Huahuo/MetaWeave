"""验证 DSH 真实工具目录、权限说明和子任务合同传递。

这些定向测试不使用模型；实际 Runtime 与真实 API 验收另存项目验收记录。
"""

from __future__ import annotations

import json
from threading import Event

import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.services.child_agent import ChildAgentContract, ChildAgentManager
from agent_service.services.child_agent.types import ChildAgentExecutionContext
from agent_service.services.dsh_adapter.executor import DshChildAgentExecutor, _SessionOpenResponse


def test_dsh_catalog_is_unknown_until_runtime_reports_actual_names() -> None:
    """后台创建不得把父工具或历史虚构的 DSH aliases 当成真实能力。"""

    entered, release = Event(), Event()

    def execute(context):
        """在握手后发布实际目录，模拟 Runtime 在模型执行前完成初始化。"""

        entered.set()
        assert release.wait(2)
        context.publish_tools(frozenset({"read", "read_image"}))
        return "read-only complete"

    manager = ChildAgentManager(max_workers=1, config=AgentConfig())
    try:
        record = manager.spawn(
            contract=ChildAgentContract(
                goal="read", parent_run_id="parent", session_id="session", provider="dsh", access_mode="readonly",
            ), executor=execute, parent_tools=frozenset({"dsh.read", "dsh.search", "dsh.git"}),
        )
        assert entered.wait(1)
        assert record.effective_tools == frozenset()
        release.set()
        manager.wait_for_children(parent_run_id="parent", run_ids=[record.run_id], timeout_seconds=2)
        assert record.effective_tools == frozenset({"read", "read_image"})
        events = manager.drain_events_for_session("session")
        assert any(event.event_name == "child_agent.capabilities" and event.allowed_tools == ("read", "read_image") for event in events)
        assert events[-1].allowed_tools == ("read", "read_image")
    finally:
        release.set()
        manager.close()


def test_session_open_requires_tool_catalog() -> None:
    """旧 SDK 没有真实目录时不能被静默接受。"""

    with pytest.raises(ValueError):
        _SessionOpenResponse(sessionId="session", disposition="created", durableSeq=-1)


@pytest.mark.parametrize("tools,expected", [
    (frozenset({"dsh.read", "dsh.search"}), frozenset()),
    (frozenset({"read", "read_image"}), frozenset({"read", "read_image"})),
])
def test_restored_dsh_turn_does_not_publish_old_aliases(tools, expected) -> None:
    """旧任务续问的首个状态事件也必须等待真实目录，不得恢复虚构能力。"""

    manager = ChildAgentManager(max_workers=1, config=AgentConfig())
    try:
        record = manager.restore(
            run_id="restored", contract=ChildAgentContract(
                goal="inspect", parent_run_id="parent", provider="dsh", allowed_tools=tools,
            ), executor=lambda _context: "done",
        )
        assert record.effective_tools == expected
        assert record.context.allowed_tools == expected
    finally:
        manager.close()


def test_dsh_prompt_carries_workspace_permissions_and_output_contract() -> None:
    """父任务的引用和输出格式须真正传给独立 DSH 模型。"""

    context = ChildAgentExecutionContext(
        run_id="child", parent_run_id="parent", goal="Inspect repository", user_id="u1", session_id="session",
        agent_mode="react", allowed_tools=frozenset({"read", "read_image"}), access_mode="readonly",
        input_refs=("README.md",), output_contract={"format": "json", "fields": ["findings"]},
        cancellation=Event(), provider="dsh", workspace_root="D:/workspace",
    )
    prompt = DshChildAgentExecutor._build_prompt(context)
    assert "Inspect repository" in prompt
    assert "D:/workspace" in prompt
    assert "readonly" in prompt
    assert "read_image" in prompt
    assert "无 Shell" in prompt
    assert "sandbox" in prompt
    assert "README.md" in prompt
    assert json.dumps(dict(context.output_contract), ensure_ascii=False) in prompt
    assert "dsh.git" not in prompt


def test_sandbox_prompt_does_not_invent_a_missing_shell() -> None:
    """权限名不能代替真实 Runtime 目录证明命令能力。"""

    context = ChildAgentExecutionContext(
        run_id="child", parent_run_id="parent", goal="Inspect", user_id="u1", session_id="session",
        agent_mode="react", allowed_tools=frozenset({"read"}), access_mode="sandbox",
        input_refs=(), output_contract={}, cancellation=Event(), provider="dsh", workspace_root="D:/workspace",
    )
    assert "无 Shell" in DshChildAgentExecutor._build_prompt(context)
