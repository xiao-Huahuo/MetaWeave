"""utility 类内置工具实现。

函数体由原 builtin.py 机械迁移，工具行为不变。
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Callable
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

def list_available_tools() -> str:
    """
    列出当前用户实际启用的全部工具名称与用途。

    返回格式为每行一个工具:`- 中文名(工具名): 一句话用途`。
    用户逐项关闭或被长期记忆总开关关闭的工具不会返回。
    """

    from agent_service.tools.tool_registry import ToolRegistry

    runtime = get_tool_runtime()
    registry = ToolRegistry.with_builtin_tools(config=runtime.config)
    if not registry.definitions:
        return "当前没有可用工具。"
    lines = []
    disabled_names = set()
    if runtime.settings_service is not None:
        disabled_names = set(runtime.settings_service.get_disabled_tools(user_id=runtime.user_id))
    for definition in sorted(
        registry.definitions.values(),
        key=lambda d: (d.display_name or d.name),
    ):
        from agent_service.tools.definitions import MEMORY_TOOL_NAMES
        if definition.name in MEMORY_TOOL_NAMES and not runtime.long_term_memory_enabled:
            continue
        if definition.name in disabled_names:
            continue
        name = definition.name
        display = definition.display_name or name
        description = (definition.description or "").strip()
        first_line = next(
            (line.strip() for line in description.split("\n") if line.strip()),
            "",
        )
        description_chars = runtime.config.limits.tool_registry_description_chars
        if len(first_line) > description_chars:
            first_line = first_line[:description_chars].rstrip() + "…"
        lines.append(f"- {display}({name}): {first_line}")
    return "\n".join(lines)


def read_tool_result(
    content_ref: str,
    start_line: int | None = None,
    end_line: int | None = None,
    cursor: int | None = None,
) -> str:
    """按稳定引用续读当前会话中已持久化的完整工具结果。"""

    runtime = get_tool_runtime()
    if runtime.message_service is None:
        return "读取失败: 当前运行时缺少消息服务。"
    prefix = "tool-result://"
    normalized_ref = content_ref.strip()
    if not normalized_ref.startswith(prefix):
        return "读取失败: content_ref 必须使用 tool-result:// 引用。"
    tool_call_id = normalized_ref.removeprefix(prefix).strip()
    if not tool_call_id:
        return "读取失败: content_ref 缺少 tool_call_id。"
    messages = runtime.message_service.list_session_messages(
        user_id=runtime.user_id,
        session_id=runtime.session_id,
        limit=None,
        exclude_roles=None,
    )
    target = next(
        (
            message
            for message in reversed(messages)
            if message.role == "tool" and message.tool_call_id == tool_call_id
        ),
        None,
    )
    if target is None:
        return "读取失败: 当前会话中不存在对应工具结果。"
    lines = target.content.splitlines()
    total_lines = len(lines)
    default_lines = runtime.config.limits.terminal_read_default_lines
    max_lines = runtime.config.limits.terminal_read_max_lines
    start = max(int(cursor if cursor is not None else start_line or 0), 0)
    requested_end = int(end_line) if end_line is not None else start + default_lines
    end = min(max(requested_end, start), start + max_lines, total_lines)
    next_cursor = end if end < total_lines else None
    return json.dumps({
        "content_ref": normalized_ref,
        "start_line": start,
        "end_line": end,
        "total_lines": total_lines,
        "next_cursor": next_cursor,
        "complete": next_cursor is None,
        "content": "\n".join(lines[start:end]),
    }, ensure_ascii=False, indent=2)
def list_skills() -> str:
    """
    List all skills visible to the current user.

    Return value: human-readable skill index with source and enabled state.
    """

    runtime = get_tool_runtime()
    if runtime.skill_service is None:
        return "Skill service is not available."
    skills = runtime.skill_service.list_skills(user_id=runtime.user_id)
    if not skills:
        return "No skills found."
    lines = [f"Skills found: {len(skills)}"]
    for index, skill in enumerate(skills, 1):
        enabled = "enabled" if skill.get("enabled") else "disabled"
        lines.append(
            f"{index}. {skill.get('name')} [{skill.get('skill_id')}, {skill.get('source')}, {enabled}] "
            f"- {skill.get('description') or ''}"
        )
    return "\n".join(lines)
def use_skill(skill_ref: str) -> str:
    """
    Load one enabled Skill's SKILL.md body for the current Agent turn.

    skill_ref: Skill id, Skill name, or skill directory name returned by list_skills.
    """

    runtime = get_tool_runtime()
    if runtime.skill_service is None:
        return "Skill service is not available."
    skill = runtime.skill_service.read_skill_body(user_id=runtime.user_id, skill_ref=skill_ref)
    if skill is None:
        return f"Skill not found: {skill_ref}. Call list_skills to inspect available skill ids and names."
    if skill.get("disabled"):
        return f"Skill is disabled: {skill.get('skill_id') or skill_ref}."
    return (
        f"Skill loaded: {skill.get('name')} [{skill.get('skill_id')}]\n"
        f"Source: {skill.get('source')}\n"
        f"Path: {skill.get('path')}\n\n"
        "[SKILL.md]\n"
        f"{skill.get('body') or ''}"
    )
