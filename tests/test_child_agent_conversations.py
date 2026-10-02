"""子 Agent 对话持久化与主会话归属回归测试。

用途：验证子对话使用正式 Session/Message 表保存，但不会进入根会话列表，
并可随主会话导入、删除和恢复。
"""

from __future__ import annotations

import json
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from sqlmodel import select

from agent_service.api.rest import sessions as sessions_api
from agent_service.agent_core.agent_core import AgentCore
from agent_service.core.agent_config import AgentConfig
from agent_service.models.session import SessionRecord
from agent_service.schemas.message import MessageCreate
from agent_service.schemas.session import SessionCreate
from agent_service.services.message.service import MessageService
from agent_service.services.child_agent import ChildAgentContract, ChildAgentManager
from agent_service.services.session.service import SessionService
from tests.db_test_utils import create_test_engine


@pytest.mark.parametrize("provider,tools,expected", [
    ("dsh", ["dsh.read", "dsh.search", "dsh.git"], []),
    ("dsh", ["read", "read_image", "pwsh"], ["read", "read_image", "pwsh"]),
    ("native", ["dsh.read"], ["dsh.read"]),
])
def test_legacy_dsh_snapshot_does_not_advertise_invented_tools(provider, tools, expected) -> None:
    """旧 DSH aliases 作为未知目录呈现；真实目录与原生工具不得被改名。"""

    child = {"run_id": "child-legacy", "provider": provider, "allowed_tools": tools}
    normalized = AgentCore._with_child_conversation_session("session", child)
    assert normalized["allowed_tools"] == expected
    assert child["allowed_tools"] == tools


def _config() -> AgentConfig:
    """创建不访问真实模型和文件系统的测试配置。"""

    return AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )


def test_child_agent_session_is_hidden_and_deleted_with_parent() -> None:
    """子对话不能进入左侧根历史，删除主会话时必须级联清理消息。"""

    engine = create_test_engine("sqlite://")
    session_service = SessionService(config=_config(), engine=engine, create_tables=False)
    message_service = MessageService(config=_config(), engine=engine, create_tables=False)
    parent = session_service.create_session(SessionCreate(user_id="u1", session_name="主对话"))
    child = session_service.create_child_agent_session(
        user_id="u1",
        parent_session_id=parent.session_id,
        run_id="child-1",
        session_name="explore1",
    )
    message_service.create_message(MessageCreate(
        session_id=child.session_id,
        user_id="u1",
        role="assistant",
        content="完整子 Agent 回复",
    ))

    assert [item.session_id for item in session_service.list_user_sessions("u1")] == [parent.session_id]
    assert session_service.delete_session(parent.session_id) is True
    assert session_service.get_session(child.session_id) is None
    assert message_service.list_session_messages(user_id="u1", session_id=child.session_id, limit=None) == []


def test_import_restores_child_agent_messages_under_new_parent(monkeypatch: Any) -> None:
    """主会话导入必须重建子 Session，并完整写回嵌套对话消息。"""

    engine = create_test_engine("sqlite://")
    config = _config()
    session_service = SessionService(config=config, engine=engine, create_tables=False)
    message_service = MessageService(config=config, engine=engine, create_tables=False)
    monkeypatch.setattr(sessions_api, "_require_session_service", lambda: session_service)
    monkeypatch.setattr(sessions_api, "_require_message_service", lambda: message_service)

    result = sessions_api._do_import({
        "user_id": "u1",
        "session_name": "导入主对话",
        "messages": [{"role": "user", "content": "主任务"}],
        "child_agents": [{
            "run_id": "child-1",
            "name": "explore1",
            "status": "completed",
            "messages": [
                {"role": "user", "content": "子任务"},
                {"role": "assistant", "content": "子任务完成", "node": "agent"},
            ],
        }],
    })
    child_session_id = SessionService.child_agent_session_id(result["session_id"], "child-1")
    child_messages = message_service.list_session_messages(
        user_id="u1",
        session_id=child_session_id,
        limit=None,
    )

    assert [message.content for message in child_messages] == ["子任务", "子任务完成"]
    assert [item.session_id for item in session_service.list_user_sessions("u1")] == [result["session_id"]]
    with sessions_api.DBSession(engine) as db_session:
        child_record = db_session.exec(
            select(SessionRecord).where(SessionRecord.session_id == child_session_id)
        ).one()
    assert child_record.parent_session_id == result["session_id"]
    assert child_record.child_agent_run_id == "child-1"


def test_child_agent_executes_through_persisted_session_without_recursive_spawn() -> None:
    """真实子运行必须走可持久化入口，并关闭子 Agent 的递归召唤能力。"""

    config = _config()
    calls: list[dict[str, Any]] = []

    class FakeSessionService:
        """记录子 Session 创建参数并返回正式会话 ID。"""

        def create_child_agent_session(self, **kwargs: Any) -> SimpleNamespace:
            calls.append({"create": kwargs})
            return SimpleNamespace(session_id="child-session-1")

    agent = object.__new__(AgentCore)
    agent.config = config
    agent.tool_registry = None
    agent.session_service = FakeSessionService()
    agent.child_agent_manager = ChildAgentManager(max_workers=1, config=config)
    agent.run_session_prompt = lambda **kwargs: calls.append({"run": kwargs}) or {"final_output": "完成"}
    try:
        result = json.loads(agent._spawn_child_from_runtime(
            parent_run_id="parent-run",
            user_id="u1",
            session_id="parent-session",
            parent_access_mode="sandbox",
            goal="检索资料",
            mode="foreground",
            category="explore",
            name="explore1",
        ))
    finally:
        agent.child_agent_manager.close()

    assert result["status"] == "completed"
    assert result["conversation_session_id"] == SessionService.child_agent_session_id(
        "parent-session",
        result["run_id"],
    )
    assert calls[0]["create"]["parent_session_id"] == "parent-session"
    assert calls[1]["run"]["session_id"] == "child-session-1"
    assert calls[1]["run"]["allow_child_spawn"] is False


def test_dsh_child_agent_is_rejected_until_user_enables_it() -> None:
    """provider=dsh不得绕过默认关闭的用户级设置。"""

    agent = object.__new__(AgentCore)
    agent.config = _config()
    agent.settings_service = SimpleNamespace(
        is_dsh_coding_agent_enabled_for_user=lambda **kwargs: False,
    )

    with pytest.raises(PermissionError, match="DSH coding agent未启用"):
        agent._spawn_child_from_runtime(
            parent_run_id="parent-run",
            user_id="u1",
            session_id="parent-session",
            parent_access_mode="sandbox",
            goal="修改代码",
            provider="dsh",
            workspace_root="D:/repo",
        )


def test_native_coding_fallback_is_rejected_when_dsh_is_enabled() -> None:
    """有 DSH时后端也必须执行 dsh优先、coding仅后备的选择规则。"""

    agent = object.__new__(AgentCore)
    agent.config = _config()
    agent.settings_service = SimpleNamespace(
        is_dsh_coding_agent_enabled_for_user=lambda **kwargs: True,
    )

    with pytest.raises(PermissionError, match="必须使用 agent_type=dsh"):
        agent._spawn_child_from_runtime(
            parent_run_id="parent-run",
            user_id="u1",
            session_id="parent-session",
            parent_access_mode="sandbox",
            goal="修改代码",
            category="coding",
            provider="native",
            workspace_root="D:/repo",
        )


def test_rejected_dsh_continuation_preserves_active_parent_run() -> None:
    """活动 DSH 续问被拒绝时，不得把原 Turn 的结果改投到新的父 run。"""

    agent = object.__new__(AgentCore)
    agent.config = _config()
    agent.settings_service = SimpleNamespace(
        is_dsh_coding_agent_enabled_for_user=lambda **kwargs: True,
    )
    agent.child_agent_manager = ChildAgentManager(max_workers=1, config=agent.config)
    started = Event()
    release = Event()

    def execute(context):
        """保持原任务活动以触发后端的续问拒绝路径。"""

        started.set()
        release.wait(timeout=2)
        return "原任务完成"

    try:
        record = agent.child_agent_manager.spawn(
            contract=ChildAgentContract(
                goal="原任务",
                parent_run_id="original-parent",
                user_id="u1",
                session_id="parent-session",
                provider="dsh",
            ),
            executor=execute,
        )
        assert started.wait(timeout=1)
        with pytest.raises(RuntimeError, match="仍在运行"):
            agent._continue_child_from_runtime(
                parent_run_id="new-parent",
                user_id="u1",
                session_id="parent-session",
                run_id=record.run_id,
                prompt="新追问",
            )
        assert record.contract.parent_run_id == "original-parent"
        assert record.context is not None
        assert record.context.parent_run_id == "original-parent"
        release.set()
        result = agent.child_agent_manager.wait_for_children(
            parent_run_id="original-parent",
            timeout_seconds=1,
        )
        assert result is not None
        assert result.parent_run_id == "original-parent"
        assert agent.child_agent_manager.drain_results("new-parent") == []
    finally:
        release.set()
        agent.child_agent_manager.close()


def test_dsh_continuation_rebinds_parent_without_old_turn_results() -> None:
    """同一主会话的新父 run 续问成功后，只能收取新 Turn 的结果。"""

    agent = object.__new__(AgentCore)
    agent.config = _config()
    agent.settings_service = SimpleNamespace(
        is_dsh_coding_agent_enabled_for_user=lambda **kwargs: True,
    )
    agent.child_agent_manager = ChildAgentManager(max_workers=1, config=agent.config)
    try:
        record = agent.child_agent_manager.spawn(
            contract=ChildAgentContract(
                goal="原任务",
                parent_run_id="original-parent",
                user_id="u1",
                session_id="parent-session",
                provider="dsh",
                mode="foreground",
            ),
            executor=lambda context: context.goal,
        )
        continued = json.loads(agent._continue_child_from_runtime(
            parent_run_id="new-parent",
            user_id="u1",
            session_id="parent-session",
            run_id=record.run_id,
            prompt="新追问",
            mode="foreground",
        ))
        assert continued["status"] == "completed"
        assert continued["parent_run_id"] == "new-parent"
        assert agent.child_agent_manager.drain_results("original-parent") == []
        results = agent.child_agent_manager.drain_results("new-parent")
        assert len(results) == 1
        assert results[0].result == "新追问"
    finally:
        agent.child_agent_manager.close()


@pytest.mark.parametrize("stale_source", ["snapshot", "late-tool"])
def test_dsh_history_keeps_latest_lifecycle_result(stale_source: str) -> None:
    """冷恢复时正式终态事件必须胜过旧快照或迟到的召唤工具结果。"""

    config = _config()
    engine = create_test_engine("sqlite://")
    sessions = SessionService(config=config, engine=engine, create_tables=False)
    messages = MessageService(config=config, engine=engine, create_tables=False)
    parent = sessions.create_session(SessionCreate(user_id="u1", session_name="DSH 历史"))
    child = {"run_id": "dsh-1", "provider": "dsh", "status": "completed", "result": "真实完成结果"}
    messages.create_message(MessageCreate(
        user_id="u1", session_id=parent.session_id, role="assistant", content="DSH 完成",
        metadata_json={"child_agent_event": {"event_name": "child_agent.completed", "child": child}},
    ))
    stale = {**child, "status": "running", "result": None}
    if stale_source == "snapshot":
        sessions.update_session_state(parent.session_id, json.dumps({"child_agents": [stale]}))
    else:
        messages.create_message(MessageCreate(
            user_id="u1", session_id=parent.session_id, role="tool", content=json.dumps(stale),
        ))
    agent = object.__new__(AgentCore)
    agent.session_service = sessions
    agent._get_message_service = lambda: messages
    agent.child_agent_manager = ChildAgentManager(max_workers=1, config=config)
    try:
        restored = agent.list_child_agents_for_session(parent.session_id)
        assert len(restored) == 1
        assert restored[0]["status"] == "completed"
        assert restored[0]["result"] == "真实完成结果"
    finally:
        agent.child_agent_manager.close()
