"""
观察节点。

功能说明:
本文件只实现 `ObservationNode` 一个节点。该节点在工具调用执行完毕后,用大模型审视
工具执行结果,判断是否已经获得足够信息回答用户问题,或者还需要继续调用工具。

使用说明:
`graph.py` 会把本节点注册为 `observation` 节点,放在 `action` 之后。
节点输出 `observation_decision` 字段,"continue" 表示继续工具循环,"answer" 表示
可以输出最终答案,路由到摘要节点结束本轮执行。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from agent_service.agent_core.nodes.base import AgentState
from agent_service.agent_core.nodes.model_decision import (
    extract_token_usage,
    get_user_llm_overrides,
    get_user_model_capacity_overrides,
)
from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.core.context_budget import ModelCapacity
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.services.scheduler import (
    FOREGROUND_AGENT_TASK,
    SMALL_MODEL_TIER,
    LLMTaskScheduler,
    get_llm_task_scheduler,
)
from agent_service.tools import ToolExecutor
from agent_service.tools.result_envelope import render_tool_result_context
from agent_service.tools.runtime_context import (
    get_context_mirror_callback,
    get_observation_content_callback,
    get_tool_trace_callback,
)


class ObservationNode:
    """
    观察节点。

    config: 全局配置对象。
    task_scheduler: 可选 LLM 任务调度器,为空时自动创建。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        task_scheduler: LLMTaskScheduler | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """保存配置和调度器。"""

        self.config = config
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(config)
        self.tool_executor = tool_executor

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """
        审视最近一次工具执行结果,决定继续还是回答。

        当 LLM 决定继续时,额外检查上下文 token 是否溢出:
        - 未溢出 → "continue"(直接路由到 planner)
        - 已溢出 → "compress"(先经过 compress 再到 planner)

        state: 当前 LangGraph 状态。
        """

        summary = self._build_observation_context(state)
        if not summary:
            decision = self._check_overflow_then_decide(state, "continue")
            return {
                "messages": [],
                "observation_decision": decision,
                "trace": [{
                    "node": "observation",
                    "event": "no_tool_results_to_review",
                    "decision": decision,
                    "reason": "没有工具结果可审视",
                    "next_action": "继续推进当前任务",
                    "confidence": 0.2,
                    "human_readable": "没有需要审视的工具执行结果，继续推进。",
                    "chat_visible": False,
                }],
            }

        system_prompt = self.config.prompts.observation_system_prompt.format(
            max_reason_chars=self.config.limits.agent_observation_reason_chars,
            max_next_action_chars=self.config.limits.agent_observation_next_action_chars,
        )
        system_message = SystemMessage(content=system_prompt)
        context_message = SystemMessage(content=summary)
        trace_callback = get_tool_trace_callback()
        if trace_callback is not None:
            trace_callback({
                "node": "observation",
                "event": "observation_request_start",
                "human_readable": "正在审视工具结果。",
                "chat_visible": False,
            })
        response = self._call_llm(system_message, context_message, state)
        token_usage = extract_token_usage(response)
        parsed = self._parse_decision(response.content, limits=self.config.limits)
        llm_decision = parsed["decision"]
        decision = self._check_overflow_then_decide(state, llm_decision)
        if decision == "compress":
            parsed["decision"] = "compress"
            parsed["next_action"] = "先压缩上下文，再继续规划。"
        readable = parsed["reason"] or parsed["next_action"] or "观察完成。"
        trace = {
            "node": "observation",
            "event": "observation_complete",
            "decision": decision,
            "reason": parsed["reason"],
            "next_action": parsed["next_action"],
            "confidence": parsed["confidence"],
            "token_usage": token_usage,
            "human_readable": readable,
            "chat_visible": False,
        }
        return {"messages": [], "observation_decision": decision, "trace": [trace]}

    def _call_llm(self, system_message: Any, context_message: Any, state: AgentState) -> Any:
        """调用 LLM,流式场景下通过 callback 逐 token 推送。"""

        api_key, base_url, model_name, small_api_key, small_base_url, small_model_name = get_user_llm_overrides(state)
        context_window_tokens, max_output_tokens = get_user_model_capacity_overrides(
            state,
            model_tier="small",
        )
        messages = [system_message, context_message]
        context_callback = get_context_mirror_callback()
        if context_callback is not None:
            context_callback(self.task_scheduler.build_observability_snapshot(
                messages=messages,
                model_tier=SMALL_MODEL_TIER,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                small_api_key=small_api_key,
                small_base_url=small_base_url,
                small_model_name=small_model_name,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
                node="observation",
            ))
        callback = get_observation_content_callback()
        if callback is not None:
            cumulative = ""
            final_message: Any = None
            for chunk in self.task_scheduler.stream_chat(
                task_type=FOREGROUND_AGENT_TASK,
                messages=messages,
                model_tier=SMALL_MODEL_TIER,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                small_api_key=small_api_key,
                small_base_url=small_base_url,
                small_model_name=small_model_name,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
            ):
                is_complete = chunk.get("status") == "complete"
                if not is_complete:
                    delta = chunk.get("content_delta", "")
                    if delta:
                        cumulative += delta
                        callback(cumulative)
                if is_complete:
                    final_message = chunk.get("message")
            if final_message is None:
                from langchain_core.messages import AIMessage
                final_message = AIMessage(content=cumulative)
            return final_message

        return self.task_scheduler.invoke_chat(
            task_type=FOREGROUND_AGENT_TASK,
            messages=messages,
            model_tier=SMALL_MODEL_TIER,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        )

    def _check_overflow_then_decide(self, state: AgentState, llm_decision: str) -> str:
        """当 LLM 决定 continue 时,检查上下文是否溢出;溢出则返回 compress 迫使进入压缩节点。"""

        llm_config = state.get("llm_config") or {}
        model_name = str(llm_config.get("model_name") or self.config.model.model_name or "") or None
        capacity = ModelCapacity.resolve(
            config=self.config,
            model_name=model_name or "",
            model_tier="large",
            context_window_tokens=int(llm_config.get("model_context_window_tokens") or 0) or None,
            max_output_tokens=int(llm_config.get("model_max_output_tokens") or 0) or None,
        )
        if ContextBuilder.should_compress(
            state.get("messages", []),
            config=self.config,
            model_name=model_name,
            capacity=capacity,
        ):
            return "compress"
        return llm_decision

    def _build_observation_context(self, state: AgentState) -> str:
        """
        从 state 中提取最近一次工具调用的上下文。
        只提取当前 cycle(最近一条人类消息之后)的工具调用和结果,
        避免跨 cycle 污染。
        """

        messages = state.get("messages", [])
        parts: list[str] = []

        # 找到最近一条人类消息的位置,作为当前 cycle 的起点
        human_idx = -1
        for i, message in enumerate(messages):
            if getattr(message, "type", None) == "human":
                human_idx = i

        if human_idx < 0:
            return ""

        parts.append(f"用户问题:\n{messages[human_idx].content}")

        # 只提取当前 cycle(人类消息之后)的工具调用和结果
        tool_calls = []
        tool_results = []
        for message in messages[human_idx + 1:]:
            msg_type = getattr(message, "type", None)
            content = getattr(message, "content", None)
            if msg_type == "ai":
                calls = getattr(message, "tool_calls", []) or []
                for tc in calls:
                    tool_calls.append(tc)
            elif msg_type == "tool" and content:
                tool_results.append(f"  结果: {render_tool_result_context(message)}")

        if tool_calls:
            tc = tool_calls[-1]
            args_str = str(tc.get("args", {}))
            display = self._lookup_display_name(tc.get("name", ""))
            parts.append(f"最近工具调用: {display} ({args_str})")
        if tool_results:
            parts.extend(tool_results)

        if len(parts) <= 1:
            return ""

        return "\n".join(parts)

    def _lookup_display_name(self, tool_name: str) -> str:
        """从工具执行器的注册表中查找工具的 display_name，找不到则回退到 tool_name。"""
        if self.tool_executor is not None:
            definition = self.tool_executor.registry.get(tool_name)
            if definition is not None and definition.display_name:
                return definition.display_name
        return tool_name

    @staticmethod
    def _parse_decision(
        raw_content: str | None,
        *,
        limits: AgentConfig.BusinessLimitsConfig = DEFAULT_BUSINESS_LIMITS,
    ) -> dict[str, Any]:
        """从模型响应中解析结构化观察决策。"""

        if not raw_content:
            return {
                "decision": "continue",
                "reason": "没有观察输出",
                "next_action": "继续获取信息",
                "confidence": 0.2,
            }
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                data = json.loads(cleaned)
                decision = str(data.get("decision", "continue")).strip().lower()
                if decision not in {"continue", "answer", "retry", "abandon"}:
                    decision = "continue"
                confidence = data.get("confidence", 0.5)
                try:
                    confidence = max(
                        limits.binary_score_min,
                        min(limits.binary_score_max, float(confidence)),
                    )
                except (TypeError, ValueError):
                    confidence = 0.5
                return {
                    "decision": decision,
                    "reason": str(data.get("reason", "") or "").strip()[
                        :limits.agent_observation_reason_chars
                    ],
                    "next_action": str(data.get("next_action", "") or "").strip()[
                        :limits.agent_observation_next_action_chars
                    ],
                    "confidence": confidence,
                }
            except json.JSONDecodeError:
                pass

        lowered = cleaned.lower()
        if "[answer]" in lowered:
            text = cleaned.rsplit("[answer]", 1)[0].strip()
            return {
                "decision": "answer",
                "reason": text or "信息充足",
                "next_action": "生成最终回复",
                "confidence": 0.7,
            }
        if "[retry]" in lowered:
            text = cleaned.rsplit("[retry]", 1)[0].strip()
            return {
                "decision": "retry",
                "reason": text or "需要换参数重试",
                "next_action": "换参数或工具重试",
                "confidence": 0.6,
            }
        if "[abandon]" in lowered:
            text = cleaned.rsplit("[abandon]", 1)[0].strip()
            return {
                "decision": "abandon",
                "reason": text or "已有尝试仍不可得",
                "next_action": "说明边界并结束",
                "confidence": 0.6,
            }
        text = cleaned.rsplit("[continue]", 1)[0].strip()
        return {
            "decision": "continue",
            "reason": text or "信息还不够充分",
            "next_action": "继续获取更多信息",
            "confidence": 0.5,
        }
