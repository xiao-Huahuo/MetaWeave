"""AgentCore graph_runner 职责实现。

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
from datetime import datetime, timezone
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
from agent_service.core.context_budget import ModelCapacity
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
    clear_agent_thinking_callback,
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
    set_agent_thinking_callback,
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

from agent_service.agent_core.runtime.model_runtime import _launch_auto_rename

class GraphRunnerMixin:
    def stream_run(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        agent_mode: str = AGENT_LOOP_PLAN,
        agent_access_mode: str = "sandbox",
        allow_child_spawn: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """
        运行一轮无状态 Agent 并逐节点产出 dict 事件。

        prompt: 用户本轮输入。
        user_id: 用户 ID。
        session_id: 会话 ID。
        agent_mode: Agent Loop 模式,支持 react / plan。无状态入口不使用 simple。
        """

        effective_mode = AGENT_LOOP_REACT if agent_mode == AGENT_LOOP_REACT else AGENT_LOOP_PLAN
        messages = [HumanMessage(content=prompt)]
        logger.info("开始无状态流式运行 | user=%s session=%s mode=%s", user_id, session_id, effective_mode)
        yield from self._stream_events(
            messages=messages,
            user_id=user_id,
            session_id=session_id,
            graph=self.graphs[effective_mode],
            agent_mode=effective_mode,
            agent_access_mode=agent_access_mode,
            prompt=prompt,
            allow_child_spawn=allow_child_spawn,
        )
        logger.debug("无状态流式运行完成 | user=%s session=%s mode=%s", user_id, session_id, effective_mode)
    def run_once(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        agent_mode: str = AGENT_LOOP_PLAN,
        agent_access_mode: str = "sandbox",
        allow_child_spawn: bool = True,
    ) -> dict[str, Any]:
        """
        运行一轮无状态 Agent 并返回结构化结果。

        prompt: 用户本轮输入。
        user_id: 用户 ID。
        session_id: 会话 ID。
        agent_mode: Agent Loop 模式,支持 react / plan。
        """

        effective_mode = AGENT_LOOP_REACT if agent_mode == AGENT_LOOP_REACT else AGENT_LOOP_PLAN
        chunks = list(self.stream_run(
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            agent_mode=effective_mode,
            agent_access_mode=agent_access_mode,
            allow_child_spawn=allow_child_spawn,
        ))
        graph_diagram_path = self.graph_diagram_paths[effective_mode]
        graph_diagram = graph_diagram_path.read_text(encoding="utf-8")
        return {
            "graph_diagram_path": str(graph_diagram_path),
            "graph_diagram": graph_diagram,
            "final_output": self.extract_final_output(chunks),
            "events": chunks,
        }
    def graph_diagram_for_mode(self, agent_mode: str) -> str:
        """返回指定 Agent Loop 模式对应的 Mermaid 图。"""

        effective_mode = AGENT_LOOP_REACT if agent_mode == AGENT_LOOP_REACT else AGENT_LOOP_PLAN
        return self.graph_diagram_paths[effective_mode].read_text(encoding="utf-8")
    def graph_diagram_path_for_mode(self, agent_mode: str) -> str:
        """返回指定 Agent Loop 模式对应的 Mermaid 文件路径。"""

        effective_mode = AGENT_LOOP_REACT if agent_mode == AGENT_LOOP_REACT else AGENT_LOOP_PLAN
        return str(self.graph_diagram_paths[effective_mode])
    def list_registered_tools(self) -> dict[str, Any]:
        """
        返回当前 Agent 最终可用工具注册表快照。

        结果包含内置工具和配置启用的 MCP 工具;测试或外部注入 tools 时回退读取
        LangChain tool 对象的基础信息。
        """

        if self.tool_registry is not None:
            tools = [
                {
                    "name": definition.name,
                    "display_name": definition.display_name or definition.name,
                    "description": definition.description,
                    "args_schema": definition.args_schema,
                    "argument_count": len(definition.args_schema.get("properties", {})),
                }
                for definition in self.tool_registry.definitions.values()
            ]
        else:
            tools = [
                {
                    "name": str(getattr(tool, "name", "")),
                    "display_name": str(getattr(tool, "name", "")),
                    "description": str(getattr(tool, "description", "")),
                    "args_schema": (
                        getattr(tool, "args_schema").model_json_schema()
                        if getattr(tool, "args_schema", None) is not None
                        else {}
                    ),
                    "argument_count": len(getattr(getattr(tool, "args_schema", None), "model_fields", {}) or {}),
                }
                for tool in self.tools
            ]
        return {
            "tool_count": len(tools),
            "tools": sorted(tools, key=lambda item: item["name"]),
        }
    def run_session_prompt(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        reference: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        user_message_metadata: dict[str, Any] | None = None,
        agent_mode: str = AGENT_LOOP_AUTO,
        agent_access_mode: str = "sandbox",
        allow_child_spawn: bool = True,
    ) -> dict[str, Any]:
        """
        运行带 session 上下文和消息持久化的一轮 Agent,返回结构化结果。

        prompt: 用户本轮输入。
        user_id: 用户 ID。
        session_id: 会话 ID。
        reference: 用户明确引用的文档片段。
        attachments: 本轮用户气泡关联的会话附件。
        agent_mode: Agent Loop 模式,支持 auto / simple / react / plan。兼容 deep 旧别名。
        """

        chunks = list(
            self.stream_session_prompt(
                prompt=prompt,
                user_id=user_id,
                session_id=session_id,
                reference=reference,
                attachments=attachments,
                user_message_metadata=user_message_metadata,
                agent_mode=agent_mode,
                agent_access_mode=agent_access_mode,
                allow_child_spawn=allow_child_spawn,
            )
        )
        effective_access_mode = normalize_agent_access_mode(agent_access_mode)
        effective_mode = self._extract_agent_mode_from_events(chunks) or self._resolve_agent_loop_mode_fallback(
            agent_mode=agent_mode,
            prompt=prompt,
            reference=reference,
        )
        diagram_mode = AGENT_LOOP_REACT if effective_mode == AGENT_LOOP_REACT else AGENT_LOOP_PLAN
        graph_diagram_path = self.graph_diagram_paths[diagram_mode]
        graph_diagram = graph_diagram_path.read_text(encoding="utf-8")
        return {
            "graph_diagram_path": str(graph_diagram_path),
            "graph_diagram": graph_diagram,
            "final_output": self.extract_final_output(chunks),
            "events": chunks,
            "agent_mode": effective_mode,
            "agent_access_mode": effective_access_mode,
        }
    def stream_session_prompt(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        reference: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        user_message_metadata: dict[str, Any] | None = None,
        agent_mode: str = AGENT_LOOP_AUTO,
        agent_access_mode: str = "sandbox",
        web_search_max_results: int | None = None,
        allow_child_spawn: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """
        运行带 session 上下文和消息持久化的一轮 Agent,逐节点产出 dict 事件。

        prompt: 用户本轮输入。
        user_id: 用户 ID。
        session_id: 会话 ID。
        reference: 用户引用的文本,作为额外上下文注入。
        attachments: 本轮用户气泡关联的附件；服务端按用户和会话重新校验。
        agent_mode: Agent Loop 模式,支持 auto / simple / react / plan。兼容 deep 旧别名。
        web_search_max_results: 联网搜索每次最大结果数,用于系统提示词引导 agent 行为。
        """

        turn_started_at = time.perf_counter()
        user_message_created_at = datetime.now(timezone.utc)
        if web_search_max_results is None:
            web_search_max_results = self.config.limits.default_web_search_max_results
        latency_marks: dict[str, float] = {}

        def mark_latency(name: str, started_at: float) -> None:
            """Record one backend stage duration for turn latency diagnostics."""

            latency_marks[name] = max(0.01, round((time.perf_counter() - started_at) * 1000, 2))

        def latency_metadata(extra: dict[str, float] | None = None) -> dict[str, Any]:
            """Build a serializable latency payload shared by streamed events."""

            timings = dict(latency_marks)
            if extra:
                timings.update(extra)
            timings["backend_elapsed_ms"] = max(0.01, round((time.perf_counter() - turn_started_at) * 1000, 2))
            return {"latency": timings}

        reference = reference.strip() if reference and reference.strip() else None
        route_started_at = time.perf_counter()
        effective_mode = self._resolve_agent_loop_mode(
            agent_mode=agent_mode,
            prompt=prompt,
            reference=reference,
            user_id=user_id,
        )
        mark_latency("route_ms", route_started_at)
        task_list_started_at = time.perf_counter()
        active_task_list = self.task_list_service.get_task_list(session_id) if self.task_list_service is not None else None
        mark_latency("task_list_ms", task_list_started_at)
        if active_task_list is not None and effective_mode == AGENT_LOOP_SIMPLE:
            effective_mode = AGENT_LOOP_REACT
        effective_access_mode = normalize_agent_access_mode(agent_access_mode)
        message_service = self._get_message_service()
        context_builder = self._get_context_builder(message_service=message_service)
        long_term_memory_enabled = self._get_long_term_memory_enabled(user_id)
        logger.info(
            "开始 session 流式运行 | user=%s session=%s prompt_len=%d mode=%s requested_mode=%s",
            user_id,
            session_id,
            len(prompt),
            effective_mode,
            agent_mode,
        )
        context_started_at = time.perf_counter()
        compression_state = self._load_session_compression_state(session_id)
        runtime_llm_config = self._get_user_llm_config(user_id) or {}
        runtime_system_tokens = ContextBuilder.estimate_messages_tokens(
            [SystemMessage(content=self._build_runtime_system_prompt(user_id=user_id, session_id=session_id))],
            model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or "") or None,
        )
        messages = context_builder.build_messages(
            user_id=user_id, session_id=session_id, current_prompt=prompt, reference=reference,
            current_prompt_created_at=user_message_created_at,
            web_search_max_results=web_search_max_results,
            long_term_memory_enabled=long_term_memory_enabled,
            compression_state=compression_state,
            model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or "") or None,
            tool_definition_tokens=ContextBuilder.estimate_tool_definition_tokens(
                self.tools,
                model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or "") or None,
            ),
            additional_context_tokens=runtime_system_tokens,
            model_context_window_tokens=int(runtime_llm_config.get("model_context_window_tokens") or 0) or None,
            model_max_output_tokens=int(runtime_llm_config.get("model_max_output_tokens") or 0) or None,
        )
        runtime_capacity = ModelCapacity.resolve(
            config=self.config,
            model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or ""),
            model_tier="large",
            context_window_tokens=int(runtime_llm_config.get("model_context_window_tokens") or 0) or None,
            max_output_tokens=int(runtime_llm_config.get("model_max_output_tokens") or 0) or None,
        )
        if effective_mode == AGENT_LOOP_SIMPLE and ContextBuilder.should_compress(
            messages,
            config=self.config,
            model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or "") or None,
            extra_tokens=(
                runtime_system_tokens
                + ContextBuilder.estimate_tool_definition_tokens(
                    self.tools,
                    model_name=str(runtime_llm_config.get("model_name") or self.config.model.model_name or "") or None,
                )
            ),
            capacity=runtime_capacity,
        ):
            effective_mode = AGENT_LOOP_REACT
        mark_latency("context_build_ms", context_started_at)
        child_results_started_at = time.perf_counter()
        child_results = self.child_agent_manager.drain_results_for_session(session_id)
        mark_latency("child_results_ms", child_results_started_at)
        if child_results:
            child_results_text = "\n".join(
                f"- 子任务 {result.run_id} [{result.status.value}]：{result.summary}"
                for result in child_results
            )
            messages.append(
                SystemMessage(
                    content=self.config.prompts.child_results_context_template.format(
                        results=child_results_text
                    )
                )
            )
        turn_citation_map: dict[str, Any] = {}
        logger.debug("上下文构建完成 | message_count=%d", len(messages))

        initial_plan = self._load_session_plan(session_id) if effective_mode == AGENT_LOOP_PLAN else None

        for msg in messages:
            if isinstance(msg, SystemMessage):
                msg_create = self._message_to_create(
                    message=msg,
                    user_id=user_id,
                    session_id=session_id,
                    node_name="context_builder",
                )
                if msg_create is not None:
                    message_service.create_message(msg_create)
        persisted_attachments: list[dict[str, Any]] = []
        for attachment in attachments or []:
            attachment_id = str(attachment.get("attachment_id") or "") if isinstance(attachment, dict) else ""
            if not attachment_id or self.attachment_service is None:
                continue
            try:
                persisted_attachments.append(
                    self.attachment_service.get_attachment(
                        user_id=user_id,
                        session_id=session_id,
                        attachment_id=attachment_id,
                    )
                )
            except ValueError:
                logger.warning("忽略不属于当前会话的附件 | session=%s attachment=%s", session_id, attachment_id)
        message_service.create_message(
            MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="user",
                content=prompt,
                metadata_json={
                    **(user_message_metadata or {}),
                    "source": "stream_session_prompt",
                    **({"reference": reference} if reference else {}),
                    **({"attachments": persisted_attachments} if persisted_attachments else {}),
                },
                created_at=user_message_created_at,
            )
        )

        # 新用户轮次开始即清空旧请求快照；若安全审核拦截，本轮应明确显示“没有模型调用”。
        self._persist_session_state_value(session_id, "context_snapshots", [])

        # 将系统提示作为首个 SSE 事件下发, 供前端 Obs 面板的上下文拼装卡片使用。
        # 系统消息不在图节点输出中, 不走常规 node 事件, 需要单独 yield。
        for msg in messages:
            if isinstance(msg, SystemMessage):
                rag_metrics = (getattr(msg, "additional_kwargs", {}) or {}).get("rag_metrics")
                recall_details = (getattr(msg, "additional_kwargs", {}) or {}).get("recall_details")
                citation_map = (recall_details or {}).get("citation_map", {})
                if citation_map:
                    turn_citation_map.update(citation_map)
                system_meta = {}
                if rag_metrics:
                    system_meta["rag_metrics"] = rag_metrics
                if recall_details:
                    system_meta["recall_details"] = recall_details
                if citation_map:
                    system_meta["citation_map"] = citation_map
                system_meta["agent_mode"] = effective_mode
                system_meta["requested_agent_mode"] = agent_mode
                system_meta["agent_access_mode"] = effective_access_mode
                system_meta["long_term_memory_enabled"] = long_term_memory_enabled
                system_meta.update(latency_metadata())
                yield {
                    "node": "context_builder",
                    "type": "system_prompt",
                    "content": self._stringify_content(msg.content),
                    "tool_calls": [],
                    "trace": [],
                    "model_name": "",
                    "metadata": system_meta,
                }
                break

        if effective_mode == AGENT_LOOP_SIMPLE:
            yield from self._stream_simple_answer(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                message_service=message_service,
                citation_map=turn_citation_map,
                latency_marks=latency_marks,
                turn_started_at=turn_started_at,
            )
            _launch_auto_rename(self, user_id=user_id, session_id=session_id)
            return

        yield from self._stream_events(
            messages=messages,
            user_id=user_id,
            session_id=session_id,
            message_service=message_service,
            initial_plan=initial_plan,
            graph=self.graphs[effective_mode],
            agent_mode=effective_mode,
            agent_access_mode=effective_access_mode,
            long_term_memory_enabled=long_term_memory_enabled,
            citation_map=turn_citation_map,
            prompt=prompt,
            latency_marks=latency_marks,
            turn_started_at=turn_started_at,
            context_overhead_tokens=runtime_system_tokens,
            allow_child_spawn=allow_child_spawn,
        )
        _launch_auto_rename(self, user_id=user_id, session_id=session_id)
    def _stream_events(
        self,
        *,
        messages: list[BaseMessage],
        user_id: str,
        session_id: str,
        message_service: MessageService | None = None,
        initial_plan: dict[str, Any] | None = None,
        graph: CompiledStateGraph | None = None,
        agent_mode: str = AGENT_LOOP_PLAN,
        agent_access_mode: str = "sandbox",
        citation_map: dict[str, Any] | None = None,
        prompt: str = "",
        run_id: str | None = None,
        allow_child_spawn: bool = True,
        latency_marks: dict[str, float] | None = None,
        turn_started_at: float | None = None,
        long_term_memory_enabled: bool = True,
        context_overhead_tokens: int = 0,
    ) -> Iterator[dict[str, Any]]:
        """
        使用给定 LangChain messages 执行图并逐节点产出 dict 事件。

        统一的流式核心,HTTP 和 gRPC 共用此方法。
        支持通过 GeneratorExit (客户端断开 SSE) 或 cancel_session() 中断执行,
        中断时会保存当前已流式输出的部分内容到 agent_messages。

        messages: 已构建好的本轮初始上下文。
        user_id: 用户 ID。
        session_id: 会话 ID。
        message_service: 可选消息服务;传入时会持久化图节点新增消息。
        initial_plan: 可选上一轮的探索状态,跨轮注入。
        graph: 本轮使用的 LangGraph 图。
        agent_mode: 本轮 Agent Loop 模式。
        """

        # 在图启动前一次性读取用户 LLM 配置,存入 state 避免重入时重复查 DB
        llm_config = self._get_user_llm_config(user_id)
        inputs: dict[str, Any] = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "trace": [],
            "llm_config": llm_config,
            "long_term_memory_enabled": long_term_memory_enabled,
            "compression_state": self._load_session_compression_state(session_id),
            "context_overhead_tokens": max(context_overhead_tokens, 0),
            "context_tool_tokens": ContextBuilder.estimate_tool_definition_tokens(
                self.tools,
                model_name=str((llm_config or {}).get("model_name") or self.config.model.model_name or "") or None,
            ),
        }
        if self.task_list_service is not None:
            inputs["task_list"] = self.task_list_service.get_task_list(session_id)
        if self.skill_service is not None:
            try:
                skill_prompt = prompt or self._last_human_text(messages)
                skill_index = self.skill_service.select_skill_candidates(user_id=user_id, prompt=skill_prompt)
                inputs["skill_index"] = skill_index
                inputs["active_skills"] = self.skill_service.route_skills(
                    user_id=user_id,
                    prompt=skill_prompt,
                    llm_config=llm_config,
                    task_scheduler=self.task_scheduler,
                    candidate_skills=skill_index,
                )
                if self.activity_service is not None and inputs["active_skills"]:
                    self.activity_service.record_skills(user_id=user_id, skills=inputs["active_skills"])
            except Exception:
                logger.exception("Skill routing failed | user=%s session=%s", user_id, session_id)
                inputs["skill_index"] = []
                inputs["active_skills"] = []
        if initial_plan is not None:
            inputs["plan"] = initial_plan
        effective_run_id = run_id or f"agent_run_{uuid4().hex}"
        if self.change_service is not None:
            self.change_service.start_run(user_id=user_id, session_id=session_id, run_id=effective_run_id)
        runtime_config = {"configurable": {"thread_id": effective_run_id}}
        active_graph = graph or self.graphs.get(agent_mode) or self.graph
        effective_access_mode = normalize_agent_access_mode(agent_access_mode)
        retrieval_service = None
        if self.context_builder is not None:
            retrieval_service = self.context_builder.retrieval_service

        cancel_event = self.cancellation_runtime.register(session_id)
        inputs["cancel_event"] = cancel_event

        token_queue: queue_module.Queue[dict[str, Any]] = queue_module.Queue()
        _streamed_content: list[str] = [""]
        _turn_traces: list[dict[str, Any]] = []
        _citation_map: dict[str, Any] = dict(citation_map or {})
        _latest_plan: dict[str, Any] | None = initial_plan
        _last_sent_content: list[str] = [""]
        _last_sent_thinking: list[str] = [""]
        _last_node_completed_at: list[float] = [time.perf_counter()]
        _first_agent_delta_sent = False

        def latency_metadata(extra: dict[str, float] | None = None) -> dict[str, Any]:
            """Attach backend latency diagnostics without affecting agent behavior."""

            if turn_started_at is None:
                return {}
            timings = dict(latency_marks or {})
            if extra:
                timings.update(extra)
            timings["backend_elapsed_ms"] = max(0.01, round((time.perf_counter() - turn_started_at) * 1000, 2))
            return {"latency": timings}


        def on_token(cumulative_text: str) -> None:
            content = self._sanitize_streaming_content(
                cumulative_text,
                min_chars=self.config.model.streaming_sanitize_min_chars,
            )
            _streamed_content[0] = content
            if content != cumulative_text:
                # 命中 JSON/内部标记拦截:跳过本轮增量,不断流、不更新基线,
                # 后续恢复正常文本时仍按原文前向切片发送。
                return
            prev = _last_sent_content[0]
            delta = content[len(prev):] if len(content) > len(prev) else ""
            _last_sent_content[0] = content
            if not delta:
                return
            token_queue.put({
                "type": "token",
                "node": "agent",
                "content": delta,
                "tool_calls": [],
                "trace": [],
            })

        def on_thinking(cumulative_text: str) -> None:
            """接收模型思考文本累积内容,按前向切片把增量放入队列供 SSE 推送。

            思考文本与正文独立:不经过 streaming_sanitize(那是针对正文的 JSON/内部标记
            拦截),只做增量切分,保证 Think 条实时渲染完整思考过程。
            """
            prev = _last_sent_thinking[0]
            delta = cumulative_text[len(prev):] if len(cumulative_text) > len(prev) else ""
            _last_sent_thinking[0] = cumulative_text
            if not delta:
                return
            token_queue.put({
                "type": "thinking",
                "node": "agent",
                "content": delta,
                "tool_calls": [],
                "trace": [],
            })

        graph_error: Exception | None = None

        def on_tool_trace(trace: dict[str, Any]) -> None:
            token_queue.put({"type": "tool_trace", "trace": trace})

        def on_planner_content(cumulative_text: str) -> None:
            token_queue.put({
                "type": "planner_content",
                "node": "planner",
                "content": cumulative_text,
                "tool_calls": [],
                "trace": [],
            })

        def on_observation_content(cumulative_text: str) -> None:
            token_queue.put({
                "type": "observation_content",
                "node": "observation",
                "content": cumulative_text,
                "tool_calls": [],
                "trace": [],
            })

        compression_active = [False]

        context_snapshots: list[dict[str, Any]] = []

        def on_context_mirror(snapshot: dict[str, Any]) -> None:
            """Persist and stream every exact model request made during this user turn."""

            normalized_snapshot = {
                **snapshot,
                "call_index": len(context_snapshots) + 1,
            }
            context_snapshots.append(normalized_snapshot)
            messages = normalized_snapshot.get("messages", [])
            model_name = str((llm_config or {}).get("model_name") or self.config.model.model_name or "") or None
            budget = normalized_snapshot.get("context_budget")
            if isinstance(budget, dict):
                usage = {
                    "current_tokens": int(budget.get("final_input_tokens", 0)),
                    "max_context_tokens": int(budget.get("effective_window_tokens", 0)),
                    "input_budget_tokens": int(budget.get("input_budget_tokens", 0)),
                    "trigger_tokens": int(budget.get("compression_trigger_tokens", 0)),
                    "target_tokens": int(budget.get("compression_target_tokens", 0)),
                    "capacity_source": budget.get("capacity_source", ""),
                    "policy_version": budget.get("policy_version", ""),
                }
            else:
                usage = ContextBuilder.context_usage_from_serialized(
                    messages,
                    config=self.config,
                    model_name=model_name,
                    extra_tokens=ContextBuilder.estimate_tool_definition_tokens(self.tools, model_name=model_name),
                )
            self._persist_session_state_value(session_id, "context_usage", usage)
            self._persist_session_state_value(session_id, "context_snapshots", context_snapshots)
            token_queue.put({
                "type": "context_mirror",
                "snapshot": normalized_snapshot,
                "snapshots": list(context_snapshots),
                "context_usage": usage,
            })

        def on_context_compression(event: dict[str, Any]) -> None:
            compression_active[0] = event.get("event") == "compression_started"
            if event.get("event") in {"compression_applied", "compression_failed"} and event.get("max_context_tokens"):
                self._persist_session_state_value(
                    session_id,
                    "context_usage",
                    {
                        "current_tokens": event.get("tokens_after", event.get("tokens_before", 0)),
                        "max_context_tokens": event.get("max_context_tokens", 0),
                        "trigger_tokens": event.get("trigger_tokens", 0),
                        "target_tokens": event.get("target_tokens", 0),
                    },
                )
            token_queue.put({"type": "context_compression", "event": event})

        def on_task_list_update(task_list: dict[str, Any] | None) -> None:
            token_queue.put({"type": "task_list_updated", "task_list": task_list})

        def on_markdown_html_visualization(visualization: dict[str, Any]) -> None:
            token_queue.put({"type": "markdown_html_visualization", "visualization": visualization})

        def run_graph() -> None:
            nonlocal graph_error
            set_tool_runtime(
                config=self.config,
                user_id=user_id,
                session_id=session_id,
                run_id=effective_run_id,
                retrieval_service=retrieval_service,
                unified_search_service=self.unified_search_service,
                task_list_service=self.task_list_service,
                change_service=self.change_service,
                skill_service=self.skill_service,
                settings_service=self.settings_service,
                tool_services=self.tool_services,
                message_service=message_service,
                database_engine=getattr(self.settings_service, "engine", None),
                citation_map=_citation_map,
                agent_access_mode=effective_access_mode,
                long_term_memory_enabled=long_term_memory_enabled,
                child_agent_spawner=(
                    None
                    if not allow_child_spawn
                    else lambda **kwargs: self._spawn_child_from_runtime(
                        parent_run_id=effective_run_id,
                        user_id=user_id,
                        session_id=session_id,
                        parent_access_mode=effective_access_mode,
                        **kwargs,
                    )
                ),
                child_agent_waiter=(
                    None
                    if not allow_child_spawn
                    else lambda **kwargs: self._wait_child_agents_from_runtime(
                        parent_run_id=effective_run_id,
                        session_id=session_id,
                        **kwargs,
                    )
                ),
                child_agent_continuation=(
                    None
                    if not allow_child_spawn
                    else lambda **kwargs: self._continue_child_from_runtime(
                        parent_run_id=effective_run_id,
                        user_id=user_id,
                        session_id=session_id,
                        **kwargs,
                    )
                ),
            )
            set_agent_token_callback(on_token)
            set_agent_thinking_callback(on_thinking)
            set_tool_trace_callback(on_tool_trace)
            set_planner_content_callback(on_planner_content)
            set_observation_content_callback(on_observation_content)
            set_context_mirror_callback(on_context_mirror)
            set_context_compression_callback(on_context_compression)
            set_task_list_callback(on_task_list_update)
            set_markdown_html_visualization_callback(on_markdown_html_visualization)
            set_plan_state(initial_plan)
            try:
                for event in active_graph.stream(inputs, config=runtime_config, stream_mode="updates"):
                    if cancel_event.is_set():
                        break
                    token_queue.put({"type": "node", "event": event})
            except Exception as exc:
                graph_error = exc
                token_queue.put({"type": "error", "error": exc})
            finally:
                clear_agent_token_callback()
                clear_agent_thinking_callback()
                clear_tool_trace_callback()
                clear_planner_content_callback()
                clear_observation_content_callback()
                clear_context_mirror_callback()
                clear_context_compression_callback()
                clear_task_list_callback()
                clear_markdown_html_visualization_callback()
                clear_plan_state()
                clear_tool_runtime()
                token_queue.put({"type": "done"})

        graph_thread = threading.Thread(target=run_graph, daemon=True, name=f"graph-{session_id[:12]}")
        graph_thread.start()

        try:
            while True:
                try:
                    item = token_queue.get(timeout=self.config.limits.agent_stream_queue_poll_seconds)
                except queue_module.Empty:
                    child_event_payloads = self._drain_child_agent_event_payloads(
                        session_id=session_id,
                    )
                    if child_event_payloads:
                        for payload in child_event_payloads:
                            yield payload
                        continue
                    if cancel_event.is_set():
                        if compression_active[0]:
                            yield {
                                "node": "compress",
                                "type": "compression_cancelled",
                                "content": "",
                                "tool_calls": [],
                                "trace": [],
                                "model_name": self._model_name_for_node("compress"),
                                "metadata": {"compression": {"event": "compression_cancelled"}},
                            }
                        partial = _streamed_content[0]
                        if message_service is not None and partial:
                            try:
                                message_service.create_message(
                                    MessageCreate(
                                        session_id=session_id,
                                        user_id=user_id,
                                        role="assistant",
                                        content=partial,
                                        metadata_json={"node": "agent", "source": "interrupted"},
                                    )
                                )
                                logger.info("已保存中断时的部分输出 | session=%s len=%d", session_id, len(partial))
                            except Exception:
                                logger.exception("保存中断输出失败 | session=%s", session_id)
                        break
                    continue

                item_type = item.get("type")

                if item_type == "done":
                    for payload in self._drain_child_agent_event_payloads(
                        session_id=session_id,
                    ):
                        yield payload
                    final_plan = get_plan_state()
                    self._persist_session_plan(session_id, final_plan)
                    break

                if item_type == "error":
                    error_msg = str(item["error"])
                    # 提取对用户友好的错误信息,去除冗余的技术细节
                    friendly_msg = extract_friendly_error(error_msg)
                    logger.warning("图执行出错 | user=%s session=%s error=%s", user_id, session_id, friendly_msg)
                    if message_service is not None:
                        try:
                            message_service.create_message(
                                MessageCreate(
                                    session_id=session_id,
                                    user_id=user_id,
                                    role="assistant",
                                    content=friendly_msg,
                                    metadata_json={"node": "error", "source": "api_content_filter"},
                                )
                            )
                            logger.info("已保存错误消息到数据库 | session=%s", session_id)
                        except Exception:
                            logger.exception("保存错误消息失败 | session=%s", session_id)
                    yield {
                        "node": "error",
                        "content": friendly_msg,
                        "error": friendly_msg,
                        "tool_calls": [],
                        "trace": [],
                        "model_name": "",
                    }
                    break

                if item_type == "token":
                    extra_latency = None
                    if not _first_agent_delta_sent:
                        _first_agent_delta_sent = True
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
                        "node": item.get("node", "agent"),
                        "content": item.get("content", ""),
                        "tool_calls": item.get("tool_calls", []),
                        "trace": item.get("trace", []),
                        "model_name": self._model_name_for_node(item.get("node", "agent")),
                        # 只有首个正文增量携带一次首字延迟；普通 token 不再制造
                        # 每次都变化的 metadata，避免前端绕过文本缓冲逐 token 重绘。
                        "metadata": latency_metadata(extra_latency) if extra_latency else {},
                    }

                elif item_type == "thinking":
                    # 模型思考文本增量,前端据此实时渲染 DSH 风格 Think 条。
                    yield {
                        "type": "thinking",
                        "node": item.get("node", "agent"),
                        "content": item.get("content", ""),
                        "tool_calls": item.get("tool_calls", []),
                        "trace": item.get("trace", []),
                        "model_name": self._model_name_for_node(item.get("node", "agent")),
                        # 思考 token 只承载文本增量，完整耗时由终态事件统一报告。
                        "metadata": {},
                    }

                elif item_type == "tool_trace":
                    trace = item.get("trace", {})
                    if trace:
                        trace_citation_map = trace.get("citation_map")
                        if isinstance(trace_citation_map, dict):
                            _citation_map.update(trace_citation_map)
                        if "model_name" not in trace:
                            trace["model_name"] = self._model_name_for_node(trace.get("node", "action"))
                        trace["ts"] = time.time()
                        trace["_streamed_trace"] = True
                        _turn_traces.append(trace)
                    public_trace = (
                        {key: value for key, value in trace.items() if not key.startswith("_")}
                        if trace
                        else {}
                    )
                    yield {
                        "node": trace.get("node", "action"),
                        "content": "",
                        "tool_calls": [],
                        "trace": [public_trace] if public_trace else [],
                        "model_name": self._model_name_for_node(trace.get("node", "action")),
                        "metadata": {
                            **({"citation_map": dict(_citation_map)} if _citation_map else {}),
                            **latency_metadata(),
                        },
                    }

                elif item_type == "planner_content":
                    yield {
                        "node": "planner",
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": self._model_name_for_node("planner"),
                    }

                elif item_type == "observation_content":
                    yield {
                        "node": "observation",
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": self._model_name_for_node("observation"),
                    }

                elif item_type == "context_mirror":
                    yield {
                        "node": "agent",
                        "type": "context_mirror",
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": self._model_name_for_node("agent"),
                        "context_request": item.get("snapshot", {}),
                        "context_snapshots": item.get("snapshots", []),
                        "context_messages": (item.get("snapshot") or {}).get("messages", []),
                        "metadata": {"context_usage": item.get("context_usage", {})},
                    }

                elif item_type == "context_compression":
                    event = item.get("event", {})
                    yield {
                        "node": "compress",
                        "type": str(event.get("event") or "context_compression"),
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": self._model_name_for_node("compress"),
                        "metadata": {
                            "compression": event,
                            "context_usage": {
                                "current_tokens": event.get("tokens_after", event.get("tokens_before", 0)),
                                "max_context_tokens": event.get("max_context_tokens", 0),
                                "trigger_tokens": event.get("trigger_tokens", 0),
                                "target_tokens": event.get("target_tokens", 0),
                            },
                        },
                    }

                elif item_type == "task_list_updated":
                    yield {
                        "node": "task_list",
                        "type": "task_list_updated",
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": "",
                        "task_list": item.get("task_list"),
                    }

                elif item_type == "markdown_html_visualization":
                    yield {
                        "node": "visualization",
                        "type": "markdown_html_visualization",
                        "content": "",
                        "tool_calls": [],
                        "trace": [],
                        "model_name": "",
                        "visualization": item.get("visualization"),
                    }

                elif item_type == "node":
                    event = item["event"]
                    for node_name, state_update in event.items():
                        completed_at = time.perf_counter()
                        duration_ms = max(0.01, round(max(0.0, completed_at - _last_node_completed_at[0]) * 1000, 2))
                        _last_node_completed_at[0] = completed_at
                        logger.debug("图节点执行 | node=%s user=%s session=%s", node_name, user_id, session_id)
                        node_traces = state_update.get("trace", []) if state_update else []
                        if isinstance(state_update, dict) and isinstance(state_update.get("compression_state"), dict):
                            self._persist_session_compression_state(session_id, state_update["compression_state"])
                        fresh_traces: list[dict[str, Any]] = []
                        if node_traces:
                            _now = time.time()
                            for t in node_traces:
                                if t.get("node") != node_name:
                                    continue
                                already_streamed = bool(t.get("_streamed_trace"))
                                if "ts" in t and not (already_streamed and not t.get("_persisted_trace")):
                                    continue
                                trace_citation_map = t.get("citation_map")
                                if isinstance(trace_citation_map, dict):
                                    _citation_map.update(trace_citation_map)
                                if "model_name" not in t:
                                    t["model_name"] = self._model_name_for_node(node_name)
                                if "ts" not in t:
                                    t["ts"] = _now
                                if not already_streamed:
                                    if t.get("event") == "tool_call_start":
                                        t["duration_ms"] = 0
                                    elif "duration_ms" not in t:
                                        t["duration_ms"] = duration_ms
                                t["_persisted_trace"] = True
                                fresh_traces.append(t)
                            _turn_traces.extend(fresh_traces)
                        if isinstance(state_update, dict) and "plan" in state_update:
                            _latest_plan = state_update["plan"]
                        public_fresh_traces = [
                            {key: value for key, value in trace.items() if not key.startswith("_")}
                            for trace in fresh_traces
                        ]
                        output_state_update = (
                            {**state_update, "trace": public_fresh_traces}
                            if isinstance(state_update, dict)
                            else state_update
                        )
                        change_snapshot: dict[str, Any] | None = None
                        if message_service is not None:
                            change_snapshot = self._save_state_update_messages(
                                message_service=message_service,
                                user_id=user_id,
                                session_id=session_id,
                                node_name=node_name,
                                state_update=output_state_update,
                                turn_traces=public_fresh_traces,
                                citation_map=_citation_map,
                                run_id=effective_run_id,
                            )
                        payload = self._build_stream_payload(
                            node_name=node_name,
                            state_update=output_state_update,
                            citation_map=_citation_map,
                        )
                        payload["model_name"] = self._model_name_for_node(node_name)
                        payload_metadata = payload.get("metadata")
                        if isinstance(payload_metadata, dict):
                            payload["metadata"] = {**payload_metadata, **latency_metadata()}
                        else:
                            payload["metadata"] = latency_metadata()
                        # The persisted final message receives this snapshot above, but the
                        # active chat must receive it in the same SSE turn as well.
                        if change_snapshot is not None:
                            payload["metadata"]["change_snapshot"] = change_snapshot
                        yield payload
        except GeneratorExit:
            cancel_event.set()
            partial = _streamed_content[0]
            if message_service is not None and partial:
                try:
                    message_service.create_message(
                        MessageCreate(
                            session_id=session_id,
                            user_id=user_id,
                            role="assistant",
                            content=partial,
                            metadata_json={"node": "agent", "source": "interrupted"},
                        )
                    )
                    logger.info("已保存中断时的部分输出 | session=%s len=%d", session_id, len(partial))
                except Exception:
                    logger.exception("保存中断输出失败 | session=%s", session_id)
            raise
        finally:
            cancel_event.set()
            self.cancellation_runtime.clear(session_id)
            clear_agent_token_callback()
            clear_tool_trace_callback()
            clear_planner_content_callback()
            clear_observation_content_callback()
            clear_task_list_callback()
            clear_plan_state()
            clear_tool_runtime()
            graph_thread.join(timeout=self.config.limits.agent_graph_join_timeout_seconds)
