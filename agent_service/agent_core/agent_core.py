"""
AgentCore 对外入口模块。

功能说明:
本文件提供 `AgentCore` 类,作为 Agent 微服务核心能力的对外门面。它负责接收
`AgentConfig`、加载默认内置工具、构建 LangGraph 图、输出图结构 Mermaid 文件,
启动时检查并下载 Embedding/ReRank 本地模型,并对外提供 Agent 执行入口。具体节点逻辑不写在本文件中,而是由
`AgentGraphBuilder` 装配 `compress`、`planner`、`model_decision`、`tool_call`、`observation` 和 `summary` 等节点。

执行能力:
`stream_run()` 提供 SSE 风格的原始流式输出,适合接口层直接转发给前端。
`run_once()` 在 `stream_run()` 之上整理结构化结果,包含图结构、原始 chunks、
节点事件、最终输出等字段,适合测试脚本、调试接口和后续前端观测面板使用。

可观测能力:
`parse_stream_chunks()` 负责把 SSE 字符串解析成节点事件列表。
`extract_final_output()` 负责从节点事件中提取最终智能体回复。
`build_human_readable_process()` 负责把节点事件格式化为给人阅读的可观测过程,
但不暴露模型内部不可观测的思维链。

Session 入口:
`run_session_prompt()` 是面向主服务和 gRPC 的正式 session 级入口。它通过
ContextBuilder 构建同一 session 的短期上下文,执行 Agent 图,并通过
MessageService 保存本轮 user、assistant 和 tool 消息。

使用说明:
调用方应显式传入配置对象:

config = AgentConfig.load_config()
agent = AgentCore(config=config)
for chunk in agent.stream_run(prompt="你好", user_id="u1", session_id="s1"):
    ...

result = agent.run_once(prompt="你好", user_id="u1", session_id="s1")
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

# 保留原模块级导入路径，实际错误恢复实现已迁入 runtime/error_recovery.py。
_extract_friendly_error = extract_friendly_error

from agent_service.agent_core.runtime.child_agent_runtime import ChildAgentRuntimeMixin
from agent_service.agent_core.runtime.graph_runner import GraphRunnerMixin
from agent_service.agent_core.runtime.session_runtime import SessionRuntimeMixin
from agent_service.agent_core.runtime.model_runtime import ModelRuntimeMixin
from agent_service.agent_core.runtime.stream_adapter import StreamAdapterMixin

logger = logging.getLogger(__name__)

CITATION_ANCHOR_PATTERN = re.compile(r"\[([A-Z]?\d+)\]")



class AgentCore(ChildAgentRuntimeMixin, GraphRunnerMixin, SessionRuntimeMixin, ModelRuntimeMixin, StreamAdapterMixin):
    """
    Agent 微服务核心入口。

    config: 由 `core.agent_config.AgentConfig.load_config()` 创建的显式配置对象。
    tools: 可选 LangChain 工具列表;为空时默认加载工具注册表中的内置工具。
    graph: 可选已编译图对象,主要用于测试时注入假图以避免真实模型请求。
    message_service: 可选消息服务,用于 session 级正式入口的消息持久化。
    context_builder: 可选上下文构建器,用于 session 级正式入口的短期上下文构建。
    session_service: 可选会话服务,用于跨轮持久化和恢复 Agent 探索状态。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        tools: Sequence[Any] | None = None,
        graph: CompiledStateGraph | None = None,
        message_service: MessageService | None = None,
        context_builder: ContextBuilder | None = None,
        attachment_service: SessionAttachmentService | None = None,
        task_scheduler: LLMTaskScheduler | None = None,
        session_service: Any = None,
        task_list_service: Any = None,
        change_service: Any = None,
        skill_service: Any = None,
        settings_service: Any = None,
    ) -> None:
        """保存配置、检查本地模型、构建或接收 LangGraph 图,并输出当前节点流程图。"""

        self.config = config
        logger.debug("AgentCore 初始化开始 | model=%s", config.model.model_name)
        self.message_service = message_service
        self.context_builder = context_builder
        self.attachment_service = attachment_service
        self.attachment_runtime = AttachmentRuntime(attachment_service)
        self.session_service = session_service
        self.task_list_service = task_list_service
        self.change_service = change_service
        self.skill_service = skill_service
        self.settings_service = settings_service
        self.unified_search_service: Any = None
        self.activity_service: Any = None
        self.tool_services: dict[str, Any] = {}
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(config, settings_service=settings_service)
        self.child_agent_manager = ChildAgentManager(
            config=config,
            event_callback=self._on_child_agent_event,
        )
        self.tool_registry = ToolRegistry.with_builtin_tools() if tools is None else None
        self.tool_executor = ToolExecutor(registry=self.tool_registry) if self.tool_registry is not None else None
        self.cancellation_runtime = CancellationRuntime()
        self._session_state_lock = threading.Lock()
        self.tools = list(tools) if tools is not None else self.tool_registry.to_langchain_tools()
        if message_service is not None:
            self._get_context_builder(message_service=message_service)
        safety_service = SafetyService(config=config, task_scheduler=self.task_scheduler)
        self.safety_service = safety_service
        plan_builder = AgentGraphBuilder(
            config=config,
            tools=self.tools,
            tool_executor=self.tool_executor,
            task_scheduler=self.task_scheduler,
            safety_service=safety_service,
            settings_service=settings_service,
        )
        react_builder = AgentGraphBuilder(
            config=config,
            tools=self.tools,
            tool_executor=self.tool_executor,
            task_scheduler=self.task_scheduler,
            safety_service=safety_service,
            settings_service=settings_service,
        )
        self.graph: CompiledStateGraph = graph or plan_builder.build(mode=AGENT_LOOP_PLAN)
        self.graphs: dict[str, CompiledStateGraph] = {
            AGENT_LOOP_PLAN: self.graph,
            AGENT_LOOP_REACT: graph or react_builder.build(mode=AGENT_LOOP_REACT),
        }
        self.graph_diagram_paths = {
            AGENT_LOOP_PLAN: draw_agent_graph(
                compiled_graph=self.graphs[AGENT_LOOP_PLAN],
                output_path=config.storage.project_root / "agent_graph.mmd",
                branch_labels=plan_builder.branch_labels,
            ),
            AGENT_LOOP_REACT: draw_agent_graph(
                compiled_graph=self.graphs[AGENT_LOOP_REACT],
                output_path=config.storage.project_root / "agent_graph_react.mmd",
                branch_labels=react_builder.branch_labels,
            ),
        }
        self.graph_diagram_path = self.graph_diagram_paths[AGENT_LOOP_PLAN]






















    def cancel_session(self, session_id: str) -> None:
        """取消指定 session 正在执行的图,保存部分输出。"""

        if self.cancellation_runtime.cancel(session_id):
            logger.info("收到取消请求 | session=%s", session_id)

    def close(self) -> None:
        """释放 AgentCore 持有的调度器等资源。"""

        logger.info("AgentCore 正在释放调度器资源...")
        self.cancellation_runtime.cancel_all()
        self.child_agent_manager.close()
        self.task_scheduler.shutdown()
        logger.info("AgentCore 资源释放完成")














    @staticmethod
    def _serialize_runtime_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """序列化直答路径实际发送给模型的上下文,供观测面板展示。"""

        role_map = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
        result: list[dict[str, Any]] = []
        for msg in messages:
            result.append(
                {
                    "role": role_map.get(msg.type, msg.type),
                    "content": AgentCore._stringify_content(getattr(msg, "content", "")),
                }
            )
        return result


    @staticmethod
    def _message_to_create(
        *,
        message: BaseMessage,
        user_id: str,
        session_id: str,
        node_name: str,
        turn_traces: list[dict[str, Any]] | None = None,
        citation_map: dict[str, Any] | None = None,
    ) -> MessageCreate | None:
        """
        将 LangChain message 转换为 MessageCreate。

        message: LangGraph 节点返回的新增消息。
        user_id: 用户 ID。
        session_id: 会话 ID。
        node_name: 产生该消息的节点名称。
        turn_traces: 本轮累积的 trace,附加到 assistant 消息 metadata 中。
        """

        metadata: dict[str, Any] = {"node": node_name, "source": "agent_graph"}
        if turn_traces:
            metadata["trace"] = turn_traces
        if isinstance(message, AIMessage):
            reasoning_content = (message.additional_kwargs or {}).get("reasoning_content")
            if isinstance(reasoning_content, list):
                # 流式合并时 reasoning_content 可能累积为片段列表,统一拼接为字符串。
                reasoning_content = "".join(str(part) for part in reasoning_content)
            if reasoning_content:
                metadata["reasoning_content"] = reasoning_content
            stream_diagnostics = (message.additional_kwargs or {}).get("stream_diagnostics")
            if isinstance(stream_diagnostics, dict):
                # 只保存字符计数和布尔诊断，不记录用户正文。
                metadata["stream_diagnostics"] = stream_diagnostics
            content = AgentCore._sanitize_agent_output(AgentCore._stringify_content(message.content))
            content = AgentCore._drop_unmapped_citation_anchors(content, citation_map)
            content = AgentCore._insert_missing_citation_anchors_inline(content, citation_map)
            metadata.update(AgentCore._build_citation_metadata(content, citation_map))
            if not content.strip() and not list(message.tool_calls or []):
                return None
            return MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=content,
                tool_calls_json=list(message.tool_calls or []),
                metadata_json=metadata,
            )
        if isinstance(message, ToolMessage):
            tool_result = (message.additional_kwargs or {}).get("tool_result")
            if isinstance(tool_result, dict):
                metadata["tool_result"] = tool_result
            return MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="tool",
                content=AgentCore._stringify_content(message.content),
                tool_call_id=message.tool_call_id,
                metadata_json=metadata,
            )
        if isinstance(message, HumanMessage):
            return MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="user",
                content=AgentCore._stringify_content(message.content),
                metadata_json=metadata,
            )
        if isinstance(message, SystemMessage):
            rag_metrics = (getattr(message, "additional_kwargs", {}) or {}).get("rag_metrics")
            if rag_metrics:
                metadata["rag_metrics"] = rag_metrics
            recall_details = (getattr(message, "additional_kwargs", {}) or {}).get("recall_details")
            if recall_details:
                metadata["recall_details"] = recall_details
            return MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="system",
                content=AgentCore._stringify_content(message.content),
                metadata_json=metadata,
            )
        return None
