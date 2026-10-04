"""
安全审核节点。

功能说明:
本文件实现安全审核图节点,在 Agent 图流程中输入和输出两个位置执行安全审核:
- safety_input: 入口节点,在 compress 前对用户输入做敏感词+意图审核
- safety_output: 出口节点,在 summary 前对 Agent 回复做输出审核

审核被拦截时直接结束,不进入后续节点;审核通过后正常流转。
拦截回复分为两类:
- 政治敏感: 小模型生成立场正确的反驳性回复
- 其他拦截: 小模型生成脱敏的礼貌拒绝回复
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agent_service.agent_core.nodes.base import AgentState
from agent_service.core.agent_config import AgentConfig
from agent_service.services.safety.safety_service import SafetyService


BLOCKED_OUTPUT_MESSAGE = AIMessage(
    content="抱歉,当前回复因安全原因无法显示。如需帮助请重新描述您的问题。"
)


def _elapsed_ms(started_at: float) -> float:
    return max(0.01, round((time.perf_counter() - started_at) * 1000, 2))


class SafetyInputNode:
    """
    输入安全审核节点。

    执行 Layer 1 (敏感词) + Layer 2 (意图审核)。
    通过 → 继续流转;拦截 → 通过 SafetyService 生成差异化回复并结束。
    """

    def __init__(self, *, config: AgentConfig, safety_service: SafetyService) -> None:
        self.config = config
        self._safety_service = safety_service

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """从最新 HumanMessage 提取用户输入并执行审核。"""

        started_at = time.perf_counter()
        user_input = self._extract_user_input(state)
        if not user_input:
            return {}

        llm_config = state.get("llm_config")
        result = self._safety_service.audit_input(user_input, llm_config=llm_config, user_id=str(state.get("user_id") or ""))
        if result.blocked:
            block_message = self._safety_service.generate_block_message(
                result,
                user_input,
                llm_config=llm_config,
            )
            return {
                "messages": [AIMessage(content=block_message)],
                "trace": [{
                    "node": "safety_input",
                    "event": "blocked",
                    "model_tier": "runtime",
                    "category": "political" if result.is_political else "general",
                    "message": result.block_reason,
                    "human_readable": result.block_reason or "输入安全审核拦截。",
                    "duration_ms": _elapsed_ms(started_at),
                    "chat_visible": False,
                }],
                "observation_decision": "blocked",
            }
        return {
            "trace": [{
                "node": "safety_input",
                "event": "passed",
                "model_tier": "runtime",
                "message": "输入安全审核通过",
                "human_readable": "输入安全审核通过。",
                "duration_ms": _elapsed_ms(started_at),
                "chat_visible": False,
            }],
        }

    @staticmethod
    def _extract_user_input(state: AgentState) -> str:
        """从状态消息中提取最近一条用户输入。"""

        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    )
        return ""


class SafetyOutputNode:
    """
    输出安全审核节点。

    执行 Layer 3 (输出审核)。
    通过 → 继续到 summary;拦截 → 注入安全回复并结束。
    """

    def __init__(self, *, config: AgentConfig, safety_service: SafetyService) -> None:
        self.config = config
        self._safety_service = safety_service

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """从最新 AIMessage 提取输出并执行审核。"""

        started_at = time.perf_counter()
        output_text = self._extract_output(state)
        user_input = SafetyInputNode._extract_user_input(state)
        if not output_text:
            return {}

        result = self._safety_service.audit_output(output_text, user_input=user_input, user_id=str(state.get("user_id") or ""))
        if result.blocked or result.sanitized:
            safe_text = result.safe_output
            return {
                "messages": [AIMessage(content=safe_text)],
                "trace": [{
                    "node": "safety_output",
                    "event": result.verdict,
                    "model_tier": "runtime",
                    "message": result.reason,
                    "human_readable": result.reason or "输出安全审核已改写回复。",
                    "duration_ms": _elapsed_ms(started_at),
                    "chat_visible": False,
                }],
            }
        return {
            "trace": [{
                "node": "safety_output",
                "event": "passed",
                "model_tier": "runtime",
                "message": "输出安全审核通过",
                "human_readable": "输出安全审核通过。",
                "duration_ms": _elapsed_ms(started_at),
                "chat_visible": False,
            }],
        }

    @staticmethod
    def _extract_output(state: AgentState) -> str:
        """从状态消息中提取最近一条 AI 回复。"""

        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                content = msg.content
                if isinstance(content, str):
                    return content
        return ""
