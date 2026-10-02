"""AgentCore child_agent_runtime 职责实现。

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
from agent_service.schemas.message import MessageCreate
from agent_service.scripts.draw_agent_graph import draw_agent_graph
from agent_service.services.memory.context_builder import ContextBuilder
from agent_service.services.child_agent import ChildAgentContract, ChildAgentEvent, ChildAgentManager, ChildAgentStatus
from agent_service.services.message.service import MessageService
from agent_service.services.session.service import SessionService
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

def _resolve_child_agent_category_template(category: str, prompts: AgentConfig.PromptConfig) -> str:
    """把子 Agent 类别解析为注入 prompt 的角色设定模板。

    命中预置 key 用对应模板;空类别返回空串不注入;其他自定义字符串视为角色描述。
    """

    text = (category or "").strip()
    if not text:
        return ""
    return prompts.child_agent_category_prompts.get(
        text,
        prompts.child_agent_custom_role_template.format(category=text),
    )

class ChildAgentRuntimeMixin:
    def list_child_agents(self, parent_run_id: str) -> list[dict[str, Any]]:
        """返回指定父 Agent 的子 Agent 状态快照。"""

        return [self._child_record_to_dict(record) for record in self.child_agent_manager.list_children(parent_run_id)]
    def list_child_agents_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """返回指定会话内主 Agent 创建的全部子 Agent,供前端面板查询。"""

        records = self.child_agent_manager.list_children_for_session(session_id)
        active_children = [self._child_record_to_dict(record) for record in records]
        saved_children = self._load_session_state_list(session_id, "child_agents")
        event_children = self._load_child_agents_from_messages(session_id, fallback_children=saved_children)
        # Live records win so the panel never renders a stale terminal status while a child is running.
        children_by_run_id = {
            str(child.get("run_id") or ""): self._with_child_conversation_session(session_id, child)
            for child in event_children
        }
        children_by_run_id.update({child["run_id"]: child for child in active_children})
        return list(children_by_run_id.values())

    def _load_child_agents_from_messages(
        self, session_id: str, *, fallback_children: Sequence[dict[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        """正式生命周期事件优先；快照与旧工具返回仅补齐历史缺失字段。"""

        if self.session_service is None:
            return list(fallback_children)
        session = self.session_service.get_session(session_id)
        message_service = self._get_message_service()
        if session is None or message_service is None:
            return list(fallback_children)
        children = {str(child.get("run_id") or ""): child for child in fallback_children}
        authoritative_runs = set(children)
        messages = message_service.list_session_messages(
            user_id=session.user_id,
            session_id=session_id,
            limit=None,
            exclude_roles=None,
        )
        for message in messages:
            candidate: dict[str, Any] | None = None
            if message.role == "tool":
                try:
                    parsed = json.loads(message.content)
                    candidate = parsed if isinstance(parsed, dict) and parsed.get("run_id") else None
                    if candidate is not None and str(candidate["run_id"]) in authoritative_runs:
                        candidate = {**candidate, **children[str(candidate["run_id"])]}
                except (json.JSONDecodeError, TypeError):
                    candidate = None
            metadata = message.metadata_json or {}
            event = metadata.get("child_agent_event") if isinstance(metadata, dict) else None
            child = event.get("child") if isinstance(event, dict) else None
            if isinstance(child, dict) and child.get("run_id"):
                candidate = {**(candidate or children.get(str(child["run_id"]), {})), **child}
                authoritative_runs.add(str(child["run_id"]))
            if candidate is None:
                continue
            run_id = str(candidate.get("run_id") or "")
            children[run_id] = {**children.get(run_id, {}), **candidate}
        return list(children.values())
    def stop_child_agent(self, run_id: str) -> bool:
        """向指定子 Agent 发送停止信号。"""

        return self.child_agent_manager.stop(run_id)
    def update_child_agent(self, run_id: str, update: dict[str, Any]) -> None:
        """向指定子 Agent 下一次安全检查点投递上下文更新。"""

        self.child_agent_manager.update_context(run_id, update)

    def claim_child_agent_completion_wakeup(self, *, run_id: str, user_id: str, session_id: str) -> bool:
        """校验归属后原子领取一个子 Agent Turn 的终态唤醒。"""

        record = self.child_agent_manager.get(run_id)
        if record is None:
            raise KeyError(f"子 Agent {run_id} 不存在。")
        if record.contract.user_id != user_id or record.contract.session_id != session_id:
            raise PermissionError(f"当前会话不能领取子 Agent {run_id} 的完成提醒。")
        return self.child_agent_manager.claim_completion_wakeup(run_id)

    @staticmethod
    def _child_record_to_dict(record: Any) -> dict[str, Any]:
        """将子 Agent 记录转为 REST/gRPC/前端共用的普通字典。"""

        result = record.result
        child = {
            "run_id": record.run_id,
            "conversation_session_id": SessionService.child_agent_session_id(
                record.contract.session_id,
                record.run_id,
            ),
            "parent_run_id": record.contract.parent_run_id,
            "goal": record.contract.goal,
            "category": record.contract.category,
            "name": record.contract.name,
            "provider": record.contract.provider,
            "workspace_root": record.contract.workspace_root,
            "mode": record.contract.mode,
            "status": record.status.value,
            "access_mode": record.effective_access_mode,
            "allowed_tools": sorted(record.effective_tools),
            "result": result.result if result is not None else None,
            "summary": result.summary if result is not None else "",
            "error": result.error if result is not None else None,
        }
        return ChildAgentRuntimeMixin._with_child_conversation_session(record.contract.session_id, child)
    @staticmethod
    def _with_child_conversation_session(session_id: str, child: dict[str, Any]) -> dict[str, Any]:
        """补全旧子对话 ID，并把旧 DSH 虚构 aliases 目录作为未知能力呈现。"""

        if child.get("provider") == "dsh" and any(
            str(tool).startswith("dsh.") for tool in child.get("allowed_tools") or []
        ):
            child = {**child, "allowed_tools": []}

        run_id = str(child.get("run_id") or "")
        if not run_id:
            return child
        return {
            **child,
            "conversation_session_id": SessionService.child_agent_session_id(session_id, run_id),
        }
    def _child_event_to_payload(self, event: ChildAgentEvent) -> dict[str, Any] | None:
        """将子 Agent 生命周期事件转换为前端可展示的 SSE payload。"""

        return {
            "type": "child_agent_event",
            "node": "child_agent",
            "content": self._child_event_content(event),
            "tool_calls": [],
            "trace": [],
            "model_name": "",
            "metadata": {
                "child_agent_event": {
                    "event_name": event.event_name,
                    "created_at": event.created_at,
                    "child": {
                        "run_id": event.run_id,
                        "parent_run_id": event.parent_run_id,
                        "goal": event.goal,
                        "category": event.category,
                        "name": event.name,
                        "provider": event.provider,
                        "mode": event.mode,
                        "status": event.status.value,
                        "access_mode": event.access_mode,
                        "allowed_tools": list(event.allowed_tools),
                        "result": event.result,
                        "summary": event.summary,
                        "error": event.error,
                    },
                },
            },
        }
    @staticmethod
    def _child_event_content(event: ChildAgentEvent) -> str:
        """生成子 Agent 事件的历史上下文正文。"""

        status_label = {
            "created": "已创建",
            "running": "开始任务",
            "completed": "完成任务",
            "failed": "任务失败",
            "stopped": "已停止",
        }.get(event.status.value, event.status.value)
        parts = [
            f"子 Agent {event.name or event.run_id} {status_label}: {event.goal}",
            f"类别={event.category or '通用'}",
            f"模式={event.mode}",
            f"权限={event.access_mode}",
            f"工具数={len(event.allowed_tools)}",
        ]
        if event.summary:
            parts.append(f"摘要={event.summary}")
        if event.error:
            parts.append(f"错误={event.error}")
        return " | ".join(parts)
    def _drain_child_agent_event_payloads(
        self,
        *,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """读取当前会话的子 Agent 事件队列,转为 SSE payload 列表。

        事件落库已由 `_on_child_agent_event` 回调负责,此处只负责主 Agent 流内推送,
        避免与回调重复入库。
        """

        payloads: list[dict[str, Any]] = []
        for event in self.child_agent_manager.drain_events_for_session(session_id):
            payload = self._child_event_to_payload(event)
            if payload is not None:
                payloads.append(payload)
        return payloads
    def _on_child_agent_event(self, event_name: str, record: Any) -> None:
        """ChildAgentManager 事件回调:子 Agent 每次状态变化立即落库。

        此回调在子 Agent 执行线程中同步调用,保证主 Agent SSE 流结束后后台子 Agent
        的完成事件也能持久化,前端刷新历史或轮询即可看到"已完成"提醒。
        """

        try:
            payload = self._record_to_payload(event_name, record)
            self._persist_child_agent_snapshot(record.contract.session_id, self._child_record_to_dict(record))
            self._save_child_agent_event_message(
                message_service=self._get_message_service(),
                user_id=record.contract.user_id,
                session_id=record.contract.session_id,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "子 Agent 事件落库失败 | event=%s run=%s", event_name, getattr(record, "run_id", "?")
            )
    @staticmethod
    def _record_to_payload(event_name: str, record: Any) -> dict[str, Any]:
        """从子 Agent 运行记录构造与 SSE payload 一致的 dict,供事件回调落库使用。"""

        result = record.result
        status_value = record.status.value if hasattr(record.status, "value") else str(record.status)
        status_label = {
            "created": "已创建",
            "running": "开始任务",
            "completed": "完成任务",
            "failed": "任务失败",
            "stopped": "已停止",
        }.get(status_value, status_value)
        parts = [
            f"子 Agent {record.contract.name or record.run_id} {status_label}: {record.contract.goal}",
            f"类别={record.contract.category or '通用'}",
            f"模式={record.contract.mode}",
            f"权限={record.effective_access_mode}",
            f"工具数={len(record.effective_tools)}",
        ]
        if result is not None and result.summary:
            parts.append(f"摘要={result.summary}")
        if result is not None and result.error:
            parts.append(f"错误={result.error}")
        return {
            "type": "child_agent_event",
            "node": "child_agent",
            "content": " | ".join(parts),
            "tool_calls": [],
            "trace": [],
            "model_name": "",
            "metadata": {
                "child_agent_event": {
                    "event_name": event_name,
                    "created_at": time.time(),
                    "child": {
                        "run_id": record.run_id,
                        "parent_run_id": record.contract.parent_run_id,
                        "goal": record.contract.goal,
                        "category": record.contract.category,
                        "name": record.contract.name,
                        "provider": record.contract.provider,
                        "workspace_root": record.contract.workspace_root,
                        "mode": record.contract.mode,
                        "status": status_value,
                        "access_mode": record.effective_access_mode,
                        "allowed_tools": sorted(record.effective_tools),
                        "result": result.result if result is not None else None,
                        "summary": result.summary if result is not None else "",
                        "error": result.error if result is not None else None,
                    },
                },
            },
        }
    @staticmethod
    def _save_child_agent_event_message(
        *,
        message_service: MessageService | None,
        user_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        """把子 Agent SSE 事件保存为可历史加载和导入导出的会话消息。"""

        if message_service is None:
            return
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = {
            **metadata,
            "node": "child_agent",
            "source": "child_agent_event",
        }
        message_service.create_message(
            MessageCreate(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=str(payload.get("content") or ""),
                metadata_json=metadata,
            )
        )
    def _spawn_child_from_runtime(
        self,
        *,
        parent_run_id: str,
        user_id: str,
        session_id: str,
        parent_access_mode: str,
        goal: str,
        mode: str = "background",
        allowed_tools: list[str] | None = None,
        access_mode: str = "sandbox",
        input_refs: list[str] | None = None,
        output_contract: dict[str, Any] | None = None,
        category: str | None = None,
        name: str | None = None,
        provider: str = "native",
        workspace_root: str = "",
    ) -> str:
        """由当前主 Agent 工具上下文创建真实子 Agent并返回 JSON 摘要。

        category: 子 Agent 能力模板 key(agent/explore/plan)或自定义角色描述,可留空。
        name: 子 Agent 名字;留空时按同类别的已有数量自动生成(plan1/agent1/...)。
        """

        if provider == "native" and (category or "").strip() == "coding":
            if self._dsh_coding_agent_enabled(user_id=user_id):
                raise PermissionError("DSH已启用，代码任务必须使用 agent_type=dsh，不能使用coding后备类型。")
            if not workspace_root.strip():
                raise ValueError("coding 子 Agent必须提供 workspace_root")
        if provider == "dsh":
            self._require_dsh_coding_agent_enabled(user_id=user_id)
            if not workspace_root.strip():
                raise ValueError("DSH 子 Agent必须提供 workspace_root")
        effective_category = "dsh" if provider == "dsh" and not (category or "").strip() else (category or "")
        effective_name = (name or "").strip() or self._auto_child_agent_name(parent_run_id, effective_category)
        from agent_service.tools.runtime_context import get_tool_runtime, child_tool_scope
        try:
            parent_registry = get_tool_runtime().tool_registry or self.tool_registry
        except RuntimeError:
            parent_registry = self.tool_registry
        parent_tools = frozenset(
            definition.name
            for definition in (parent_registry.definitions.values() if parent_registry else [])
            # 用户交互由主 Agent 承担；子对话没有输入框消费者，不能进入同步提问等待。
            if definition.name not in {"spawn_child_agent", "wait_for_child_agents", "continue_child_agent", "request_user_input"}
        )
        if provider == "dsh":
            # 真目录将在 Runtime 握手后发布；DSH 不继承 MW 原生工具名。
            parent_tools = frozenset()
        contract = ChildAgentContract(
            goal=goal,
            parent_run_id=parent_run_id,
            user_id=user_id,
            session_id=session_id,
            mode=mode,
            allowed_tools=(
                None
                if provider == "dsh"
                else frozenset(allowed_tools) if allowed_tools is not None else None
            ),
            access_mode=access_mode,
            input_refs=tuple(input_refs or []),
            output_contract=output_contract or {},
            category=effective_category,
            name=effective_name,
            provider=provider,
            workspace_root=workspace_root,
        )

        def execute_child(context: Any) -> str:
            """在独立线程中执行一轮无状态 Agent,禁止继续召唤子 Agent。

            类别模板作为角色设定注入 prompt 前,让子 Agent 一进入就知道自己是谁。
            """

            context.raise_if_stopped()
            template = _resolve_child_agent_category_template(context.category, self.config.prompts)
            prompt = f"{template}\n\n{context.goal}" if template else context.goal
            if context.workspace_root:
                prompt = f"{prompt}\n\n工作区绝对路径: {context.workspace_root}"
            with child_tool_scope(context.allowed_tools):
                if self.session_service is None:
                    result = self.run_once(
                        prompt=prompt,
                        user_id=context.user_id,
                        session_id=SessionService.child_agent_session_id(context.session_id, context.run_id),
                        agent_mode=context.agent_mode,
                        agent_access_mode=context.access_mode,
                        allow_child_spawn=False,
                    )
                    context.raise_if_stopped()
                    return str(result.get("final_output") or "")
                child_session = self.session_service.create_child_agent_session(
                    user_id=context.user_id,
                    parent_session_id=context.session_id,
                    run_id=context.run_id,
                    session_name=context.name or context.goal,
                )
                result = self.run_session_prompt(
                    prompt=prompt,
                    user_id=context.user_id,
                    session_id=child_session.session_id,
                    agent_mode=context.agent_mode,
                    agent_access_mode=context.access_mode,
                    allow_child_spawn=False,
                )
                context.raise_if_stopped()
                return str(result.get("final_output") or "")

        executor = execute_child
        if provider == "dsh":
            dsh_executor = getattr(self, "dsh_executor", None)
            if dsh_executor is None:
                raise RuntimeError("DSH 子 Agent执行器尚未初始化")
            executor = dsh_executor
        record = self.child_agent_manager.spawn(
            contract=contract,
            executor=executor,
            parent_tools=parent_tools,
            parent_access_mode=parent_access_mode,
        )
        if provider == "dsh" and self.session_service is not None:
            self.session_service.create_child_agent_session(
                user_id=user_id,
                parent_session_id=session_id,
                run_id=record.run_id,
                session_name=effective_name or goal,
                provider="dsh",
                dsh_session_id=dsh_executor.session_id_for_run(record.run_id),
                workspace_root=workspace_root,
                dsh_runtime_version=self.config.dsh.runtime_version,
            )
        return json.dumps(self._child_record_to_dict(record), ensure_ascii=False)
    def _auto_child_agent_name(self, parent_run_id: str, category: str | None) -> str:
        """按同类别的已有子 Agent 数量生成递增默认名(plan1/agent1/...)。"""

        base = (category or "").strip() or "child"
        siblings = self.child_agent_manager.list_children(parent_run_id)
        same_category = sum(1 for record in siblings if record.contract.category == (category or ""))
        return f"{base}{same_category + 1}"
    def _wait_child_agents_from_runtime(
        self,
        *,
        parent_run_id: str,
        session_id: str,
        run_ids: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        """由当前主 Agent 工具上下文等待一个后台子 Agent 结果并返回 JSON。"""

        wait_timeout = (
            self.config.limits.agent_child_wait_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        records = self.child_agent_manager.list_children(parent_run_id)
        current_run_ids = {record.run_id for record in records}
        use_session_scope = not records or bool(run_ids and not set(run_ids).issubset(current_run_ids))
        if use_session_scope:
            result = self.child_agent_manager.wait_for_children_for_session(
                session_id=session_id,
                run_ids=run_ids or [],
                timeout_seconds=wait_timeout,
            )
            records = self.child_agent_manager.list_children_for_session(session_id)
        else:
            result = self.child_agent_manager.wait_for_children(
                parent_run_id=parent_run_id,
                run_ids=run_ids or [],
                timeout_seconds=wait_timeout,
            )
        if run_ids:
            target_run_ids = set(run_ids)
            records = [record for record in records if record.run_id in target_run_ids]
        return json.dumps(
            {
                "result": (
                    {
                        "run_id": result.run_id,
                        "parent_run_id": result.parent_run_id,
                        "status": result.status.value,
                        "summary": result.summary,
                        "result": result.result,
                        "error": result.error,
                    }
                    if result is not None
                    else None
                ),
                "children": [self._child_record_to_dict(record) for record in records],
            },
            ensure_ascii=False,
        )

    def _continue_child_from_runtime(
        self,
        *,
        parent_run_id: str,
        user_id: str,
        session_id: str,
        run_id: str,
        prompt: str,
        mode: str = "background",
    ) -> str:
        """由原父 Agent在同一个 DSH Child Agent Conversation中提交后续 Turn。"""

        self._require_dsh_coding_agent_enabled(user_id=user_id)
        record = self.child_agent_manager.get(run_id)
        if record is None:
            child = next(
                (item for item in self.list_child_agents_for_session(session_id) if item.get("run_id") == run_id),
                None,
            )
            if child is None or child.get("provider") != "dsh":
                raise KeyError(f"当前会话不存在 DSH 子 Agent {run_id}")
            dsh_executor = getattr(self, "dsh_executor", None)
            if dsh_executor is None:
                raise RuntimeError("DSH 子 Agent执行器尚未初始化")
            status_value = str(child.get("status") or "completed")
            status = ChildAgentStatus(status_value) if status_value in {"completed", "failed", "stopped"} else ChildAgentStatus.FAILED
            record = self.child_agent_manager.restore(
                run_id=run_id,
                contract=ChildAgentContract(
                    goal=str(child.get("goal") or "继续代码任务"),
                    parent_run_id=str(child.get("parent_run_id") or parent_run_id),
                    user_id=user_id,
                    session_id=session_id,
                    mode=mode,
                    allowed_tools=frozenset(str(item) for item in child.get("allowed_tools") or []),
                    access_mode=str(child.get("access_mode") or "sandbox"),
                    category=str(child.get("category") or "dsh"),
                    name=str(child.get("name") or ""),
                    provider="dsh",
                    workspace_root=str(child.get("workspace_root") or ""),
                ),
                executor=dsh_executor,
                status=status,
            )
        if record.contract.session_id != session_id or record.contract.user_id != user_id:
            raise PermissionError(f"当前会话不能继续子 Agent {run_id}")
        continued = self.child_agent_manager.continue_child(
            run_id=run_id,
            prompt=prompt,
            mode=mode,
            parent_run_id=parent_run_id,
        )
        return json.dumps(self._child_record_to_dict(continued), ensure_ascii=False)

    def _require_dsh_coding_agent_enabled(self, *, user_id: str) -> None:
        """在所有 DSH创建与追问入口强制执行默认关闭的用户级门禁。"""

        if not self._dsh_coding_agent_enabled(user_id=user_id):
            raise PermissionError(
                "DSH coding agent未启用；请先在基础设置开启“启用 DSH（deepseek-harness）作为 coding agent”。"
            )

    def _dsh_coding_agent_enabled(self, *, user_id: str) -> bool:
        """读取当前用户的 DSH开关；设置服务不可用时安全回退为关闭。"""

        return bool(
            self.settings_service is not None
            and self.settings_service.is_dsh_coding_agent_enabled_for_user(user_id=user_id)
        )
