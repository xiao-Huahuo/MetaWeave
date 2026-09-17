"""
工具调用节点。

功能说明:
本文件只实现 `ToolCallNode` 一个节点。该节点负责执行模型消息中的 tool_calls,
并把工具执行结果写回 LangGraph 消息状态。

使用说明:
`graph.py` 会把本节点注册为 `action` 节点。默认路径使用项目工具执行器执行
内置工具;如果未来传入外部 LangChain 工具且没有项目执行器,则回退到 LangGraph
自带 `ToolNode`。
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from agent_service.agent_core.nodes.base import AgentState
from agent_service.core.agent_config import AgentConfig
from agent_service.tools import ToolExecutor
from agent_service.tools.result_envelope import build_tool_result_envelope
from agent_service.tools.runtime_context import get_tool_citation_map, get_tool_runtime, get_tool_trace_callback

TASK_LIST_TOOL_NAMES = {"create_task_list", "complete_task_list_item", "finish_task_list"}


class ToolCallNode:
    """
    执行工具调用的 LangGraph 节点。

    config: 全局配置对象,保留给后续根据配置选择内置工具或 MCP 工具。
    tools: LangChain 工具列表,用于构造 LangGraph 的 `ToolNode`。
    tool_executor: 项目工具执行器,优先用于执行模型生成的 tool_calls。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        tools: Sequence[Any] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """初始化工具节点;没有工具时保留空节点以返回可观测错误。"""

        self.config = config
        self.tools = list(tools or [])
        self.tool_executor = tool_executor
        self.tool_node = ToolNode(self.tools) if self.tools and self.tool_executor is None else None

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """执行工具调用;若未注册工具则为每个调用返回说明性 ToolMessage。"""

        if self.tool_executor is not None:
            return self._execute_with_project_executor(state)

        if self.tool_node is not None:
            result = self.tool_node.invoke(state)
            trace = {
                "node": "action",
                "event": "tools_executed",
                "tool_count": len(self.tools),
                "human_readable": f"通过 LangGraph ToolNode 执行了 {len(self.tools)} 个工具。",
            }
            return {**result, "trace": [trace]}

        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        tool_names = [tc.get("name", "") for tc in tool_calls]
        messages = [
            ToolMessage(
                content=f"工具 {tool_call.get('name', '')} 未注册,无法执行。",
                tool_call_id=tool_call["id"],
            )
            for tool_call in tool_calls
            if "id" in tool_call
        ]
        return {
            "messages": messages,
            "trace": [
                {
                    "node": "action",
                    "event": "no_tools_registered",
                    "requested_tool_count": len(tool_calls),
                    "human_readable": f"模型尝试调用工具（{', '.join(tool_names)}），但工具未注册，无法执行。",
                }
            ],
        }

    def _execute_with_project_executor(self, state: AgentState) -> dict[str, Any]:
        """
        使用项目工具执行器处理 tool_calls。

        state: 当前 LangGraph 状态,最后一条消息应为包含 tool_calls 的 AIMessage。
        """

        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        raw_bound_tool_names = state.get("bound_tool_names")
        bound_tool_names = (
            {str(name) for name in raw_bound_tool_names}
            if isinstance(raw_bound_tool_names, list)
            else None
        )
        max_tool_calls = self.config.limits.agent_max_tool_calls_per_turn
        deferred_tool_calls = tool_calls[max_tool_calls:]
        tool_calls = tool_calls[:max_tool_calls]
        messages: list[ToolMessage] = []
        traces: list[dict[str, Any]] = []
        trace_callback = get_tool_trace_callback()
        task_list_updated = False
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
                continue
            tool_name = tool_call.get("name", "")
            display_name = self._lookup_display_name(tool_name)
            arguments = tool_call.get("args", {})
            if not isinstance(arguments, dict):
                arguments = {}
            args_summary = self._summarize_args(arguments)
            terminal_command = self._build_terminal_command(arguments) if tool_name == "run_terminal_command" else ""
            start_trace = {
                "node": "action",
                "event": "tool_call_start",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "display_name": display_name,
                "tool_args_summary": args_summary,
                "tool_args": arguments,
                "human_readable": f"正在调用工具「{display_name}」。",
                # Stream the preview immediately so the UI can render the running tool row.
                "chat_visible": True,
            }
            if terminal_command:
                start_trace["terminal_command"] = terminal_command
            if tool_name == "patch_knowledge_file":
                start_trace["patch"] = {
                    "path": str(arguments.get("path") or ""),
                    "before": str(arguments.get("old_text") or ""),
                    "after": str(arguments.get("new_text") or ""),
                    "complete": False,
                }
            traces.append(start_trace)
            if trace_callback is not None:
                trace_callback(start_trace)
            before_citations = get_tool_citation_map()
            started_at = time.perf_counter()
            runtime = None
            failed = False
            try:
                from agent_service.tools.definitions import MEMORY_TOOL_NAMES
                from agent_service.tools.runtime_context import get_tool_runtime

                try:
                    runtime = get_tool_runtime()
                except RuntimeError:
                    runtime = None
                if runtime is not None and tool_name == "patch_knowledge_file":
                    runtime.latest_file_patch = None
                disabled_names = set()
                if runtime is not None and runtime.settings_service is not None:
                    disabled_names = set(
                        runtime.settings_service.get_disabled_tools(user_id=runtime.user_id)
                    )
                if bound_tool_names is not None and tool_name not in bound_tool_names:
                    content = f"工具 {tool_name} 未绑定到本轮模型请求，已拒绝执行。"
                    failed = True
                elif tool_name in disabled_names:
                    content = f"工具 {tool_name} 已在用户设置中禁用，已拒绝执行。"
                    failed = True
                elif runtime is not None and tool_name in MEMORY_TOOL_NAMES and not runtime.long_term_memory_enabled:
                    content = "长期记忆功能已关闭,当前工具不可用。"
                    failed = True
                else:
                    content = self.tool_executor.execute(tool_name, arguments)
            except Exception as exc:
                content = f"工具 {tool_name} 执行失败: {exc}"
                failed = True
            if tool_name in TASK_LIST_TOOL_NAMES:
                task_list_updated = True
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            after_citations = get_tool_citation_map()
            new_citations = {
                key: value
                for key, value in after_citations.items()
                if key not in before_citations
            }
            tool_result = build_tool_result_envelope(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=content,
                failed=failed,
            ).to_dict()
            messages.append(ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                name=tool_name,
                additional_kwargs={"tool_result": tool_result},
            ))
            result_count = self._count_results(content)
            completion_text = (
                f"工具「{display_name}」未执行：{content}"
                if failed
                else (
                    f"工具「{display_name}」已完成，共 {result_count} 条结果。"
                    if result_count is not None
                    else f"工具「{display_name}」已完成。"
                )
            )
            end_trace = {
                "node": "action",
                "event": "tool_call_end",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "display_name": display_name,
                "tool_args_summary": args_summary,
                "tool_args": arguments,
                "raw_content": content,
                "tool_result": tool_result,
                "duration_ms": duration_ms,
                "human_readable": completion_text,
                "result_count": result_count,
                "chat_visible": True,
            }
            if terminal_command:
                end_trace["terminal_command"] = terminal_command
            if tool_name == "patch_knowledge_file":
                end_trace["patch"] = runtime.latest_file_patch if runtime and runtime.latest_file_patch else start_trace["patch"]
                if runtime and runtime.change_service is not None:
                    snapshot = runtime.change_service.current_for_run(run_id=runtime.run_id)
                    if snapshot is not None:
                        end_trace["change_snapshot"] = snapshot
            if new_citations:
                end_trace["citation_map"] = new_citations
            traces.append(end_trace)
            if trace_callback is not None:
                trace_callback(end_trace)
        for tool_call in deferred_tool_calls:
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
                continue
            tool_name = tool_call.get("name", "")
            display_name = self._lookup_display_name(tool_name)
            content = (
                f"工具 {display_name} 本轮暂未执行: 单轮最多执行 {max_tool_calls} 个工具调用, "
                "请根据已获得结果决定是否继续读取剩余文件。"
            )
            messages.append(ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name))
            deferred_trace = {
                "node": "action",
                "event": "tool_call_deferred",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "display_name": display_name,
                "duration_ms": 0,
                "human_readable": content,
                "chat_visible": True,
            }
            traces.append(deferred_trace)
            if trace_callback is not None:
                trace_callback(deferred_trace)
        result: dict[str, Any] = {"messages": messages, "trace": traces}
        if task_list_updated:
            try:
                runtime = get_tool_runtime()
                if runtime.task_list_service is not None:
                    result["task_list"] = runtime.task_list_service.get_task_list(runtime.session_id)
            except RuntimeError:
                pass
        return result

    def _lookup_display_name(self, tool_name: str) -> str:
        """从工具执行器的注册表中查找工具的 display_name，找不到则回退到 tool_name。"""
        if self.tool_executor is not None:
            definition = self.tool_executor.registry.get(tool_name)
            if definition is not None and definition.display_name:
                return definition.display_name
        return tool_name

    def _summarize_args(self, arguments: dict[str, Any]) -> str:
        """将工具参数转为简短可读摘要，单行截断。"""

        parts: list[str] = []
        for k, v in arguments.items():
            v_str = str(v)
            preview_chars = self.config.limits.agent_tool_argument_preview_chars
            if len(v_str) > preview_chars:
                v_str = v_str[:preview_chars] + "…"
            parts.append(f"{k}={v_str}")
        summary = ", ".join(parts) if parts else "无参数"
        return summary[:self.config.limits.agent_tool_summary_chars]

    @classmethod
    def _build_terminal_command(cls, arguments: dict[str, Any]) -> str:
        """从终端工具结构化 segments 中拼接完整命令串。"""

        raw_segments = arguments.get("segments")
        if not isinstance(raw_segments, list):
            return ""
        commands: list[str] = []
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue
            program = str(segment.get("program") or segment.get("command") or "").strip()
            raw_args = segment.get("args") or []
            if not program or not isinstance(raw_args, list):
                continue
            args = [cls._quote_terminal_arg(str(arg)) for arg in raw_args]
            commands.append(" ".join([cls._quote_terminal_arg(program), *args]).strip())
        return " && ".join(command for command in commands if command)

    @staticmethod
    def _quote_terminal_arg(value: str) -> str:
        """为展示用途保留可读命令参数,含空白时加双引号。"""

        normalized = value.replace('"', '\\"')
        if normalized == "" or any(ch.isspace() for ch in normalized):
            return f'"{normalized}"'
        return normalized

    @staticmethod
    def _count_results(content: str) -> int | None:
        """从工具输出中统计条目数,供前端展示"检索到 X 条知识"等。"""
        text = str(content).strip()
        if not text:
            return None
        empty_markers = ("未找到", "没有找到", "无相关", "no result", "not found")
        if any(marker in text.lower() for marker in empty_markers):
            return None

        lines = str(content).strip().split("\n")
        count = 0
        citation_ids: set[str] = set()
        file_like_count = 0
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(("[FILE]", "[DIR]")):
                file_like_count += 1
                continue
            # 匹配 "1. " "2. " 等编号行
            if stripped and stripped[0].isdigit():
                dot_pos = stripped.find(". ")
                if dot_pos > 0 and stripped[:dot_pos].isdigit():
                    count += 1
                    continue
            if stripped.startswith("[") and "]" in stripped:
                citation_ids.add(stripped[1:stripped.find("]")])
                continue
            if any(suffix in stripped.lower() for suffix in (".md", ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv")):
                file_like_count += 1
        return count or len(citation_ids) or file_like_count or None
