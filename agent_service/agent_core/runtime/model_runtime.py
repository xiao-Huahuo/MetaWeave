"""AgentCore model_runtime 职责实现。

本模块由机械迁移生成，方法体保持原业务逻辑。
"""

from __future__ import annotations

import json
import logging
import queue as queue_module
import re
import threading
import time
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from agent_service.agent_core.graph import AgentGraphBuilder
from agent_service.agent_core.nodes.model_decision import ModelDecisionNode
from agent_service.agent_core.runtime import AttachmentRuntime, CancellationRuntime
from agent_service.agent_core.runtime.error_recovery import extract_friendly_error
from agent_service.agent_core.runtime.shared import (
    AGENT_LOOP_AUTO,
    AGENT_LOOP_DEEP_ALIAS,
    AGENT_LOOP_MODES,
    AGENT_LOOP_PLAN,
    AGENT_LOOP_REACT,
    AGENT_LOOP_SIMPLE,
)
from agent_service.agent_core.runtime.token_usage import extract_token_usage
from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.core.context_budget import capacity_overrides_from_mapping
from agent_service.schemas.message import MessageCreate
from agent_service.scripts.draw_agent_graph import draw_agent_graph
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.services.child_agent import ChildAgentContract, ChildAgentEvent, ChildAgentManager
from agent_service.services.message.service import MessageService
from agent_service.services.session_attachment.service import SessionAttachmentService
from agent_service.services.safety import SafetyService
from agent_service.services.scheduler import (
    BACKGROUND_SUMMARY_TASK,
    FOREGROUND_AGENT_TASK,
    LARGE_MODEL_TIER,
    SMALL_MODEL_TIER,
    LLMTaskScheduler,
    get_llm_task_scheduler,
)
from agent_service.tools import (
    ToolExecutor,
    ToolRegistry,
    clear_agent_token_callback,
    clear_context_mirror_callback,
    clear_context_compression_callback,
    clear_markdown_html_visualization_callback,
    clear_plan_state,
    clear_planner_content_callback,
    clear_observation_content_callback,
    clear_task_list_callback,
    clear_tool_runtime,
    clear_tool_trace_callback,
    get_plan_state,
    set_agent_token_callback,
    set_context_mirror_callback,
    set_context_compression_callback,
    set_markdown_html_visualization_callback,
    set_plan_state,
    set_planner_content_callback,
    set_observation_content_callback,
    set_task_list_callback,
    set_tool_runtime,
    set_tool_trace_callback,
    normalize_agent_access_mode,
)
from agent_service.services.task_list.service import extract_plan_state, merge_plan_state


logger = logging.getLogger(__name__)
CITATION_ANCHOR_PATTERN = re.compile(r"\[([A-Z]?\d+)\]")

class ModelRuntimeMixin:
    def _stream_simple_answer(
        self,
        *,
        messages: list[BaseMessage],
        user_id: str,
        session_id: str,
        message_service: MessageService,
        citation_map: dict[str, Any] | None = None,
        latency_marks: dict[str, float] | None = None,
        turn_started_at: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        对明显不需要工具的短输入走轻量直答路径。

        这条路径仍然使用 ContextBuilder 的消息、用户自定义系统提示词和消息持久化,
        但绕过 planner/action/observation graph loop,避免一次简单问候触发多次 LLM 请求。
        """

        system_content = self._build_runtime_system_prompt(user_id=user_id, session_id=session_id)
        llm_config = self._get_user_llm_config(user_id) or {}
        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        model_name = llm_config.get("model_name")
        small_api_key = llm_config.get("small_api_key") or api_key
        small_base_url = llm_config.get("small_base_url") or base_url
        small_model_name = llm_config.get("small_model_name") or model_name
        context_window_tokens, max_output_tokens = capacity_overrides_from_mapping(
            llm_config,
            model_tier=SMALL_MODEL_TIER,
        )
        runtime_messages = [SystemMessage(content=system_content), *messages]
        cumulative = ""
        last_sent_content = ""
        final_message: BaseMessage | None = None
        stream_diagnostics: dict[str, Any] = {}
        user_prompt = ""
        first_delta_sent = False

        def latency_metadata(extra: dict[str, float] | None = None) -> dict[str, Any]:
            """Attach backend latency diagnostics to simple-mode SSE events."""

            if turn_started_at is None:
                return {}
            timings = dict(latency_marks or {})
            if extra:
                timings.update(extra)
            timings["backend_elapsed_ms"] = max(0.01, round((time.perf_counter() - turn_started_at) * 1000, 2))
            return {"latency": timings}

        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_prompt = self._stringify_content(msg.content)
                break

        try:
            logger.info("启用短问直答路径 | user=%s session=%s msg_count=%d", user_id, session_id, len(runtime_messages))
            safety_started_at = time.perf_counter()
            input_audit = self.safety_service.audit_input(user_prompt, llm_config=llm_config)
            safety_input_trace = {
                "node": "safety_input",
                "event": "blocked" if input_audit.blocked else "passed",
                "model_tier": "runtime",
                "category": "political" if input_audit.is_political else "general",
                "message": input_audit.block_reason if input_audit.blocked else "输入安全审核通过",
                "human_readable": input_audit.block_reason if input_audit.blocked else "输入安全审核通过。",
                "duration_ms": max(0.01, round((time.perf_counter() - safety_started_at) * 1000, 2)),
                "chat_visible": False,
            }
            message_service.create_message(
                MessageCreate(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content="",
                    metadata_json={
                        "node": "safety_input",
                        "source": "simple_answer_safety",
                        "trace": [safety_input_trace],
                    },
                )
            )
            serialized_runtime_messages = self._serialize_runtime_messages(runtime_messages)
            simple_context_usage = ContextBuilder.context_usage_from_serialized(
                serialized_runtime_messages,
                config=self.config,
                model_name=str(model_name or self.config.model.model_name or "") or None,
            )
            self._persist_session_state_value(session_id, "context_usage", simple_context_usage)
            yield {
                "node": "safety_input",
                "content": "",
                "tool_calls": [],
                "trace": [safety_input_trace],
                "model_name": "",
                "metadata": latency_metadata({"safety_input_ms": safety_input_trace["duration_ms"]}),
            }
            if input_audit.blocked:
                block_message = self.safety_service.generate_block_message(
                    input_audit,
                    user_prompt,
                    llm_config=llm_config,
                )
                message_service.create_message(
                    MessageCreate(
                        session_id=session_id,
                        user_id=user_id,
                        role="assistant",
                        content=block_message,
                        metadata_json={
                            "node": "safety_input",
                            "source": "simple_answer_safety_block",
                            "trace": [safety_input_trace],
                        },
                    )
                )
                yield {
                    "node": "safety_input",
                    "content": block_message,
                    "tool_calls": [],
                    "trace": [],
                    "model_name": "",
                    "metadata": latency_metadata(),
                }
                return
            started_at = time.perf_counter()
            cumulative_reasoning = ""
            simple_snapshot = {
                **self.task_scheduler.build_observability_snapshot(
                    messages=runtime_messages,
                    tool_names=[],
                    model_tier=SMALL_MODEL_TIER,
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    small_api_key=small_api_key,
                    small_base_url=small_base_url,
                    small_model_name=small_model_name,
                    context_window_tokens=context_window_tokens,
                    max_output_tokens=max_output_tokens,
                    node="agent_simple",
                ),
                "call_index": 1,
            }
            self._persist_session_state_value(session_id, "context_snapshots", [simple_snapshot])
            yield {
                "node": "agent",
                "type": "context_mirror",
                "content": "",
                "tool_calls": [],
                "trace": [],
                "model_name": self._model_name_for_node("agent_simple"),
                "context_request": simple_snapshot,
                "context_snapshots": [simple_snapshot],
                "context_messages": serialized_runtime_messages,
                "metadata": {
                    **latency_metadata(),
                    "context_usage": simple_context_usage,
                },
            }
            for chunk in self.task_scheduler.stream_chat(
                task_type=FOREGROUND_AGENT_TASK,
                messages=runtime_messages,
                tool_names=[],
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
                if chunk.get("status") == "complete":
                    final_message = chunk.get("message")
                    diagnostics = chunk.get("stream_diagnostics")
                    if isinstance(diagnostics, dict):
                        stream_diagnostics = diagnostics
                    continue
                reasoning_delta = chunk.get("reasoning_delta", "")
                if reasoning_delta:
                    # 思考文本实时透传,前端 Think 条在首字正文之前就能开始渲染。
                    cumulative_reasoning += reasoning_delta
                    yield {
                        "type": "thinking",
                        "node": "agent",
                        "content": reasoning_delta,
                        "tool_calls": [],
                        "trace": [],
                        "model_name": self._model_name_for_node("agent_simple"),
                        # 思考 token 不携带逐次变化的耗时，防止前端响应式风暴。
                        "metadata": {},
                    }
                delta = chunk.get("content_delta", "")
                if not delta:
                    continue
                cumulative += delta
                safe_content = self._sanitize_streaming_content(
                    cumulative,
                    min_chars=self.config.model.streaming_sanitize_min_chars,
                )
                if safe_content != cumulative:
                    # 命中 JSON/内部标记拦截:跳过本轮,避免把被拦截内容按增量发出。
                    continue
                output_delta = safe_content[len(last_sent_content):] if len(safe_content) > len(last_sent_content) else ""
                if not output_delta:
                    last_sent_content = safe_content
                    continue
                last_sent_content = safe_content
                extra_latency = None
                if not first_delta_sent:
                    first_delta_sent = True
                    extra_latency = (
                        {
                            "first_agent_delta_ms": max(
                                0.01,
                                round((time.perf_counter() - turn_started_at) * 1000, 2),
                            )
                        }
                        if turn_started_at is not None
                        else None
                    )
                yield {
                    "type": "delta",
                    "node": "agent",
                    "content": output_delta,
                    "tool_calls": [],
                    "trace": [],
                    "model_name": self._model_name_for_node("agent_simple"),
                    # 仅首个正文增量报告首字延迟，终态仍携带完整 latency。
                    "metadata": latency_metadata(extra_latency) if extra_latency else {},
                }

            content = self._stringify_content(getattr(final_message, "content", "") if final_message is not None else cumulative)
            content = self._sanitize_agent_output(content)
            content = self._drop_unmapped_citation_anchors(content, citation_map)
            content = self._insert_missing_citation_anchors_inline(content, citation_map)
            citation_metadata = self._build_citation_metadata(content, citation_map)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            token_usage = extract_token_usage(final_message)
            simple_trace = {
                "node": "agent",
                "event": "simple_answer",
                "human_readable": "短输入直接生成回复，未进入工具循环。",
                "model_tier": SMALL_MODEL_TIER,
                "model_name": self._model_name_for_node("agent_simple"),
                "duration_ms": duration_ms,
                "token_usage": token_usage,
            }
            output_safety_started_at = time.perf_counter()
            output_audit = self.safety_service.audit_output(content, user_input=user_prompt)
            if output_audit.blocked or output_audit.sanitized:
                content = output_audit.safe_output
                citation_metadata = self._build_citation_metadata(content, citation_map)
            safety_output_trace = {
                "node": "safety_output",
                "event": output_audit.verdict if (output_audit.blocked or output_audit.sanitized) else "passed",
                "model_tier": "runtime",
                "message": output_audit.reason if (output_audit.blocked or output_audit.sanitized) else "输出安全审核通过",
                "human_readable": output_audit.reason if (output_audit.blocked or output_audit.sanitized) else "输出安全审核通过。",
                "duration_ms": max(0.01, round((time.perf_counter() - output_safety_started_at) * 1000, 2)),
                "chat_visible": False,
            }
            message_service.create_message(
                MessageCreate(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=content,
                    metadata_json={
                        "node": "agent",
                        "source": "simple_answer_mode",
                        "trace": [simple_trace, safety_output_trace],
                        **({"reasoning_content": cumulative_reasoning} if cumulative_reasoning else {}),
                        **({"stream_diagnostics": stream_diagnostics} if stream_diagnostics else {}),
                        **citation_metadata,
                    },
                )
            )
            yield {
                "node": "agent",
                "content": content,
                "tool_calls": [],
                "trace": [simple_trace, safety_output_trace],
                "model_name": self._model_name_for_node("agent_simple"),
                "metadata": {
                    **citation_metadata,
                    **({"stream_diagnostics": stream_diagnostics} if stream_diagnostics else {}),
                    **latency_metadata(
                        {
                            "simple_model_total_ms": duration_ms,
                            "safety_output_ms": safety_output_trace["duration_ms"],
                        }
                    ),
                },
            }
        except GeneratorExit:
            raise
        except Exception as exc:
            friendly_msg = extract_friendly_error(str(exc))
            logger.warning("短问直答出错 | user=%s session=%s error=%s", user_id, session_id, friendly_msg)
            message_service.create_message(
                MessageCreate(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=friendly_msg,
                    metadata_json={"node": "error", "source": "simple_answer_mode"},
                )
            )
            yield {
                "node": "error",
                "content": friendly_msg,
                "error": friendly_msg,
                "tool_calls": [],
                "trace": [],
                "model_name": "",
            }
    @staticmethod
    def _should_use_simple_answer_mode(*, prompt: str, reference: str | None = None) -> bool:
        """判断本轮是否可以跳过 Agent Loop,直接轻量回复。"""

        if reference:
            return False
        text = (prompt or "").strip()
        if not text:
            return False
        normalized = text.lower()
        simple_exact = {
            "hi",
            "hello",
            "hey",
            "ok",
            "okay",
            "thanks",
            "thank you",
            "你好",
            "您好",
            "在吗",
            "谢谢",
            "好的",
            "好",
            "嗯",
            "？",
            "?",
        }
        if normalized in simple_exact:
            return True
        if len(text) > DEFAULT_BUSINESS_LIMITS.agent_simple_prompt_max_chars:
            return False
        toolish_keywords = (
            "搜索",
            "查找",
            "查询",
            "打开",
            "读取",
            "文件",
            "知识库",
            "图谱",
            "记住",
            "长期",
            "规则",
            "写入",
            "删除",
            "重命名",
            "复制",
            "剪切",
            "粘贴",
            "灌库",
            "入库",
            "总结文档",
            "pdf",
            "docx",
            "xlsx",
            "ppt",
            "csv",
            "代码",
            "运行",
            "工具",
        )
        return not any(keyword in normalized for keyword in toolish_keywords)
    @staticmethod
    def _should_use_plan_mode(*, prompt: str, reference: str | None = None) -> bool:
        """判断 auto 模式下是否需要进入带 planner/observation 的规划图。"""

        if reference:
            return True
        text = (prompt or "").strip()
        if not text:
            return False
        normalized = text.lower()
        if len(text) >= DEFAULT_BUSINESS_LIMITS.agent_plan_prompt_min_chars:
            return True
        plan_keywords = (
            "计划",
            "规划",
            "方案",
            "步骤",
            "拆解",
            "分析",
            "比较",
            "评估",
            "调研",
            "排查",
            "诊断",
            "设计",
            "实现",
            "重构",
            "优化",
            "修复",
            "完成",
            "整理",
            "总结",
            "写文档",
            "多步骤",
            "一步一步",
            "从头到尾",
            "先",
            "然后",
            "最后",
            "todo",
        )
        return any(keyword in normalized for keyword in plan_keywords)
    def _resolve_agent_loop_mode(
        self,
        *,
        agent_mode: str | None,
        prompt: str,
        reference: str | None = None,
        user_id: str = "",
    ) -> str:
        """把外部请求模式归一为本轮实际执行模式。auto 模式优先由小模型分类。"""

        requested = (agent_mode or AGENT_LOOP_AUTO).strip().lower()
        explicit_mode = self._normalize_explicit_agent_loop_mode(requested)
        if explicit_mode is not None:
            return explicit_mode
        classified_mode = self._classify_agent_loop_mode_with_small_model(
            prompt=prompt,
            reference=reference,
            user_id=user_id,
        )
        if classified_mode is not None:
            return classified_mode
        return self._resolve_agent_loop_mode_fallback(
            agent_mode=requested,
            prompt=prompt,
            reference=reference,
        )
    @staticmethod
    def _normalize_explicit_agent_loop_mode(requested: str) -> str | None:
        """返回用户显式指定的模式;auto 返回 None。"""

        if requested == AGENT_LOOP_SIMPLE:
            return AGENT_LOOP_SIMPLE
        if requested == AGENT_LOOP_REACT:
            return AGENT_LOOP_REACT
        if requested in {AGENT_LOOP_PLAN, AGENT_LOOP_DEEP_ALIAS}:
            return AGENT_LOOP_PLAN
        return None
    @staticmethod
    def _resolve_agent_loop_mode_fallback(
        *,
        agent_mode: str | None,
        prompt: str,
        reference: str | None = None,
    ) -> str:
        """小模型路由不可用时的保守回退规则。"""

        requested = (agent_mode or AGENT_LOOP_AUTO).strip().lower()
        explicit_mode = ModelRuntimeMixin._normalize_explicit_agent_loop_mode(requested)
        if explicit_mode is not None:
            return explicit_mode
        if ModelRuntimeMixin._should_use_plan_mode(prompt=prompt, reference=reference):
            return AGENT_LOOP_PLAN
        if ModelRuntimeMixin._should_use_simple_answer_mode(prompt=prompt, reference=reference):
            return AGENT_LOOP_SIMPLE
        return AGENT_LOOP_REACT
    def _classify_agent_loop_mode_with_small_model(
        self,
        *,
        prompt: str,
        reference: str | None = None,
        user_id: str = "",
    ) -> str | None:
        """使用小模型判断 auto 模式下应进入 simple/react/plan 哪张图。"""

        text = (prompt or "").strip()
        if not text:
            return None
        llm_config = self._get_user_llm_config(user_id) or {}
        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        model_name = llm_config.get("model_name")
        small_api_key = llm_config.get("small_api_key") or api_key
        small_base_url = llm_config.get("small_base_url") or base_url
        small_model_name = llm_config.get("small_model_name") or model_name
        context_window_tokens, max_output_tokens = capacity_overrides_from_mapping(
            llm_config,
            model_tier=SMALL_MODEL_TIER,
        )
        system_prompt = self.config.prompts.agent_mode_router_system_prompt
        user_prompt = (
            f"用户请求:\n{text}\n\n"
            f"是否带显式引用片段: {'是' if reference else '否'}\n"
            "请给出路由 JSON。"
        )
        try:
            response = self.task_scheduler.invoke_chat(
                task_type=FOREGROUND_AGENT_TASK,
                messages=[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
                tool_names=[],
                model_tier=SMALL_MODEL_TIER,
                temperature=0.0,
                timeout_seconds=self.config.limits.agent_mode_decision_timeout_seconds,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                small_api_key=small_api_key,
                small_base_url=small_base_url,
                small_model_name=small_model_name,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
            )
        except Exception:
            logger.warning("小模型 Agent Loop 路由失败,回退到本地规则 | user=%s", user_id, exc_info=True)
            return None
        mode = self._parse_agent_loop_route_response(self._stringify_content(response.content))
        if mode is None:
            logger.warning("小模型 Agent Loop 路由输出无法解析,回退到本地规则 | output=%s", response.content)
        return mode
    @staticmethod
    def _parse_agent_loop_route_response(content: str) -> str | None:
        """解析小模型路由输出。"""

        text = (content or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0].strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        mode = str(data.get("mode", "") or "").strip().lower()
        if mode in {AGENT_LOOP_SIMPLE, AGENT_LOOP_REACT, AGENT_LOOP_PLAN}:
            return mode
        if mode == AGENT_LOOP_DEEP_ALIAS:
            return AGENT_LOOP_PLAN
        return None
    @staticmethod
    def _extract_agent_mode_from_events(events: list[dict[str, Any]]) -> str | None:
        """从 stream_session_prompt 事件中读取本轮实际执行模式。"""

        for event in events:
            metadata = event.get("metadata")
            if not isinstance(metadata, dict):
                continue
            mode = str(metadata.get("agent_mode", "") or "").strip().lower()
            if mode in {AGENT_LOOP_SIMPLE, AGENT_LOOP_REACT, AGENT_LOOP_PLAN}:
                return mode
        return None
    def _build_runtime_system_prompt(self, *, user_id: str, session_id: str = "") -> str:
        """构造运行时系统提示词,与模型决策节点保持一致。"""

        system_content = self.config.prompts.agent_system_prompt
        if not user_id:
            return system_content
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
            logger.debug("读取用户自定义系统提示词失败 | user=%s", user_id, exc_info=True)
        if session_id and self.task_list_service is not None:
            try:
                system_content += ModelDecisionNode._build_task_list_prompt(
                    self.task_list_service.get_task_list(session_id)
                )
            except Exception:
                logger.debug("failed to load session task list | session=%s", session_id, exc_info=True)
        return system_content
    def _model_name_for_node(self, node_name: str) -> str:
        """根据节点名返回对应的模型名称，供前端展示。"""
        small_nodes = {"planner", "observation", "agent_simple", "compress", "summary"}
        runtime_nodes = {"action", "context_builder", "safety_input", "safety_output", "error", "interrupted"}
        if node_name in runtime_nodes:
            return ""
        if node_name in small_nodes:
            return (
                self.config.model.small_model_name
                or self.config.model.model_name
            )
        return self.config.model.model_name
    def _get_user_llm_config(self, user_id: str) -> dict[str, Any] | None:
        """读取用户的 LLM 配置（api_key, base_url 等），在图启动前一次性获取，避免重入竞态。"""
        if not user_id or self.settings_service is None:
            return None
        try:
            return self.settings_service.get_llm_config(user_id=user_id)
        except Exception:
            return None
    def _get_long_term_memory_enabled(self, user_id: str) -> bool:
        """读取用户的长期记忆开关,读取失败时保持默认开启。"""
        if not user_id or self.settings_service is None:
            return True
        try:
            return bool(self.settings_service.get_memory_config(user_id=user_id).get("long_term_memory_enabled", True))
        except Exception:
            return True

def _rename_session_worker(agent: Any, *, user_id: str, session_id: str) -> str | None:
    """生成会话标题并持久化到 DB。优先用小模型,失败时自动降级大模型。"""
    try:
        message_service = agent._get_message_service()
        recent = message_service.list_recent_messages(
            user_id=user_id, session_id=session_id, limit=agent.config.limits.session_title_history_limit,
            include_summarized=True,
        )
        if len(recent) < agent.config.limits.session_title_min_messages:
            return None
        for message in reversed(recent):
            if getattr(message, "role", "") != "assistant":
                continue
            content = (getattr(message, "content", "") or "").strip()
            metadata = getattr(message, "metadata_json", None) or {}
            if metadata.get("node") == "error" or "429 Too Many Requests" in content or "模型服务限流" in content:
                logger.info("跳过会话自动重命名 | session=%s reason=last_assistant_error", session_id)
                return None
            break
        lines: list[str] = []
        for m in recent[-agent.config.limits.session_title_history_limit:]:
            role_label = ""
            if m.role == "user":
                role_label = "用户"
            elif m.role == "assistant":
                role_label = "助手"
            if not role_label:
                continue
            content_preview = (m.content or "")[:agent.config.limits.session_title_message_preview_chars].replace("\n", " ")
            lines.append(f"{role_label}: {content_preview}")
        if not lines:
            return None
        conversation = "\n".join(lines)
        rename_prompt = (
            "根据以下对话内容,为这个会话生成一个简洁的标题(15字以内,中文):\n\n"
            f"{conversation}\n\n标题:"
        )
        llm_config = agent._get_user_llm_config(user_id)
        api_key = llm_config.get("api_key") if llm_config else None
        base_url = llm_config.get("base_url") if llm_config else None
        model_name = llm_config.get("model_name") if llm_config else None
        small_api_key = (llm_config.get("small_api_key") or api_key) if llm_config else None
        small_base_url = (llm_config.get("small_base_url") or base_url) if llm_config else None
        small_model_name = (llm_config.get("small_model_name") or model_name) if llm_config else None
        small_context_tokens, small_output_tokens = capacity_overrides_from_mapping(
            llm_config,
            model_tier=SMALL_MODEL_TIER,
        )
        large_context_tokens, large_output_tokens = capacity_overrides_from_mapping(
            llm_config,
            model_tier=LARGE_MODEL_TIER,
        )

        title = _do_rename_llm_call(agent, rename_prompt, session_id,
            model_tier=SMALL_MODEL_TIER,
            api_key=api_key, base_url=base_url, model_name=model_name,
            small_api_key=small_api_key, small_base_url=small_base_url, small_model_name=small_model_name,
            context_window_tokens=small_context_tokens, max_output_tokens=small_output_tokens)
        if title is not None:
            return _persist_rename_title(agent, session_id, title)

        logger.info("小模型重命名失败,降级使用大模型 | session=%s", session_id)
        title = _do_rename_llm_call(agent, rename_prompt, session_id,
            model_tier=LARGE_MODEL_TIER,
            api_key=api_key, base_url=base_url, model_name=model_name,
            context_window_tokens=large_context_tokens, max_output_tokens=large_output_tokens)
        if title is not None:
            return _persist_rename_title(agent, session_id, title)
        return None
    except Exception:
        logger.info("会话自动重命名失败 | session=%s", session_id, exc_info=True)
        return None
def _do_rename_llm_call(
    agent: Any, prompt: str, session_id: str, *,
    model_tier: str,
    api_key: str | None = None, base_url: str | None = None, model_name: str | None = None,
    small_api_key: str | None = None, small_base_url: str | None = None, small_model_name: str | None = None,
    context_window_tokens: int | None = None, max_output_tokens: int | None = None,
) -> str | None:
    """调用 LLM 生成会话标题,返回标题或 None。"""
    try:
        response = agent.task_scheduler.invoke_chat(
            task_type=BACKGROUND_SUMMARY_TASK,
            messages=[HumanMessage(content=prompt)],
            tool_names=[],
            model_tier=model_tier,
            temperature=0.3,
            api_key=api_key, base_url=base_url, model_name=model_name,
            small_api_key=small_api_key, small_base_url=small_base_url, small_model_name=small_model_name,
            context_window_tokens=context_window_tokens, max_output_tokens=max_output_tokens,
        )
        title = (getattr(response, "content", "") or "").strip()
        if not title:
            return None
        return title[:agent.config.limits.session_title_max_chars]
    except Exception:
        logger.info("重命名 LLM 调用失败 | session=%s tier=%s", session_id, model_tier, exc_info=True)
        return None
def _persist_rename_title(agent: Any, session_id: str, title: str) -> str:
    """将标题写入 DB 并返回。"""
    from agent_service.services.session.service import SessionService
    from agent_service.schemas.session import SessionUpdate
    session_service = agent.session_service or SessionService(config=agent.config)
    session_service.update_session_name(session_id, SessionUpdate(session_name=title))
    return title
def _launch_auto_rename(agent: Any, *, user_id: str, session_id: str) -> tuple[threading.Thread, queue_module.Queue]:
    """Fire rename worker in background thread. Caller can wait on the queue for the result."""
    q: queue_module.Queue = queue_module.Queue(maxsize=1)

    def _worker() -> None:
        try:
            title = _rename_session_worker(agent, user_id=user_id, session_id=session_id)
            q.put(title)
        except Exception:
            q.put(None)

    thread = threading.Thread(target=_worker, daemon=True, name=f"rename-{session_id[:12]}")
    thread.start()
    return thread, q
