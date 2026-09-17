"""
模型决策节点。

功能说明:
本文件只实现 `ModelDecisionNode` 一个节点。该节点负责调用 OpenAI Compatible
聊天模型,根据当前 `AgentState.messages` 决定直接回复用户还是发起工具调用。

使用说明:
`graph.py` 会把本节点注册为 `agent` 节点。节点接收 `AgentConfig` 和工具列表,
使用 `config.model` 中的模型名称、API Key、Base URL、温度和超时时间初始化模型。
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent_service.agent_core.nodes.base import AgentState
from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.core.context_budget import capacity_overrides_from_mapping
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.services.scheduler import FOREGROUND_AGENT_TASK, LLMTaskScheduler, get_llm_task_scheduler
from agent_service.tools import ToolExecutor
from agent_service.tools.runtime_context import (
    get_agent_thinking_callback,
    get_agent_token_callback,
    get_context_mirror_callback,
    get_tool_trace_callback,
)

logger = logging.getLogger(__name__)


def get_user_llm_overrides(
    state: AgentState,
    settings_service: Any = None,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """从 SettingsService 读取用户的 LLM 配置。

    返回 `(api_key, base_url, model_name, small_api_key, small_base_url, small_model_name)`。
    小模型字段为空时继承大模型字段。
    """

    user_id = state.get("user_id")
    if not user_id:
        logger.warning("get_user_llm_overrides: state has no user_id")
        return None, None, None, None, None, None

    llm_config = state.get("llm_config")
    if llm_config:
        api_key = _normalize_optional_str(llm_config.get("api_key"))
        base_url = _normalize_optional_str(llm_config.get("base_url"))
        model_name = _normalize_optional_str(llm_config.get("model_name"))
        small_api_key = _normalize_optional_str(llm_config.get("small_api_key")) or api_key
        small_base_url = _normalize_optional_str(llm_config.get("small_base_url")) or base_url
        small_model_name = _normalize_optional_str(llm_config.get("small_model_name")) or model_name
        logger.info(
            "get_user_llm_overrides: user=%s from state has_api_key=True api_key_len=%d",
            user_id,
            len(api_key or ""),
        )
        return (
            api_key,
            base_url,
            model_name,
            small_api_key,
            small_base_url,
            small_model_name,
        )

    if settings_service is None:
        logger.warning("get_user_llm_overrides: settings_service is None")
        return None, None, None, None, None, None
    try:
        config = settings_service.get_llm_config(user_id=user_id)
        api_key = _normalize_optional_str(config.get("api_key"))
        base_url = _normalize_optional_str(config.get("base_url"))
        model_name = _normalize_optional_str(config.get("model_name"))
        small_api_key = _normalize_optional_str(config.get("small_api_key")) or api_key
        small_base_url = _normalize_optional_str(config.get("small_base_url")) or base_url
        small_model_name = _normalize_optional_str(config.get("small_model_name")) or model_name
        logger.info(
            "get_user_llm_overrides: user=%s from db has_api_key=%s api_key_len=%d",
            user_id,
            bool(api_key),
            len(api_key or ""),
        )
        return (
            api_key,
            base_url,
            model_name,
            small_api_key,
            small_base_url,
            small_model_name,
        )
    except Exception as exc:
        logger.error("get_user_llm_overrides: exception user=%s err=%s", user_id, exc)
        return None, None, None, None, None, None


def _normalize_optional_str(value: Any) -> str | None:
    """把设置项中的空字符串归一为 None,避免空 small key 覆盖可用的大模型 key。"""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_user_model_capacity_overrides(
    state: AgentState,
    *,
    model_tier: str,
) -> tuple[int | None, int | None]:
    """读取当前用户对主模型或小模型显式保存的容量覆盖。"""

    return capacity_overrides_from_mapping(state.get("llm_config"), model_tier=model_tier)


def extract_token_usage(message: Any) -> dict[str, int]:
    """从 LangChain message 中标准化提取模型真实 token 用量。"""

    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {}) if isinstance(response_metadata, dict) else {}
    candidates = [usage, token_usage]

    def read_int(*keys: str) -> int:
        for source in candidates:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if isinstance(value, int | float):
                    return int(value)
        return 0

    input_tokens = read_int("input_tokens", "prompt_tokens")
    output_tokens = read_int("output_tokens", "completion_tokens")
    total_tokens = read_int("total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    if input_tokens <= 0 and output_tokens <= 0 and total_tokens > 0:
        input_tokens = total_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


class ModelDecisionNode:
    """
    调用大模型进行 Agent 决策的 LangGraph 节点。

    config: 全局配置对象,从 `AgentCore(config=...)` 显式传入。
    tools: 可供模型调用的 LangChain 工具列表;为空时模型只会进行普通对话。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        tools: Sequence[Any] | None = None,
        task_scheduler: LLMTaskScheduler | None = None,
        tool_executor: ToolExecutor | None = None,
        settings_service: Any = None,
    ) -> None:
        """初始化聊天模型,并在存在工具时绑定工具。"""

        self.config = config
        self.tools = list(tools or [])
        self.tool_names = [str(tool.name) for tool in self.tools if getattr(tool, "name", None)]
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(config)
        self.tool_executor = tool_executor
        self.settings_service = settings_service
        # 模型不在 __init__ 时创建，由调用方按需通过 self.task_scheduler 获取。
        # 用户可自行在客户端设置中配置 API Key，启动时无需强制提供。

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """读取当前消息状态,调用模型,并把模型响应追加回 `messages`。"""

        user_id = state.get("user_id")

        # 从 state 或数据库读取已关闭的工具列表
        active_tool_names: list[str] = list(self.tool_names)
        _disabled_tools_state = state.get("disabled_tools")
        if isinstance(_disabled_tools_state, list):
            disabled_set = set(str(t) for t in _disabled_tools_state)
            active_tool_names = [t for t in active_tool_names if t not in disabled_set]
        elif user_id:
            try:
                if self.settings_service is not None:
                    disabled_tools = self.settings_service.get_disabled_tools(user_id=user_id)
                    disabled_set = set(disabled_tools)
                    active_tool_names = [t for t in active_tool_names if t not in disabled_set]
            except Exception:
                pass

        if not state.get("long_term_memory_enabled", True):
            from agent_service.tools.definitions import MEMORY_TOOL_NAMES

            active_tool_names = [name for name in active_tool_names if name not in MEMORY_TOOL_NAMES]

        if self._current_turn_tool_call_count(state.get("messages", [])) >= self.config.limits.agent_max_tool_calls_per_turn:
            # 单轮累计预算耗尽后解绑工具，让模型基于已有结果生成最终回答，避免
            # 同一个空结果被无限重试并持续写入历史。
            active_tool_names = []

        # 每轮全量绑定所有可用工具(已剔除禁用工具),保证任意工具随时可直接调用。
        system_content = self.config.prompts.agent_system_prompt

        # 追加用户自定义系统提示词(数据库持久化,每次对话自动加载)
        if user_id:
            try:
                if self.settings_service is not None:
                    system_content += self.config.prompts.resolve_child_agent_type_prompt(
                        dsh_enabled=self.settings_service.is_dsh_coding_agent_enabled_for_user(
                            user_id=user_id,
                        ),
                    )
                    custom_prompt = self.settings_service.get_system_prompt(user_id=user_id)
                    if custom_prompt:
                        system_content += f"\n\n【用户自定义指令】\n{custom_prompt}"
            except Exception:
                pass  # 获取用户设置失败时不阻断流程

        plan = state.get("plan")
        if plan and plan.get("hint"):
            covered = plan.get("covered", [])
            suggested = plan.get("suggested", [])
            sub_questions = plan.get("sub_questions", [])
            current_index = int(plan.get("current_index", 0) or 0)
            current_question = ""
            if isinstance(sub_questions, list) and sub_questions:
                current_index = max(0, min(current_index, len(sub_questions) - 1))
                current_question = str(sub_questions[current_index])
            sufficient = plan.get("sufficient", False)
            plan_status = plan.get("status", "running")
            status = "信息已充足，可以结束探索" if sufficient else "信息尚不充分，需继续探索"
            system_content += (
                f"\n\n【探索状态 — 仅供参考，你自行决定下一步】\n"
                f"计划状态: {plan_status}\n"
                f"当前子问题: {current_question or '暂无'}\n"
                f"子问题队列: {' | '.join(str(item) for item in sub_questions) if sub_questions else '暂无'}\n"
                f"已覆盖: {', '.join(covered) if covered else '暂无'}\n"
                f"建议方向: {', '.join(suggested) if suggested else '暂无'}\n"
                f"当前判断: {status}\n"
                f"策略提示: {plan['hint']}"
            )

        task_list_prompt = self._build_task_list_prompt(state.get("task_list"))
        if task_list_prompt:
            system_content += task_list_prompt

        skill_prompt = self._build_skill_prompt(state.get("skill_index"), state.get("active_skills"))
        if skill_prompt:
            system_content += skill_prompt

        system_message = SystemMessage(content=system_content)
        token_callback = get_agent_token_callback()

        if token_callback is not None:
            return self._streaming_call(
                system_message=system_message,
                state=state,
                token_callback=token_callback,
                active_tool_names=active_tool_names,
            )

        (
            user_api_key,
            user_base_url,
            user_model_name,
            user_small_api_key,
            user_small_base_url,
            user_small_model_name,
        ) = self._get_user_model_overrides(state)
        context_window_tokens, max_output_tokens = get_user_model_capacity_overrides(
            state,
            model_tier="large",
        )
        llm_messages = self._prepare_messages_for_llm(
            system_message,
            state["messages"],
            limits=self.config.limits,
        )
        context_callback = get_context_mirror_callback()
        if context_callback is not None:
            context_callback(self.task_scheduler.build_observability_snapshot(
                messages=llm_messages,
                tool_names=active_tool_names,
                api_key=user_api_key,
                base_url=user_base_url,
                model_name=user_model_name,
                small_api_key=user_small_api_key,
                small_base_url=user_small_base_url,
                small_model_name=user_small_model_name,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
                node="agent",
            ))
        response = self.task_scheduler.invoke_chat(
            task_type=FOREGROUND_AGENT_TASK,
            messages=llm_messages,
            tool_names=active_tool_names,
            api_key=user_api_key,
            base_url=user_base_url,
            model_name=user_model_name,
            small_api_key=user_small_api_key,
            small_base_url=user_small_base_url,
            small_model_name=user_small_model_name,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        )
        tool_calls = getattr(response, "tool_calls", []) or []
        token_usage = extract_token_usage(response)
        return {
            "messages": [response],
            "bound_tool_names": active_tool_names,
            "trace": [
                {
                    "node": "agent",
                    "event": "model_response",
                    "tool_call_count": len(tool_calls),
                    "has_content": bool(response.content),
                    "token_usage": token_usage,
                    "human_readable": self._make_agent_readable(tool_calls, bool(response.content)),
                    "chat_visible": False,
                }
            ],
        }

    @staticmethod
    def _current_turn_tool_call_count(messages: Sequence[BaseMessage]) -> int:
        """统计最近一条用户消息之后已经产生的工具调用数量。"""

        current_turn: Sequence[BaseMessage] = messages
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                current_turn = messages[index + 1:]
                break
        return sum(
            len(getattr(message, "tool_calls", []) or [])
            for message in current_turn
            if isinstance(message, AIMessage)
        )

    @staticmethod
    def _build_task_list_prompt(task_list: dict[str, Any] | None) -> str:
        """Build the system prompt section for an active session task list."""

        if not isinstance(task_list, dict):
            return ""
        items = task_list.get("items")
        if not isinstance(items, list) or not items:
            return ""
        status = str(task_list.get("status") or "active")
        current_item_id = task_list.get("current_item_id")
        lines = [
            "",
            "",
            "[Session task list]",
            f"Status: {status}",
            f"Title: {task_list.get('title') or 'Task list'}",
            "Your later work in this session must continue this task list until finish_task_list is called.",
            "Right after you actually complete each item, immediately call complete_task_list_item with that item id and a factual completion_summary, before starting the next item.",
            "Items may be completed in any order. When no useful items remain, call finish_task_list.",
        ]
        for item in items:
            if not isinstance(item, dict):
                continue
            marker = "current" if item.get("id") == current_item_id else str(item.get("status") or "pending")
            lines.append(f"- {item.get('id')}: [{marker}] {item.get('title')}")
            summary = str(item.get("completion_summary") or "").strip()
            if summary:
                lines.append(f"  completion_summary: {summary}")
        return "\n".join(lines)

    @staticmethod
    def _build_skill_prompt(
        skill_index: list[dict[str, Any]] | None,
        active_skills: list[dict[str, Any]] | None,
    ) -> str:
        """Build the system prompt section for indexed and routed skills."""

        enabled = skill_index if isinstance(skill_index, list) else []
        selected = active_skills if isinstance(active_skills, list) else []
        if skill_index is None and active_skills is None:
            return ""
        if not enabled and not selected:
            return (
                "\n\n"
                "[Skill routing]\n"
                "Skill registry is available, but no candidate skill matched this turn. "
                "If the user request clearly needs a reusable capability package, call list_skills first, then use_skill with the selected skill id."
            )
        lines = [
            "",
            "",
            "[Candidate skills]",
            "Skills are reusable capability packages. This section only lists skills matched to the current user request.",
            "If a candidate skill may help but its body is not included below, call use_skill to load that SKILL.md body before applying it.",
        ]
        for skill in enabled:
            if not isinstance(skill, dict):
                continue
            lines.append(
                f"- {skill.get('skill_id')}: {skill.get('name')} "
                f"({skill.get('source')}): {skill.get('description') or ''}"
            )
        if selected:
            lines.extend([
                "",
                "[Routed skills for this turn]",
                "The following SKILL.md bodies apply only to the current user turn.",
            ])
        for skill in selected:
            if not isinstance(skill, dict):
                continue
            lines.append(f"\n--- Skill: {skill.get('name')} [{skill.get('skill_id')}] ---")
            lines.append(str(skill.get("body") or ""))
            lines.append("--- End Skill ---")
        return "\n".join(lines)

    def _streaming_call(
        self,
        *,
        system_message: SystemMessage,
        state: AgentState,
        token_callback: Any,
        active_tool_names: list[str],
    ) -> dict[str, Any]:
        """
        流式调用模型,逐 token 通过 callback 推送,最终返回完整消息。

        system_message: 系统提示消息。
        state: 当前 AgentState。
        token_callback: 接收累积文本内容的回调。
        active_tool_names: 当前可用的工具名称列表。
        """

        cumulative = ""
        cumulative_reasoning = ""
        final_message: Any = None

        context_callback = get_context_mirror_callback()
        trace_callback = get_tool_trace_callback()
        llm_messages = self._prepare_messages_for_llm(
            system_message,
            state["messages"],
            limits=self.config.limits,
        )
        (
            user_api_key,
            user_base_url,
            user_model_name,
            user_small_api_key,
            user_small_base_url,
            user_small_model_name,
        ) = self._get_user_model_overrides(state)
        context_window_tokens, max_output_tokens = get_user_model_capacity_overrides(
            state,
            model_tier="large",
        )
        if context_callback is not None:
            context_callback(self.task_scheduler.build_observability_snapshot(
                messages=llm_messages,
                tool_names=active_tool_names,
                api_key=user_api_key,
                base_url=user_base_url,
                model_name=user_model_name,
                small_api_key=user_small_api_key,
                small_base_url=user_small_base_url,
                small_model_name=user_small_model_name,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
                node="agent",
            ))
        if trace_callback is not None:
            trace_callback({
                "node": "agent",
                "event": "model_request_start",
                "human_readable": "模型正在决策下一步。",
                "chat_visible": False,
            })

        # Each tool round starts a fresh cumulative model response. Reset the
        # outer stream's delta baseline before the first token of this call.
        token_callback("")
        thinking_callback = get_agent_thinking_callback()
        if thinking_callback is not None:
            # 与正文同理:每轮工具循环重置思考基线,避免下一轮思考被上一轮累计文本
            # 挡住增量(前向切片依赖前缀,基线必须从本轮重新开始)。
            thinking_callback("")

        for chunk in self.task_scheduler.stream_chat(
            task_type=FOREGROUND_AGENT_TASK,
            messages=llm_messages,
            tool_names=active_tool_names,
            api_key=user_api_key,
            base_url=user_base_url,
            model_name=user_model_name,
            small_api_key=user_small_api_key,
            small_base_url=user_small_base_url,
            small_model_name=user_small_model_name,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        ):
            is_complete = chunk.get("status") == "complete"
            if not is_complete:
                # 思考文本(reasoning_content)与正文分开累积:思考走独立回调,
                # 上层据此流式渲染 Think 条,正文仍走 token_callback。
                reasoning_delta = chunk.get("reasoning_delta", "")
                if reasoning_delta:
                    cumulative_reasoning += reasoning_delta
                    thinking_callback = get_agent_thinking_callback()
                    if thinking_callback is not None:
                        thinking_callback(cumulative_reasoning)
                delta = chunk.get("content_delta", "")
                if delta:
                    cumulative += delta
                    token_callback(cumulative)
            if is_complete:
                final_message = chunk.get("message")
        if final_message is None:
            from langchain_core.messages import AIMessage
            final_message = AIMessage(content=cumulative)
        tool_calls = getattr(final_message, "tool_calls", []) or []
        has_content = bool(getattr(final_message, "content", None))
        token_usage = extract_token_usage(final_message)
        return {
            "messages": [final_message],
            "bound_tool_names": active_tool_names,
            "trace": [
                {
                    "node": "agent",
                    "event": "model_response",
                    "tool_call_count": len(tool_calls),
                    "has_content": has_content,
                    "token_usage": token_usage,
                    "human_readable": self._make_agent_readable(tool_calls, has_content),
                    "chat_visible": False,
                }
            ],
        }

    def _make_agent_readable(self, tool_calls: list, has_content: bool) -> str:
        """根据模型决策生成人类可读的思考描述。"""

        if tool_calls:
            names = ", ".join(
                self._lookup_display_name(tc.get("name", "")) for tc in tool_calls if tc.get("name")
            )
            return f"模型决定调用工具：{names}"
        if has_content:
            return "模型生成最终回复。"
        return "模型返回空响应。"

    def _lookup_display_name(self, tool_name: str) -> str:
        """从工具执行器的注册表中查找工具的 display_name，找不到则回退到 tool_name。"""
        if self.tool_executor is not None:
            definition = self.tool_executor.registry.get(tool_name)
            if definition is not None and definition.display_name:
                return definition.display_name
        return tool_name

    @staticmethod
    def _prepare_messages_for_llm(
        system_message: SystemMessage,
        messages: list[BaseMessage],
        *,
        limits: AgentConfig.BusinessLimitsConfig = DEFAULT_BUSINESS_LIMITS,
    ) -> list[BaseMessage]:
        """
        压缩工具返回内容后再送入模型,避免文件/搜索结果撑爆上下文。

        保留本轮内所有消息以保证 tool_call → tool_message 顺序完整；
        最终模型可见表示由调度器统一按 ContextBudget 组装。
        """

        # 图循环中的消息可能经过压缩或恢复；在真正发给模型前再次保证
        # 每条 ToolMessage 都有对应且位于其前方的 assistant tool_call。
        del limits
        filtered = ContextBuilder._filter_orphaned_tool_messages(list(messages))
        return [system_message, *filtered]

    def _get_user_model_overrides(
        self,
        state: AgentState,
    ) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
        """从 SettingsService 读取用户的 LLM 配置。"""

        return get_user_llm_overrides(state, self.settings_service)

    @staticmethod
    def _serialize_messages(messages: list) -> list[dict[str, Any]]:
        """
        将 LangChain BaseMessage 列表序列化为 JSON 友好的 dict 列表。

        用于上下文镜像回调, 让前端 Obs 面板能看到模型收到的完整消息。
        """
        role_map = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
        result: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {
                "role": role_map.get(msg.type, msg.type),
                "content": str(getattr(msg, "content", "") or ""),
            }
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = tool_calls
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            name = getattr(msg, "name", None)
            if name:
                entry["name"] = name
            result.append(entry)
        return result

    def _build_model(self) -> Any:
        """根据 `AgentConfig.ModelConfig` 创建 OpenAI Compatible 聊天模型。

        注意: 此方法创建的模型实例仅保留向后兼容，实际 LLM 调用由
        self.task_scheduler（LLMTaskScheduler）统一管理。用户可在客户端
        设置中配置 API Key，启动时无需强制提供。
        """

        if not self.config.model.model_name:
            raise ValueError("config.model.model_name 不能为空。")

        model_kwargs = AgentConfig.ModelConfig.get_model_kwargs(self.config.model.model_name)
        model = ChatOpenAI(
            model=self.config.model.model_name,
            api_key=self.config.model.api_key,
            base_url=self.config.model.base_url,
            temperature=self.config.model.resolve_primary_temperature(),
            timeout=self.config.model.timeout_seconds,
            **model_kwargs,
        )
        if self.tools:
            return model.bind_tools(self.tools)
        return model
