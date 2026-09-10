"""
LLM 调度器运行时辅助 mixin。

功能说明:
本文件承载 `LLMTaskScheduler` 的底层运行时能力,包括模型实例解析、模型池并发许可、
本地任务重试/超时、队列选择、去重键维护和任务参数校验。

使用说明:
`scheduler.py` 中的 `LLMTaskScheduler` 继承 `LLMTaskRuntimeMixin`。外部业务不直接实例化
本 mixin。
"""

from __future__ import annotations

import json
import logging
import queue
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent_service.services.scheduler.types import (
    BACKGROUND_FACT_RESOLUTION_TASK,
    BACKGROUND_SUMMARY_TASK,
    FOREGROUND_AGENT_TASK,
    LLMOperation,
    LLMTaskHandle,
    LLMTaskOverloadedError,
    LARGE_MODEL_TIER,
    SMALL_MODEL_TIER,
    SUPPORTED_MODEL_TIERS,
    SUPPORTED_TASK_TYPES,
    ScheduledLLMTask,
)
from agent_service.core.context_budget import ModelCapacity


_DSML_TOOL_BLOCK_RE = re.compile(
    r"<[|｜]{1,2}DSML[|｜]{1,2}(?:tool_calls|function_calls|calls)>"
    r"(?P<body>.*?)"
    r"</[|｜]{1,2}DSML[|｜]{1,2}(?:tool_calls|function_calls|calls)>",
    re.DOTALL,
)
_DSML_INVOKE_RE = re.compile(
    r'<[|｜]{1,2}DSML[|｜]{1,2}invoke\s+name="(?P<name>[^"]+)"\s*>'
    r"(?P<body>.*?)"
    r"</[|｜]{1,2}DSML[|｜]{1,2}invoke>",
    re.DOTALL,
)
_DSML_PARAMETER_RE = re.compile(
    r'<[|｜]{1,2}DSML[|｜]{1,2}parameter\s+name="(?P<name>[^"]+)"'
    r'\s+string="(?P<string>true|false)"\s*>'
    r"(?P<value>.*?)"
    r"</[|｜]{1,2}DSML[|｜]{1,2}parameter>",
    re.DOTALL,
)
_DSML_TOOL_OPEN_MARKERS = (
    "<｜DSML｜tool_calls>",
    "<｜｜DSML｜｜tool_calls>",
    "<|DSML|tool_calls>",
    "<||DSML||tool_calls>",
    "<｜DSML｜function_calls>",
    "<｜｜DSML｜｜function_calls>",
    "<|DSML|function_calls>",
    "<||DSML||function_calls>",
    "<｜DSML｜calls>",
    "<｜｜DSML｜｜calls>",
    "<|DSML|calls>",
    "<||DSML||calls>",
)


def recover_deepseek_dsml_tool_calls(
    message: BaseMessage,
    *,
    allowed_tool_names: list[str],
) -> BaseMessage:
    """把 DeepSeek 正文中的完整 DSML 块恢复为 LangChain 工具调用。"""

    content = getattr(message, "content", "")
    if not isinstance(message, AIMessage) or not isinstance(content, str) or message.tool_calls:
        return message
    allowed_names = set(allowed_tool_names)
    recovered_calls: list[dict[str, Any]] = []
    matched_dsml = False

    def replace_block(match: re.Match[str]) -> str:
        """解析一个完整工具块，并从最终用户可见正文中移除。"""

        nonlocal matched_dsml
        matched_dsml = True
        for invoke in _DSML_INVOKE_RE.finditer(match.group("body")):
            name = invoke.group("name")
            if name not in allowed_names:
                continue
            arguments: dict[str, Any] = {}
            valid = True
            parameters = list(_DSML_PARAMETER_RE.finditer(invoke.group("body")))
            if parameters:
                for parameter in parameters:
                    value: Any = parameter.group("value")
                    if parameter.group("string") == "false":
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            valid = False
                            break
                    arguments[parameter.group("name")] = value
            else:
                direct_arguments = invoke.group("body").strip()
                if direct_arguments:
                    try:
                        decoded_arguments = json.loads(direct_arguments)
                    except json.JSONDecodeError:
                        valid = False
                    else:
                        if isinstance(decoded_arguments, dict):
                            arguments = decoded_arguments
                        else:
                            valid = False
            if valid:
                recovered_calls.append({
                    "name": name,
                    "args": arguments,
                    "id": f"call_{uuid4().hex}",
                    "type": "tool_call",
                })
        return ""

    visible_content = _DSML_TOOL_BLOCK_RE.sub(replace_block, content)
    if not matched_dsml:
        return message
    return message.model_copy(update={"content": visible_content, "tool_calls": recovered_calls})


def filter_deepseek_dsml_stream_delta(
    buffered_text: str,
    content_delta: str,
    *,
    suppressing: bool,
) -> tuple[str, str, bool]:
    """流式隐藏 DSML；保留可能被拆分的起始标记前缀等待下一 chunk。"""

    if suppressing:
        return "", "", True
    pending = buffered_text + content_delta
    marker_indexes = [
        index
        for marker in _DSML_TOOL_OPEN_MARKERS
        if (index := pending.find(marker)) >= 0
    ]
    if marker_indexes:
        first_marker = min(marker_indexes)
        return pending[:first_marker], "", True
    retained_length = max(
        (
            length
            for marker in _DSML_TOOL_OPEN_MARKERS
            for length in range(1, min(len(marker), len(pending)) + 1)
            if pending.endswith(marker[:length])
        ),
        default=0,
    )
    if retained_length:
        return pending[:-retained_length], pending[-retained_length:], False
    return pending, "", False


class DeepSeekChatOpenAI(ChatOpenAI):
    """Preserve DeepSeek ``reasoning_content`` across LangChain conversions.

    ChatOpenAI intentionally targets the standard OpenAI schema and may drop
    provider-specific fields. DeepSeek requires reasoning to be streamed,
    persisted, and replayed with assistant tool-call messages.
    """

    @staticmethod
    def _reasoning_text(value: Any) -> str:
        """Normalize provider string/list reasoning payloads to one string."""

        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(str(part) for part in value)
        return ""

    @staticmethod
    def supports_model(model_name: str) -> bool:
        """识别直连名和模型市场常见的命名空间 DeepSeek 标识。"""

        normalized = model_name.strip().lower().replace(":", "/")
        return any(part.startswith("deepseek") for part in normalized.split("/"))

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> Any:
        """Attach raw DeepSeek reasoning delta to the converted message chunk."""

        generation = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        delta = choices[0].get("delta", {}) if choices else {}
        reasoning = self._reasoning_text(delta.get("reasoning_content"))
        if generation is not None and reasoning:
            generation.message.additional_kwargs["reasoning_content"] = reasoning
        return generation

    def _create_chat_result(
        self,
        response: dict[str, Any] | Any,
        generation_info: dict[str, Any] | None = None,
    ) -> Any:
        """Attach full DeepSeek reasoning to non-streaming/final results."""

        response_dict = response if isinstance(response, dict) else response.model_dump()
        result = super()._create_chat_result(response, generation_info)
        choices = response_dict.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        reasoning = self._reasoning_text(message.get("reasoning_content"))
        if result.generations and reasoning:
            result.generations[0].message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Replay assistant reasoning required by DeepSeek thinking tool calls."""

        payload = super()._get_request_payload(input_, *args, **kwargs)
        serialized_messages = payload.get("messages")
        if not isinstance(serialized_messages, list):
            return payload
        source_messages = self._convert_input(input_).to_messages()
        for source, serialized in zip(source_messages, serialized_messages, strict=False):
            reasoning = self._reasoning_text(
                getattr(source, "additional_kwargs", {}).get("reasoning_content")
            )
            if reasoning and isinstance(serialized, dict) and serialized.get("role") == "assistant":
                serialized["reasoning_content"] = reasoning
        return payload


class LLMTaskRuntimeMixin:
    """
    `LLMTaskScheduler` 的运行时辅助能力集合。

    继承者需要提供 config、task_config、模型缓存、模型信号量、本地队列和去重锁等字段。
    """

    def _get_chat_model(
        self,
        *,
        tool_names: list[str],
        temperature: float | None,
        timeout_seconds: float,
        model_tier: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
    ) -> Any:
        """构造或复用与请求匹配的 ChatOpenAI 实例。"""

        model_name, resolved_api_key, resolved_base_url, final_temperature = self._resolve_model_runtime(
            model_tier=model_tier,
            requested_temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
        )
        use_local_qwen = (
            model_name == self.config.model.local_model_name
            and not resolved_api_key
            and not resolved_base_url
        )
        if not resolved_api_key and not use_local_qwen:
            logger = __import__("logging").getLogger(__name__)
            logger.error(
                "_get_chat_model: MISSING API KEY tier=%s model=%s has_api_key_param=%s has_small_api_key_param=%s",
                model_tier,
                model_name,
                bool(api_key),
                bool(small_api_key),
            )
        cache_key = (
            model_tier,
            model_name,
            tuple(sorted(tool_names)),
            float(final_temperature),
            float(timeout_seconds),
            resolved_api_key,
            resolved_base_url,
        )
        with self._model_cache_lock:
            model = self._model_cache.get(cache_key)
            if model is not None:
                return model
            if use_local_qwen:
                from agent_service.services.local_qwen.service import LocalQwenChatModel, get_local_qwen_service

                model = LocalQwenChatModel(
                    service=get_local_qwen_service(self.config),
                    temperature=final_temperature,
                )
            else:
                model_kwargs = self.config.model.get_model_kwargs(model_name)
                model_class = (
                    DeepSeekChatOpenAI
                    if DeepSeekChatOpenAI.supports_model(model_name)
                    else ChatOpenAI
                )
                model = model_class(
                    model=model_name,
                    api_key=resolved_api_key,
                    base_url=resolved_base_url,
                    temperature=final_temperature,
                    timeout=timeout_seconds,
                    max_retries=0,
                    **model_kwargs,
                )
            if tool_names:
                tool_registry = self._get_tool_registry()
                tools = [
                    tool
                    for tool in tool_registry.to_langchain_tools()
                    if tool.name in set(tool_names)
                ]
                if tools:
                    model = model.bind_tools(tools)
            self._model_cache[cache_key] = model
            return model

    def build_observability_snapshot(
        self,
        *,
        messages: list[BaseMessage],
        tool_names: list[str] | None = None,
        model_tier: str = LARGE_MODEL_TIER,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        node: str = "agent",
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """返回即将提交给模型的完整、无密钥请求快照。

        工具定义使用与 ``bind_tools`` 相同的 LangChain 转换函数生成，避免 Debug
        页面根据工具名重建出与真实请求不同的 schema。模型名、温度和扩展参数也在
        此处按实际运行时规则解析；API Key 属于密钥，永不进入快照。
        """

        selected_names = list(tool_names or [])
        resolved_model, _resolved_key, _resolved_base_url, resolved_temperature = self._resolve_model_runtime(
            model_tier=model_tier,
            requested_temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
        )
        prepared_messages, context_budget = self.prepare_messages_for_model(
            messages=messages,
            tool_names=selected_names,
            model_tier=model_tier,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        )
        selected_name_set = set(selected_names)
        tools = [
            convert_to_openai_tool(tool)
            for tool in self._get_tool_registry().to_langchain_tools()
            if tool.name in selected_name_set
        ]
        return {
            "node": node,
            "model_tier": model_tier,
            "model": resolved_model,
            "temperature": resolved_temperature,
            "timeout_seconds": timeout_seconds or self._resolve_timeout_seconds(FOREGROUND_AGENT_TASK),
            "model_kwargs": self.config.model.get_model_kwargs(resolved_model),
            "messages": self._serialize_observability_messages(prepared_messages),
            "tools": tools,
            "context_budget": context_budget,
        }

    def prepare_messages_for_model(
        self,
        *,
        messages: list[BaseMessage],
        tool_names: list[str] | None,
        model_tier: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[list[BaseMessage], dict[str, Any]]:
        """在调度器最终边界按实际模型能力组装并复算请求。"""

        from agent_service.services.memory.context_builder import ContextBuilder

        resolved_model, _resolved_key, _resolved_base_url, _temperature = self._resolve_model_runtime(
            model_tier=model_tier,
            requested_temperature=None,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
        )
        capacity = ModelCapacity.resolve(
            config=self.config,
            model_name=resolved_model,
            model_tier=model_tier,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        )
        selected_name_set = set(tool_names or [])
        selected_tools = [
            tool
            for tool in self._get_tool_registry().to_langchain_tools()
            if tool.name in selected_name_set
        ]
        tool_definition_tokens = ContextBuilder.estimate_tool_definition_tokens(
            selected_tools,
            model_name=resolved_model,
        )
        source_messages = list(messages)
        system_index = next(
            (index for index, message in enumerate(source_messages) if isinstance(message, SystemMessage)),
            None,
        )
        if system_index is None:
            system_message = None
            remaining_messages = source_messages
        else:
            system_message = source_messages[system_index]
            remaining_messages = [
                message for index, message in enumerate(source_messages) if index != system_index
            ]
        return ContextBuilder.assemble_request_messages(
            system_message=system_message,
            messages=remaining_messages,
            config=self.config,
            capacity=capacity,
            tool_definition_tokens=tool_definition_tokens,
        )

    @staticmethod
    def _serialize_observability_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """按模型输入顺序保留消息正文、工具调用和工具响应关联字段。"""

        role_map = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
        serialized: list[dict[str, Any]] = []
        for message in messages:
            item: dict[str, Any] = {
                "role": role_map.get(message.type, message.type),
                "content": getattr(message, "content", "") or "",
            }
            for field_name in ("tool_calls", "tool_call_id", "name"):
                value = getattr(message, field_name, None)
                if value:
                    item[field_name] = value
            serialized.append(item)
        return serialized

    def _resolve_model_runtime(
        self,
        *,
        model_tier: str,
        requested_temperature: float | None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
    ) -> tuple[str, str, str, float]:
        """根据模型池等级解析实际调用所需的模型参数。"""

        configured_primary_model = (model_name or self.config.model.model_name or "").strip()
        primary_api_key = (api_key or self.config.model.api_key or "").strip()
        primary_base_url = (base_url or self.config.model.base_url or "").strip()
        primary_is_remote = bool(configured_primary_model and primary_api_key)
        primary_model_name = configured_primary_model if primary_is_remote else self.config.model.local_model_name
        resolved_small_model_name = (
            (
                small_model_name
                or self.config.model.small_model_name
                or configured_primary_model
            )
            if primary_is_remote
            else self.config.model.local_model_name
        ).strip()
        if model_tier == SMALL_MODEL_TIER:
            small_temperature = self.config.model._normalize_temperature_for_model(
                model_name=resolved_small_model_name,
                requested_temperature=(
                    self.config.model.small_model_temperature
                    if requested_temperature is None
                    else requested_temperature
                ),
            )
            if not primary_is_remote:
                return resolved_small_model_name, "", "", small_temperature
            return (
                resolved_small_model_name,
                (small_api_key or self.config.model.small_model_api_key or primary_api_key or "").strip(),
                (small_base_url or self.config.model.small_model_base_url or primary_base_url or "").strip(),
                small_temperature,
            )
        primary_temperature = self.config.model._normalize_temperature_for_model(
            model_name=primary_model_name,
            requested_temperature=(
                self.config.model.temperature
                if requested_temperature is None
                else requested_temperature
            ),
        )
        if not primary_is_remote:
            return primary_model_name, "", "", primary_temperature
        return primary_model_name, primary_api_key, primary_base_url, primary_temperature

    @contextmanager
    def _acquire_model_pool(self, model_tier: str) -> Any:
        """获取指定模型池的并发许可。"""

        semaphore = self._model_semaphores[model_tier]
        semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()

    def _get_tool_registry(self) -> Any:
        """懒加载工具注册表,避免在模块导入阶段引入环依赖。"""

        if self._tool_registry is not None:
            return self._tool_registry
        from agent_service.tools.tool_registry import ToolRegistry

        self._tool_registry = ToolRegistry.with_builtin_tools(config=self.config)
        return self._tool_registry

    def _run_with_retries(self, task: ScheduledLLMTask) -> Any:
        """执行任务并对可恢复错误做指数退避重试。"""

        attempt = 0
        last_error: Exception | None = None
        while attempt <= task.max_retries:
            try:
                return self._run_with_timeout(task)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= task.max_retries or not self._is_retryable_error(exc):
                    raise
                backoff_seconds = min(
                    self.task_config.initial_backoff_seconds * (2**attempt),
                    self.task_config.max_backoff_seconds,
                )
                jitter = random.uniform(0.0, backoff_seconds * 0.2)
                time.sleep(backoff_seconds + jitter)
                attempt += 1
        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM 任务重试失败但没有异常信息。")

    @staticmethod
    def _run_operation_future(operation: LLMOperation) -> Any:
        """作为线程池 target 包装实际操作。"""

        return operation()

    def _run_with_timeout(self, task: ScheduledLLMTask) -> Any:
        """使用受控超时执行实际操作。"""

        if self._shutdown_event.is_set() or sys.is_finalizing():
            raise RuntimeError("LLM 调度器正在关闭,不再接受新的本地执行任务。")
        with ThreadPoolExecutor(
            max_workers=self.task_config.operation_timeout_worker_count,
            thread_name_prefix=f"{task.task_type}-call",
        ) as executor:
            future = executor.submit(self._run_operation_future, task.operation)
            try:
                return future.result(timeout=task.timeout_seconds)
            except FutureTimeoutError as exc:
                future.cancel()
                raise TimeoutError(
                    f"LLM 任务 {task.task_type} 超时,超过 {task.timeout_seconds} 秒仍未完成。"
                ) from exc

    def _enqueue_local_task(self, task: ScheduledLLMTask) -> None:
        """将任务放入对应本地等级队列。"""

        target_queue = self._resolve_local_queue(task.task_type)
        try:
            target_queue.put_nowait(task)
        except queue.Full as exc:
            if task.task_type != FOREGROUND_AGENT_TASK and self.task_config.drop_low_priority_when_overloaded:
                raise LLMTaskOverloadedError(f"后台本地队列已满,拒绝任务 {task.task_type}。") from exc
            raise LLMTaskOverloadedError(f"本地 LLM 队列已满,无法提交任务 {task.task_type}。") from exc

    def _resolve_local_queue(self, task_type: str) -> queue.Queue[ScheduledLLMTask]:
        """根据任务类型返回目标本地队列。"""

        if task_type == FOREGROUND_AGENT_TASK:
            return self._local_foreground_queue
        if task_type == BACKGROUND_SUMMARY_TASK:
            return self._local_summary_queue
        return self._local_fact_queue

    def _resolve_timeout_seconds(self, task_type: str) -> float:
        """根据任务类型返回默认超时。"""

        if task_type == FOREGROUND_AGENT_TASK:
            return float(self.task_config.foreground_timeout_seconds)
        if task_type == BACKGROUND_SUMMARY_TASK:
            return float(self.task_config.summary_timeout_seconds)
        if task_type == BACKGROUND_FACT_RESOLUTION_TASK:
            return float(self.task_config.fact_resolution_timeout_seconds)
        return float(self.task_config.default_timeout_seconds)

    def _resolve_queue_max_size(self, task_type: str) -> int:
        """根据任务类型返回 Redis 队列最大长度。"""

        if task_type == FOREGROUND_AGENT_TASK:
            return max(self.task_config.foreground_queue_max_size, 1)
        return max(self.task_config.background_queue_max_size, 1)

    def _normalize_dedup_key(self, *, task_type: str, dedup_key: str | None) -> str | None:
        """标准化去重键。"""

        if not dedup_key:
            return None
        if task_type == BACKGROUND_SUMMARY_TASK and not self.task_config.summary_deduplicate_by_session:
            return None
        return f"{task_type}:{dedup_key}"

    def _get_existing_local_dedup_handle(self, dedup_key: str) -> LLMTaskHandle | None:
        """读取仍在执行中的本地去重句柄。"""

        with self._dedup_lock:
            handle = self._dedup_handles.get(dedup_key)
            if handle is None:
                return None
            if handle.future.done():
                self._dedup_handles.pop(dedup_key, None)
                return None
            return handle

    def _release_local_dedup_key(self, dedup_key: str | None, handle: LLMTaskHandle | None) -> None:
        """释放本地去重键。"""

        if dedup_key is None:
            return
        with self._dedup_lock:
            current = self._dedup_handles.get(dedup_key)
            if handle is None or current is handle:
                self._dedup_handles.pop(dedup_key, None)

    @staticmethod
    def _ensure_supported_task_type(task_type: str) -> None:
        """校验任务类型是否合法。"""

        if task_type not in SUPPORTED_TASK_TYPES:
            raise ValueError(f"不支持的 LLM 调度任务类型: {task_type}")

    @staticmethod
    def _ensure_supported_model_tier(model_tier: str) -> None:
        """校验模型池等级是否合法。"""

        if model_tier not in SUPPORTED_MODEL_TIERS:
            raise ValueError(f"不支持的模型池等级: {model_tier}")

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """判断一个异常是否适合自动重试。"""

        if isinstance(exc, TimeoutError):
            return True
        message = str(exc).lower()
        retryable_tokens = (
            "429",
            "rate limit",
            "too many requests",
            "overload",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection error",
            "connection aborted",
            "server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
        return any(token in message for token in retryable_tokens)
