"""memory 类内置工具实现。

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

def get_long_term_memory(query: str, top_k: int | None = None) -> str:
    """
    检索当前用户的长期摘要记忆。

    query: 检索查询文本。
    top_k: 最多返回多少条结果。
    """

    runtime = get_tool_runtime()
    top_k = top_k or runtime.config.limits.memory_search_default_limit
    results = runtime.retrieval_service.retrieve_long_term_memory(
        query=query,
        user_id=runtime.user_id,
        session_id=runtime.session_id,
        top_k=top_k,
    )
    if not results:
        return "未找到相关长期记忆。"
    lines = []
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item.memory.content}")
    return "\n\n".join(lines)
def get_knowledge_context(query: str, top_k: int | None = None) -> str:
    """
    检索知识库相关片段。

    query: 检索查询文本。
    top_k: 最多返回多少条结果。
    """

    runtime = get_tool_runtime()
    top_k = top_k or runtime.config.memory.knowledge_search_semantic_top_k
    results = runtime.retrieval_service.retrieve_knowledge(
        query=query,
        user_id=runtime.user_id,
        top_k=top_k,
    )
    if not results:
        return "未找到相关知识库内容。"
    lines = []
    for i, item in enumerate(results, 1):
        source = item.memory.source_uri or "未知来源"
        citation_id = register_tool_citation(
            source_uri=source,
            content=item.memory.content,
            adopted_by_default=True,
        )
        lines.append(f"{i}. [{citation_id}] 来源: {source}\n   内容: {item.memory.content}")
    return "\n\n".join(lines)
def _supersede_prior_entries(
    *,
    runtime: Any,
    user_id: str,
    memory_type: str,
) -> None:
    """
    将同一用户、同一 memory_type 的旧 active 记忆标记为 superseded。
    确保手动写入的类型中只有最新一条保持 active 状态。
    """

    from sqlmodel import Session, select

    from agent_service.models.longterm_memory_spec import LongTermMemorySpec

    if runtime.memory_service is None:
        return
    memory_service = runtime.memory_service
    with Session(memory_service.engine) as db_session:
        statement = (
            select(LongTermMemorySpec)
            .where(LongTermMemorySpec.user_id == user_id)
            .where(LongTermMemorySpec.tag == runtime.config.constants.memory_tag)
            .where(LongTermMemorySpec.memory_type == memory_type)
            .where(LongTermMemorySpec.source_type == "manual_write")
        )
        records = db_session.exec(statement).all()
        for record in records:
            metadata = dict(record.metadata_json or {})
            if metadata.get("fact_status") != "active":
                continue
            metadata["fact_status"] = "superseded"
            record.metadata_json = metadata
            db_session.add(record)
        db_session.commit()
def write_long_term_memory(
    content: str,
    memory_type: str = "important_fact_summary",
    importance: float = 0.5,
    authority: float = 0.5,
) -> str:
    """
    向当前用户的长期记忆中写入一条记录,包含向量化后可被后续对话检索召回。

    content: 需要记忆的内容。
    memory_type: 记忆子类型,默认 important_fact_summary。可选值与检索优先级相关。
    importance: 重要性(0~1),默认 0.5。
    authority: 权威性(0~1),默认 0.5。
    """

    runtime = get_tool_runtime()
    from agent_service.services.memory.manual_write import write_manual_memory
    write_manual_memory(config=runtime.config, memory_service=runtime.memory_service,
        embedding_service=runtime.embedding_service, user_id=runtime.user_id, session_id=runtime.session_id,
        content=content, memory_type=memory_type, importance=importance, authority=authority)
    return f"已记住: {content}"
def delete_long_term_memory(content: str) -> str:
    """
    删除当前用户的一条长期记忆。按内容文本匹配后删除。

    content: 需要删除的记忆内容关键词或完整句子。会尝试精确匹配和包含匹配。
    """

    if _is_readonly_access():
        return _deny_readonly_write("删除长期记忆")
    normalized_content = content.strip()
    if not normalized_content:
        return "删除失败: content 不能为空。"
    runtime = get_tool_runtime()
    matched = runtime.memory_service.find_user_memory_by_content(
        user_id=runtime.user_id,
        content=normalized_content,
    )
    if not matched:
        return f"未找到内容匹配的长期记忆: {normalized_content}"
    success = runtime.memory_service.delete_memory(memory_id=matched.memory_id)
    if success:
        return f"已删除长期记忆: {matched.content}"
    return f"删除长期记忆失败，可能已被删除。"
def delete_long_term_rule(content: str) -> str:
    """
    删除当前用户的一条长期系统规则。按内容文本匹配后删除。

    content: 需要删除的规则内容关键词或完整句子。会尝试精确匹配和包含匹配。
    """

    if _is_readonly_access():
        return _deny_readonly_write("删除长期规则")
    normalized_content = content.strip()
    if not normalized_content:
        return "删除失败: content 不能为空。"
    runtime = get_tool_runtime()
    if runtime.memory_service is None:
        return "删除长期规则失败: 当前工具运行时缺少设置存储服务。"
    from agent_service.services.settings.service import SettingsService

    settings_service = SettingsService(config=runtime.config, memory_service=runtime.memory_service)
    entries = settings_service.list_system_prompt_entries(user_id=runtime.user_id)
    lower_content = normalized_content.lower()
    matched = None
    for entry in entries:
        if entry["content"].strip().lower() == lower_content:
            matched = entry
            break
    if not matched:
        for entry in entries:
            entry_content = entry["content"].strip().lower()
            if lower_content in entry_content or entry_content in lower_content:
                matched = entry
                break
    if not matched:
        return f"未找到内容匹配的长期规则: {normalized_content}"
    success = settings_service.delete_system_prompt_entry(prompt_id=matched["prompt_id"])
    if success:
        return f"已删除长期规则: {matched['content']}"
    return f"删除长期规则失败，可能已被删除。"
def write_long_term_rule(content: str) -> str:
    """
    追加一条当前用户的长期系统规则。

    content: 需要每轮 Agent 都必须读取并遵守的长期规则。该内容写入用户自定义系统提示词,
    与设置页手动追加系统提示词等效,不会作为 RAG 记忆按相关性召回。
    """

    normalized_content = content.strip()
    if not normalized_content:
        return "长期规则写入失败: content 不能为空。"
    runtime = get_tool_runtime()
    if runtime.memory_service is None:
        return "长期规则写入失败: 当前工具运行时缺少设置存储服务。"
    from agent_service.services.settings.service import SettingsService

    settings_service = SettingsService(config=runtime.config, memory_service=runtime.memory_service)
    entry = settings_service.add_system_prompt_entry(
        user_id=runtime.user_id,
        content=normalized_content,
    )
    return f"已写入长期规则: {entry['prompt_id']}"
