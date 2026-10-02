"""agent 类内置工具实现。

函数体由原 builtin.py 机械迁移，工具行为不变。
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from agent_service.tools.runtime_context import (
    AGENT_ACCESS_READONLY,
    get_markdown_html_visualization_callback,
    get_task_list_callback,
    get_tool_runtime,
    register_network_citation,
    register_tool_citation,
)
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate
from agent_service.services.todo.service import TodoService
from agent_service.services.automation.service import AutomationService
from agent_service.tools.builtin.builtin import (
    BuiltinToolDefinition, _deny_readonly_write, _is_readonly_access,
    _safe_visualization_filename, _strip_markdown_html_fence,
)

def spawn_child_agent(
    goal: str,
    agent_type: str = "explore",
    mode: str = "background",
    allowed_tools: list[str] | None = None,
    access_mode: str = "sandbox",
    input_refs: list[str] | None = None,
    output_contract: dict[str, Any] | None = None,
    category: str = "",
    name: str = "",
    provider: str = "native",
    workspace_root: str = "",
) -> str:
    """由主 Agent 创建一个前台或后台子 Agent,返回子任务运行信息。

    agent_type: explore、dsh或coding，这是模型必须显式选择的真实类型。
    category/provider: 内部兼容字段，由 agent_type统一映射。
    name: 子 Agent名字；留空时按类型自动生成。
    workspace_root: dsh和coding代码 Agent的工作区绝对路径。
    """

    runtime = get_tool_runtime()
    if runtime.child_agent_spawner is None:
        return "当前 Agent 运行时未启用子 Agent 能力。"
    normalized_type = agent_type.strip().lower()
    if normalized_type not in {"explore", "dsh", "coding"}:
        return "agent_type 必须是 explore、dsh 或 coding。"
    type_mapping = {
        "explore": ("native", "explore", "readonly"),
        "dsh": ("dsh", "dsh", access_mode),
        "coding": ("native", "coding", access_mode),
    }
    provider, category, access_mode = type_mapping[normalized_type]
    return runtime.child_agent_spawner(
        goal=goal,
        mode=mode,
        allowed_tools=allowed_tools,
        access_mode=access_mode,
        input_refs=input_refs or [],
        output_contract=output_contract or {},
        category=category or None,
        name=name or None,
        provider=provider,
        workspace_root=workspace_root,
    )
def wait_for_child_agents(
    run_ids: list[str] | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """由主 Agent 等待一个后台子 Agent 结果,返回结果和当前子任务快照。"""

    runtime = get_tool_runtime()
    if runtime.child_agent_waiter is None:
        return "当前 Agent 运行时未启用等待子 Agent 的能力。"
    return runtime.child_agent_waiter(
        run_ids=run_ids or [],
        timeout_seconds=timeout_seconds,
    )


def request_user_input(questions: list[dict[str, Any]]) -> str:
    """同步询问用户；当前 Agent 暂停，收到真实回答后才继续思考。"""
    runtime = get_tool_runtime()
    if runtime.user_question_asker is None:
        return "当前 Agent 运行时未启用同步提问能力。"
    return runtime.user_question_asker(questions=questions)


def continue_child_agent(
    run_id: str,
    prompt: str,
    mode: str = "background",
) -> str:
    """向同一个 DSH Child Agent Conversation提交后续 Turn。"""

    runtime = get_tool_runtime()
    if runtime.child_agent_continuation is None:
        return "当前 Agent 运行时未启用 DSH 子 Agent持续追问能力。"
    return runtime.child_agent_continuation(run_id=run_id, prompt=prompt, mode=mode)
