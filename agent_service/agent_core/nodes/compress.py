"""
上下文压缩节点。

功能说明:
本文件只实现 `CompressNode` 一个节点。该节点会在每次进入模型决策前检查当前
工作消息是否已经接近上下文 token 配额上限。如果超过阈值,节点会:

1. 使用小模型生成“重要事实摘要”。
2. 把该摘要写入统一长期记忆表。
3. 将当前工作消息替换为“压缩摘要 + 最近少量消息”,然后把控制流交回 `agent` 节点。

使用说明:
`graph.py` 会把本节点放在 `agent` 前面,因此它既能覆盖对话入口,也能覆盖
`action -> agent` 的回路。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_service.agent_core.nodes.base import AgentState
from agent_service.core.agent_config import AgentConfig
from agent_service.core.context_budget import ContextBudget, ModelCapacity
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.services.memory.important_fact_summary_service import ImportantFactSummaryService
from agent_service.services.scheduler import FOREGROUND_AGENT_TASK, LLMTaskScheduler, get_llm_task_scheduler
from agent_service.tools.runtime_context import get_context_compression_callback


logger = logging.getLogger(__name__)
_MEMORY_WRITE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="context-memory")


class CompressNode:
    """
    上下文压缩节点。

    config: 全局配置对象。
    task_scheduler: 统一调度器,用于将压缩摘要路由到小模型池。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        task_scheduler: LLMTaskScheduler | None = None,
        summary_service: ImportantFactSummaryService | None = None,
    ) -> None:
        """初始化压缩节点依赖。"""

        self.config = config
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(config)
        self.summary_service = summary_service or ImportantFactSummaryService(
            config=config,
            task_scheduler=self.task_scheduler,
        )

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """
        在模型决策前检查是否需要压缩上下文。

        state: 当前 LangGraph 运行状态。
        """

        llm_config = state.get("llm_config") or {}
        model_name = str(llm_config.get("model_name") or self.config.model.model_name or "") or None
        capacity = ModelCapacity.resolve(
            config=self.config,
            model_name=model_name or "",
            model_tier="large",
            context_window_tokens=int(llm_config.get("model_context_window_tokens") or 0) or None,
            max_output_tokens=int(llm_config.get("model_max_output_tokens") or 0) or None,
        )
        fixed_request_tokens = int(state.get("context_overhead_tokens", 0) or 0) + int(
            state.get("context_tool_tokens", 0) or 0
        )
        estimated_tokens = (
            ContextBuilder.estimate_messages_tokens(state["messages"], model_name=model_name)
            + fixed_request_tokens
        )
        available_tokens, trigger_tokens, target_tokens = ContextBuilder.compression_limits(
            self.config,
            capacity,
        )
        display_window_tokens = ContextBudget.from_config(
            config=self.config,
            capacity=capacity,
        ).effective_window_tokens
        if estimated_tokens < trigger_tokens:
            return {
                "trace": [
                    {
                        "node": "compress",
                        "event": "compression_skipped",
                        "estimated_tokens": estimated_tokens,
                        "trigger_tokens": trigger_tokens,
                        "human_readable": f"当前上下文 {estimated_tokens} tokens，未超过阈值，无需压缩。",
                    }
                ]
            }
        previous_state = state.get("compression_state") or {}
        transcript = self._build_transcript(state["messages"], previous_state=previous_state)
        self._emit_event(
            {
                "event": "compression_started",
                "tokens_before": estimated_tokens,
                "max_context_tokens": display_window_tokens,
                "trigger_tokens": trigger_tokens,
                "target_tokens": target_tokens,
                "version": int(previous_state.get("version", 0) or 0) + 1,
            }
        )
        try:
            summary_text = self.summary_service.summarize_text(
                transcript=transcript,
                task_type=FOREGROUND_AGENT_TASK,
                mode="compress",
                llm_config=state.get("llm_config"),
            )
        except Exception as exc:
            logger.exception("同步上下文压缩失败 | session=%s", state.get("session_id"))
            return self._build_failure_result(
                state=state,
                reason=type(exc).__name__,
                tokens_before=estimated_tokens,
                available_tokens=available_tokens,
                display_window_tokens=display_window_tokens,
                trigger_tokens=trigger_tokens,
                target_tokens=target_tokens,
                model_name=model_name,
            )
        if not summary_text:
            return self._build_failure_result(
                state=state,
                reason="empty_summary",
                tokens_before=estimated_tokens,
                available_tokens=available_tokens,
                display_window_tokens=display_window_tokens,
                trigger_tokens=trigger_tokens,
                target_tokens=target_tokens,
                model_name=model_name,
            )
        cancel_event = state.get("cancel_event")
        if cancel_event is not None and cancel_event.is_set():
            cancelled = {
                "event": "compression_cancelled",
                "tokens_before": estimated_tokens,
                "max_context_tokens": display_window_tokens,
            }
            self._emit_event(cancelled)
            return {
                "trace": [
                    {
                        "node": "compress",
                        **cancelled,
                        "human_readable": "上下文压缩已取消，原工作上下文保持不变。",
                    }
                ]
            }
        source_hash = self.summary_service.build_hash(
            state["session_id"],
            state["user_id"],
            transcript,
        )
        compression_state = self._parse_compression_state(
            summary_text,
            previous_state=previous_state,
            source_message_count=len(state["messages"]),
        )
        persisted_summary = ContextBuilder.compression_state_to_text(compression_state)
        if state.get("long_term_memory_enabled", True):
            _MEMORY_WRITE_EXECUTOR.submit(
                self._persist_memory_safely,
                user_id=state["user_id"],
                session_id=state["session_id"],
                summary_text=persisted_summary,
                memory_type=self.config.constants.important_fact_summary_memory_type,
                source_type="context_compression",
                source_id=state["session_id"],
                source_hash=source_hash,
                source_range_json={
                    "mode": "compress",
                    "message_count": len(state["messages"]),
                    "start_index": 0,
                    "end_index": max(len(state["messages"]) - 1, 0),
                },
                metadata_json={"estimated_tokens": estimated_tokens, "version": compression_state["version"]},
                importance=0.95,
                authority=0.6,
            )
        compressed_messages = self._build_compressed_messages(
            original_messages=state["messages"],
            compression_state=compression_state,
            target_tokens=max(target_tokens - fixed_request_tokens, 1),
            model_name=model_name,
        )
        tokens_after = (
            ContextBuilder.estimate_messages_tokens(compressed_messages, model_name=model_name)
            + fixed_request_tokens
        )
        retained_message_count = sum(not isinstance(message, SystemMessage) for message in compressed_messages)
        applied = {
            "event": "compression_applied",
            "tokens_before": estimated_tokens,
            "tokens_after": tokens_after,
            "max_context_tokens": display_window_tokens,
            "trigger_tokens": trigger_tokens,
            "target_tokens": target_tokens,
            "version": compression_state["version"],
            "retained_message_count": retained_message_count,
            "source_message_count": len(state["messages"]),
            "retained_message_range": {
                "start_index": max(len(state["messages"]) - retained_message_count, 0),
                "end_index": max(len(state["messages"]) - 1, 0),
            },
        }
        self._emit_event(applied)
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compressed_messages],
            "compression_state": compression_state,
            "trace": [
                {
                    "node": "compress",
                    **applied,
                    "estimated_tokens": estimated_tokens,
                    "compressed_message_count": len(compressed_messages),
                    "human_readable": f"上下文已从 {estimated_tokens} tokens 压缩到 {tokens_after} tokens，并保留结构化事实、动作状态与最近消息。",
                }
            ],
        }

    @staticmethod
    def _build_transcript(messages: list[BaseMessage], *, previous_state: dict[str, Any]) -> str:
        """
        将当前工作消息转换为适合摘要模型消费的文本。

        messages: 当前工作消息列表。
        """

        lines: list[str] = [
            "请输出 JSON 对象，字段必须为 important_facts、historical_actions、unfinished_actions，值均为字符串数组。",
            "根据事实与动作状态对旧摘要执行保留、替换、新增或删除，禁止简单追加重复、冲突或过期内容。",
            "[现有压缩状态]",
            json.dumps(previous_state, ensure_ascii=False, sort_keys=True),
            "[本次工作上下文]",
        ]
        for message in messages:
            content = str(getattr(message, "content", "") or "").strip()
            tool_calls = getattr(message, "tool_calls", []) or []
            if content:
                lines.append(f"{message.type}: {content}")
            if tool_calls:
                lines.append(f"{message.type}_tool_calls: {json.dumps(tool_calls, ensure_ascii=False, sort_keys=True)}")
        return "\n".join(lines)

    @staticmethod
    def _parse_compression_state(
        summary_text: str,
        *,
        previous_state: dict[str, Any],
        source_message_count: int,
    ) -> dict[str, Any]:
        """校验小模型结构化输出并生成单调递增的压缩状态版本。"""

        normalized = summary_text.strip()
        if normalized.startswith("```"):
            normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(normalized)
        except (json.JSONDecodeError, TypeError):
            parsed = {"important_facts": [summary_text], "historical_actions": [], "unfinished_actions": []}
        required_keys = {"important_facts", "historical_actions", "unfinished_actions"}
        if not isinstance(parsed, dict) or not required_keys.issubset(parsed) or any(
            not isinstance(parsed.get(key), list) for key in required_keys
        ):
            parsed = {
                key: list(previous_state.get(key, []))
                for key in required_keys
            }
        state: dict[str, Any] = {
            "version": int(previous_state.get("version", 0) or 0) + 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_message_count": source_message_count,
            "source_range": {"start_index": 0, "end_index": max(source_message_count - 1, 0)},
        }
        for key in ("important_facts", "historical_actions", "unfinished_actions"):
            values = parsed.get(key, []) if isinstance(parsed, dict) else []
            state[key] = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        return state

    def _persist_memory_safely(self, **kwargs: Any) -> None:
        """在后台线程幂等写入长期记忆，失败只记录日志而不影响当前回答。"""

        try:
            self.summary_service.persist_summary_memory(**kwargs)
        except Exception:
            logger.exception("异步写入上下文压缩记忆失败 | session=%s", kwargs.get("session_id"))

    def _build_failure_result(
        self,
        *,
        state: AgentState,
        reason: str,
        tokens_before: int,
        available_tokens: int,
        display_window_tokens: int,
        trigger_tokens: int,
        target_tokens: int,
        model_name: str | None,
    ) -> dict[str, Any]:
        """摘要失败时从原消息原子构造安全滑动窗口，并保留最后一条当前消息。"""

        fixed_request_tokens = int(state.get("context_overhead_tokens", 0) or 0) + int(
            state.get("context_tool_tokens", 0) or 0
        )
        fallback_messages = ContextBuilder.select_recent_messages_within_budget(
            state["messages"],
            token_budget=max(trigger_tokens - fixed_request_tokens - 1, 1),
            model_name=model_name,
        )
        if not fallback_messages and state["messages"]:
            fallback_messages = [state["messages"][-1]]
        tokens_after = (
            ContextBuilder.estimate_messages_tokens(fallback_messages, model_name=model_name)
            + fixed_request_tokens
        )
        failed = {
            "event": "compression_failed",
            "reason": reason,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "max_context_tokens": display_window_tokens,
            "trigger_tokens": trigger_tokens,
            "target_tokens": target_tokens,
        }
        self._emit_event(failed)
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *fallback_messages],
            "trace": [
                {
                    "node": "compress",
                    **failed,
                    "human_readable": "上下文摘要失败，已保留原始记录并原子回退到安全 token 滑动窗口。",
                }
            ],
        }

    @staticmethod
    def _emit_event(payload: dict[str, Any]) -> None:
        """把压缩生命周期事件立即推送给流式调用方。"""

        callback = get_context_compression_callback()
        if callback is not None:
            callback(payload)

    @staticmethod
    def _collect_valid_tail(
        messages: list[BaseMessage],
        tail_count: int,
    ) -> list[BaseMessage]:
        """
        从消息列表末尾往前收集有效的尾部消息。
        跳过孤立的 ToolMessage(其 tool_call_id 对应的 AIMessage 不在尾部),避免 API 400 错误。

        方法:先超量收集候选消息(两倍 tail_count),从中提取 AIMessage 的 tool_call_id,
        再过滤掉孤立的 ToolMessage,最后取末尾 tail_count 条。
        """

        def _tool_call_ids_from_message(msg: BaseMessage) -> set[str]:
            ids: set[str] = set()
            for tc in getattr(msg, "tool_calls", []) or []:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    ids.add(tc_id)
            return ids

        # 从末尾超量收集候选
        buffer: list[BaseMessage] = []
        idx = len(messages) - 1
        while idx >= 0 and len(buffer) < tail_count * 2:
            buffer.append(messages[idx])
            idx -= 1
        buffer.reverse()

        # 从候选中提取已知 tool_call_id
        known_ids: set[str] = set()
        for msg in buffer:
            if isinstance(msg, AIMessage):
                known_ids.update(_tool_call_ids_from_message(msg))

        # 过滤孤立的 ToolMessage
        filtered: list[BaseMessage] = []
        for msg in buffer:
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id and tc_id not in known_ids:
                    continue
            filtered.append(msg)

        return filtered[-tail_count:] if len(filtered) >= tail_count else filtered

    def _build_compressed_messages(
        self,
        *,
        original_messages: list[BaseMessage],
        compression_state: dict[str, Any],
        target_tokens: int,
        model_name: str | None,
    ) -> list[BaseMessage]:
        """
        构建压缩后的工作消息列表。

        original_messages: 压缩前的完整消息列表。
        compression_state: 小模型合并后的结构化压缩状态。
        target_tokens: 压缩后的目标 token 预算。
        model_name: 用于 token 统计的当前模型名。
        """

        summary_message = SystemMessage(
            content=self.config.prompts.compressed_context_template.format(
                summary=ContextBuilder.compression_state_to_text(compression_state)
            )
        )
        protected_system_messages = [
            message
            for message in original_messages
            if isinstance(message, SystemMessage)
            and bool((getattr(message, "additional_kwargs", {}) or {}).get("recall_details"))
        ]
        summary_tokens = ContextBuilder.estimate_messages_tokens(
            [*protected_system_messages, summary_message],
            model_name=model_name,
        )
        recent_messages = ContextBuilder.select_recent_messages_within_budget(
            [message for message in original_messages if message not in protected_system_messages],
            token_budget=max(target_tokens - summary_tokens, 1),
            model_name=model_name,
        )
        if not recent_messages and original_messages:
            recent_messages = [original_messages[-1]]
        return [*protected_system_messages, summary_message, *recent_messages]
