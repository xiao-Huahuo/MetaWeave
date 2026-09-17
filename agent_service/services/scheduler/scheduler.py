"""
LLM 多级任务队列调度器模块。

功能说明:
本文件实现统一 `LLMTaskScheduler`。它同时支持两类执行路径:

1. 本地 generic 队列:
   用于当前进程内不可序列化的普通后台任务,例如 `SummaryNode` 触发的摘要业务入口。
2. Redis Chat 队列:
   用于真正的 LLM 请求。请求会被序列化为消息列表、工具名和推理参数,写入 Redis Stream,
   由 worker 消费并执行 `ChatOpenAI.invoke(...)`,再将结果回写 Redis。

这样做的原因是: Python callable 不能跨进程放入 Redis 队列,但项目里所有真正的 LLM
调用都可以抽象成"可序列化的 chat request",因此可以在不破坏现有业务结构的前提下,
把 LLM 资源调度升级为生产可扩展模式。

使用说明:
- 普通本地任务继续使用 `run(...)` / `submit(...)`
- 所有 LLM 调用必须使用 `invoke_chat(...)` / `submit_chat(...)`
"""

from __future__ import annotations

import atexit
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
import itertools
import json
import logging
import queue
import random
import threading
import time
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage

from agent_service.core.agent_config import AgentConfig
from agent_service.services.scheduler.circuit_breaker import CircuitBreaker, RedisCircuitBreakerStore
from agent_service.services.scheduler.redis_backend import (
    RedisStreamLLMBackend,
    SerializedChatRequest,
    SerializedChatResult,
    SerializedSummaryJobRequest,
    SerializedSummaryJobResult,
)
from agent_service.services.scheduler.runtime import (
    LLMTaskRuntimeMixin,
    filter_deepseek_dsml_stream_delta,
    recover_deepseek_dsml_tool_calls,
)
from agent_service.services.scheduler.types import (
    BACKGROUND_FACT_RESOLUTION_TASK,
    BACKGROUND_SUMMARY_TASK,
    FOREGROUND_AGENT_TASK,
    LARGE_MODEL_TIER,
    LLMOperation,
    LLMConfigurationError,
    LLMTaskHandle,
    LLMTaskOverloadedError,
    SMALL_MODEL_TIER,
    VISION_MODEL_TIER,
    VISION_UNDERSTANDING_TASK,
    ScheduledLLMTask,
)


logger = logging.getLogger(__name__)


class LLMTaskScheduler(LLMTaskRuntimeMixin):
    """
    统一 LLM 调度器。

    config: 全局配置对象。
    """

    def __init__(self, *, config: AgentConfig, settings_service: Any = None) -> None:
        """初始化本地队列、Redis backend、worker 池和熔断器。"""

        self.config = config
        self.settings_service = settings_service
        self.task_config = config.task_schedule
        logger.info(
            "LLM 调度器初始化 | redis=%s large_pool=%d small_pool=%d global_max=%d",
            bool(self.task_config.redis_url),
            self.task_config.large_model_max_concurrency,
            self.task_config.small_model_max_concurrency,
            self.task_config.global_max_concurrency,
        )
        self._sequence = itertools.count()
        self._shutdown_event = threading.Event()
        self._global_semaphore = threading.Semaphore(max(self.task_config.global_max_concurrency, 1))
        self._model_semaphores = {
            LARGE_MODEL_TIER: threading.Semaphore(max(self.task_config.large_model_max_concurrency, 1)),
            SMALL_MODEL_TIER: threading.Semaphore(max(self.task_config.small_model_max_concurrency, 1)),
            VISION_MODEL_TIER: threading.Semaphore(max(self.task_config.large_model_max_concurrency, 1)),
        }
        self._dedup_lock = threading.Lock()
        self._dedup_handles: dict[str, LLMTaskHandle] = {}
        self._tool_registry: Any | None = None
        self._model_cache_lock = threading.Lock()
        self._model_cache: dict[tuple[tuple[str, ...], float, float], Any] = {}
        self._local_foreground_queue: queue.Queue[ScheduledLLMTask] = queue.Queue(
            maxsize=max(self.task_config.foreground_queue_max_size, 1)
        )
        self._local_summary_queue: queue.Queue[ScheduledLLMTask] = queue.Queue(
            maxsize=max(self.task_config.background_queue_max_size, 1)
        )
        self._local_fact_queue: queue.Queue[ScheduledLLMTask] = queue.Queue(
            maxsize=max(self.task_config.background_queue_max_size, 1)
        )
        self._backend: RedisStreamLLMBackend | None = None
        store = None
        if self.task_config.redis_url:
            store = RedisCircuitBreakerStore(
                redis_url=self.task_config.redis_url,
                key_prefix=self.task_config.redis_prefix,
            )
            self._backend = RedisStreamLLMBackend(
                redis_url=self.task_config.redis_url,
                key_prefix=self.task_config.redis_prefix,
                consumer_group=self.task_config.redis_consumer_group,
                result_ttl_seconds=self.task_config.redis_result_ttl_seconds,
                dedup_ttl_seconds=self.task_config.redis_dedup_ttl_seconds,
                block_timeout_ms=self.task_config.redis_block_timeout_ms,
                visibility_timeout_ms=self.task_config.redis_visibility_timeout_seconds * 1000,
                result_poll_interval_seconds=self.task_config.redis_result_poll_interval_seconds,
                stream_maxlen=self.task_config.redis_stream_maxlen,
            )
        self._circuit_breakers = {
            FOREGROUND_AGENT_TASK: CircuitBreaker(
                name=FOREGROUND_AGENT_TASK,
                failure_threshold=self.task_config.circuit_breaker_failure_threshold,
                recovery_seconds=self.task_config.circuit_breaker_recovery_seconds,
                store=store,
            ),
            BACKGROUND_SUMMARY_TASK: CircuitBreaker(
                name=BACKGROUND_SUMMARY_TASK,
                failure_threshold=self.task_config.circuit_breaker_failure_threshold,
                recovery_seconds=self.task_config.circuit_breaker_recovery_seconds,
                store=store,
            ),
            BACKGROUND_FACT_RESOLUTION_TASK: CircuitBreaker(
                name=BACKGROUND_FACT_RESOLUTION_TASK,
                failure_threshold=self.task_config.circuit_breaker_failure_threshold,
                recovery_seconds=self.task_config.circuit_breaker_recovery_seconds,
                store=store,
            ),
            VISION_UNDERSTANDING_TASK: CircuitBreaker(
                name=VISION_UNDERSTANDING_TASK,
                failure_threshold=self.task_config.circuit_breaker_failure_threshold,
                recovery_seconds=self.task_config.circuit_breaker_recovery_seconds,
                store=store,
            ),
        }
        self._local_worker_threads = self._start_local_workers()
        self._redis_worker_threads = self._start_redis_workers()

    def run(
        self,
        *,
        task_type: str,
        operation: LLMOperation,
        dedup_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """
        提交并同步等待一个本地 generic 任务。

        该入口保留给不可序列化的本地业务任务,不用于真正的 LLM 调用。
        """

        handle = self.submit(
            task_type=task_type,
            operation=operation,
            dedup_key=dedup_key,
            timeout_seconds=timeout_seconds,
        )
        return handle.wait()

    def submit(
        self,
        *,
        task_type: str,
        operation: LLMOperation,
        dedup_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMTaskHandle:
        """
        提交一个本地 generic 异步任务。

        该入口保留给不可序列化的本地业务任务,不用于真正的 LLM 调用。
        """

        self._ensure_supported_task_type(task_type)
        actual_dedup_key = self._normalize_dedup_key(task_type=task_type, dedup_key=dedup_key)
        if actual_dedup_key is not None:
            existing_handle = self._get_existing_local_dedup_handle(actual_dedup_key)
            if existing_handle is not None:
                return existing_handle
        task = ScheduledLLMTask(
            sequence=next(self._sequence),
            task_id=f"llm_task_{uuid4().hex}",
            task_type=task_type,
            operation=operation,
            timeout_seconds=timeout_seconds or self._resolve_timeout_seconds(task_type),
            max_retries=max(self.task_config.max_retries, 0),
            dedup_key=actual_dedup_key,
        )
        handle = LLMTaskHandle(task_id=task.task_id, task_type=task.task_type, future=task.future)
        if actual_dedup_key is not None:
            with self._dedup_lock:
                existing_handle = self._dedup_handles.get(actual_dedup_key)
                if existing_handle is not None:
                    return existing_handle
                self._dedup_handles[actual_dedup_key] = handle
        try:
            self._enqueue_local_task(task)
        except Exception:
            self._release_local_dedup_key(actual_dedup_key, handle)
            raise
        return handle

    def invoke_chat(
        self,
        *,
        task_type: str,
        messages: Sequence[BaseMessage],
        tool_names: list[str] | None = None,
        dedup_key: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        model_tier: str = LARGE_MODEL_TIER,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> BaseMessage:
        """提交并同步等待一个可序列化的 LLM Chat 请求。"""

        logger.debug(
            "LLM Chat 调用 | task_type=%s model_tier=%s msg_count=%d tools=%d",
            task_type,
            model_tier,
            len(messages),
            len(tool_names or []),
        )
        handle = self.submit_chat(
            task_type=task_type,
            messages=messages,
            tool_names=tool_names,
            dedup_key=dedup_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
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
        return handle.wait(timeout=timeout_seconds)

    def stream_chat(
        self,
        *,
        task_type: str,
        messages: Sequence[BaseMessage],
        tool_names: list[str] | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        model_tier: str = LARGE_MODEL_TIER,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        流式调用 LLM Chat,逐 token 产出增量内容。

        与 invoke_chat() 不同,本方法不会阻塞等待完整回复,而是通过
        model.stream() 逐 token yield dict。适用于 SSE / gRPC 流式推送场景。

        每个 chunk: {"content_delta": str}
        最后一个 chunk: {"content_delta": "...", "message": BaseMessage, "status": "complete"}

        task_type: 任务类型。
        messages: 对话消息列表。
        tool_names: 可选工具名列表,用于绑定工具。
        timeout_seconds: 可选超时秒数。
        temperature: 可选温度覆盖值。
        model_tier: 模型池等级,默认 large。
        """

        self._ensure_supported_task_type(task_type)
        self._ensure_supported_model_tier(model_tier)
        if not self._circuit_breakers[task_type].allow_request():
            raise LLMTaskOverloadedError(f"任务类型 {task_type} 当前处于熔断状态,暂时拒绝新请求。")
        logger.debug(
            "LLM Chat 流式调用 | task_type=%s model_tier=%s msg_count=%d tools=%d",
            task_type,
            model_tier,
            len(messages),
            len(tool_names or []),
        )
        request = SerializedChatRequest.from_messages(
            task_id=f"llm_chat_{uuid4().hex}",
            task_type=task_type,
            messages=list(messages),
            tool_names=tool_names or [],
            timeout_seconds=timeout_seconds or self._resolve_timeout_seconds(task_type),
            max_retries=max(self.task_config.max_retries, 0),
            dedup_key=None,
            temperature=temperature,
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
        if self._backend is not None:
            request.stream_channel = f"stream:{request.task_id}"
            pubsub = self._backend.subscribe_stream(channel=request.stream_channel)
            try:
                self._backend.enqueue_chat_request(
                    request,
                    queue_max_size=self._resolve_queue_max_size(task_type),
                )
                for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    chunk = json.loads(message["data"])
                    if chunk.get("status") == "done":
                        final_message = self._backend.wait_for_result(
                            task_id=request.task_id, timeout=request.timeout_seconds
                        )
                        full_content = getattr(final_message, "content", "") or ""
                        stream_diagnostics = (
                            getattr(final_message, "additional_kwargs", {}).get("stream_diagnostics", {})
                        )
                        yield {
                            "content_delta": full_content,
                            "message": final_message,
                            "status": "complete",
                            "stream_diagnostics": stream_diagnostics,
                        }
                        return
                    if chunk.get("status") == "error":
                        raise RuntimeError(chunk.get("error_message", "流式任务失败"))
                    yield chunk
            finally:
                pubsub.unsubscribe(request.stream_channel)
                pubsub.close()
            return
        yield from self._stream_chat_request_with_retries(request)

    def submit_chat(
        self,
        *,
        task_type: str,
        messages: Sequence[BaseMessage],
        tool_names: list[str] | None = None,
        dedup_key: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        model_tier: str = LARGE_MODEL_TIER,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMTaskHandle:
        """提交一个可序列化的 LLM Chat 请求。"""

        self._ensure_supported_task_type(task_type)
        self._ensure_supported_model_tier(model_tier)
        actual_dedup_key = self._normalize_dedup_key(task_type=task_type, dedup_key=dedup_key)
        if not self._circuit_breakers[task_type].allow_request():
            raise LLMTaskOverloadedError(f"任务类型 {task_type} 当前处于熔断状态,暂时拒绝新请求。")
        request = SerializedChatRequest.from_messages(
            task_id=f"llm_chat_{uuid4().hex}",
            task_type=task_type,
            messages=list(messages),
            tool_names=tool_names or [],
            timeout_seconds=timeout_seconds or self._resolve_timeout_seconds(task_type),
            max_retries=max(self.task_config.max_retries, 0),
            dedup_key=actual_dedup_key,
            temperature=temperature,
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
        if self._backend is None:
            return self._submit_local_chat_request(request)
        return self._submit_redis_chat_request(request)

    def submit_summary_job(
        self,
        *,
        user_id: str,
        session_id: str,
        dedup_key: str | None = None,
    ) -> LLMTaskHandle:
        """
        提交一个持久化的 Summary 业务任务。

        在启用 Redis backend 时,任务会被写入专用 Redis Stream,即使当前服务实例退出,
        其他实例或重启后的实例也可以继续消费处理。
        """

        actual_dedup_key = self._normalize_dedup_key(
            task_type=BACKGROUND_SUMMARY_TASK,
            dedup_key=dedup_key or session_id,
        )
        request = SerializedSummaryJobRequest(
            task_id=f"summary_job_{uuid4().hex}",
            user_id=user_id,
            session_id=session_id,
            dedup_key=actual_dedup_key,
        )
        if self._backend is None:
            return self.submit(
                task_type=BACKGROUND_SUMMARY_TASK,
                operation=lambda: self._run_summary_business_task(
                    user_id=user_id,
                    session_id=session_id,
                ),
                dedup_key=actual_dedup_key,
                timeout_seconds=self._resolve_timeout_seconds(BACKGROUND_SUMMARY_TASK),
            )
        effective_task_id = request.task_id
        if request.dedup_key is not None:
            effective_task_id = self._backend.register_dedup_or_get_existing(
                dedup_key=request.dedup_key,
                task_id=request.task_id,
            )
        handle = LLMTaskHandle(
            task_id=effective_task_id,
            task_type=BACKGROUND_SUMMARY_TASK,
            future=Future(),
            result_loader=lambda timeout: self._backend.wait_for_summary_result(
                task_id=effective_task_id,
                timeout=timeout,
            ),
        )
        if effective_task_id != request.task_id:
            return handle
        try:
            queue_max_size = self._resolve_queue_max_size(BACKGROUND_SUMMARY_TASK)
            self._backend.enqueue_summary_job(request, queue_max_size=queue_max_size)
        except Exception:
            self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
            raise
        return handle

    def shutdown(self) -> None:
        """停止 worker 线程。"""

        logger.info("LLM 调度器正在关闭 | local_workers=%d redis_workers=%d",
                     len(self._local_worker_threads), len(self._redis_worker_threads))
        self._shutdown_event.set()
        for worker in self._local_worker_threads:
            worker.join(timeout=self.config.task_schedule.worker_shutdown_timeout_seconds)
        for worker in self._redis_worker_threads:
            worker.join(timeout=self.config.task_schedule.worker_shutdown_timeout_seconds)
        logger.info("LLM 调度器已关闭")

    def supports_persistent_summary_jobs(self) -> bool:
        """返回当前调度器是否启用了 Redis 持久化 Summary 业务任务。"""

        return self._backend is not None

    def _submit_local_chat_request(self, request: SerializedChatRequest) -> LLMTaskHandle:
        """将 Chat 请求回退为本地 generic 队列任务。"""

        task = ScheduledLLMTask(
            sequence=next(self._sequence),
            task_id=request.task_id,
            task_type=request.task_type,
            operation=lambda: self._invoke_chat_request(request),
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            dedup_key=request.dedup_key,
        )
        handle = LLMTaskHandle(task_id=task.task_id, task_type=task.task_type, future=task.future)
        if request.dedup_key is not None:
            with self._dedup_lock:
                existing_handle = self._dedup_handles.get(request.dedup_key)
                if existing_handle is not None:
                    return existing_handle
                self._dedup_handles[request.dedup_key] = handle
        try:
            self._enqueue_local_task(task)
        except Exception:
            self._release_local_dedup_key(request.dedup_key, handle)
            raise
        return handle

    def _submit_redis_chat_request(self, request: SerializedChatRequest) -> LLMTaskHandle:
        """将 Chat 请求写入 Redis Stream。"""

        assert self._backend is not None
        effective_task_id = request.task_id
        if request.dedup_key is not None:
            effective_task_id = self._backend.register_dedup_or_get_existing(
                dedup_key=request.dedup_key,
                task_id=request.task_id,
            )
        handle = LLMTaskHandle(
            task_id=effective_task_id,
            task_type=request.task_type,
            future=Future(),
            result_loader=lambda timeout: self._backend.wait_for_result(
                task_id=effective_task_id,
                timeout=timeout,
            ),
        )
        if effective_task_id != request.task_id:
            return handle
        try:
            queue_max_size = self._resolve_queue_max_size(request.task_type)
            self._backend.enqueue_chat_request(request, queue_max_size=queue_max_size)
        except Exception:
            self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
            raise
        return handle

    def _start_local_workers(self) -> list[threading.Thread]:
        """启动本地 generic 队列 worker。"""

        workers: list[threading.Thread] = []
        for index in range(max(self.task_config.foreground_agent_worker_count, 1)):
            worker = threading.Thread(
                target=self._local_foreground_worker_loop,
                daemon=True,
                name=f"llm-local-foreground-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_summary_worker_count, 1)):
            worker = threading.Thread(
                target=self._local_summary_worker_loop,
                daemon=True,
                name=f"llm-local-summary-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_fact_worker_count, 1)):
            worker = threading.Thread(
                target=self._local_fact_worker_loop,
                daemon=True,
                name=f"llm-local-fact-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        return workers

    def _start_redis_workers(self) -> list[threading.Thread]:
        """在启用 Redis backend 时启动对应的 Stream worker。"""

        if self._backend is None:
            return []
        workers: list[threading.Thread] = []
        for index in range(max(self.task_config.foreground_agent_worker_count, 1)):
            worker = threading.Thread(
                target=self._redis_worker_loop,
                kwargs={"task_type": FOREGROUND_AGENT_TASK, "consumer_name": f"fg-{uuid4().hex[:8]}-{index}"},
                daemon=True,
                name=f"llm-redis-foreground-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_summary_worker_count, 1)):
            worker = threading.Thread(
                target=self._redis_worker_loop,
                kwargs={"task_type": BACKGROUND_SUMMARY_TASK, "consumer_name": f"sum-{uuid4().hex[:8]}-{index}"},
                daemon=True,
                name=f"llm-redis-summary-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_summary_worker_count, 1)):
            worker = threading.Thread(
                target=self._redis_summary_business_worker_loop,
                kwargs={"consumer_name": f"sum-job-{uuid4().hex[:8]}-{index}"},
                daemon=True,
                name=f"llm-redis-summary-business-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_fact_worker_count, 1)):
            worker = threading.Thread(
                target=self._redis_worker_loop,
                kwargs={"task_type": BACKGROUND_FACT_RESOLUTION_TASK, "consumer_name": f"fact-{uuid4().hex[:8]}-{index}"},
                daemon=True,
                name=f"llm-redis-fact-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        for index in range(max(self.task_config.background_fact_worker_count, 1)):
            worker = threading.Thread(
                target=self._redis_worker_loop,
                kwargs={"task_type": VISION_UNDERSTANDING_TASK, "consumer_name": f"vision-{uuid4().hex[:8]}-{index}"},
                daemon=True,
                name=f"llm-redis-vision-worker-{index}",
            )
            worker.start()
            workers.append(worker)
        return workers

    def _local_foreground_worker_loop(self) -> None:
        """本地主循环队列 worker。"""

        self._consume_local_queue(self._local_foreground_queue)

    def _local_summary_worker_loop(self) -> None:
        """本地 Summary 队列 worker。"""

        self._consume_local_queue(self._local_summary_queue)

    def _local_fact_worker_loop(self) -> None:
        """本地 Fact 队列 worker。"""

        self._consume_local_queue(self._local_fact_queue)

    def _consume_local_queue(self, task_queue: queue.Queue[ScheduledLLMTask]) -> None:
        """从指定本地队列持续消费 generic 任务。"""

        while not self._shutdown_event.is_set():
            try:
                task = task_queue.get(timeout=self.config.task_schedule.local_queue_poll_seconds)
            except queue.Empty:
                continue
            try:
                self._execute_local_task(task)
            finally:
                task_queue.task_done()

    def _execute_local_task(self, task: ScheduledLLMTask) -> None:
        """执行一个本地 generic 任务。"""

        breaker = self._circuit_breakers[task.task_type]
        try:
            with self._global_semaphore:
                result = self._run_with_retries(task)
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            if not task.future.done():
                task.future.set_exception(exc)
            self._release_local_dedup_key(task.dedup_key, None)
            return
        breaker.record_success()
        if not task.future.done():
            task.future.set_result(result)
        self._release_local_dedup_key(task.dedup_key, None)

    def _redis_worker_loop(self, *, task_type: str, consumer_name: str) -> None:
        """持续消费 Redis Stream 中的 Chat 请求。"""

        assert self._backend is not None
        while not self._shutdown_event.is_set():
            item = self._backend.read_next_request(task_type=task_type, consumer_name=consumer_name)
            if item is None:
                continue
            entry_id, request = item
            self._execute_redis_chat_request(entry_id=entry_id, request=request)

    def _redis_summary_business_worker_loop(self, *, consumer_name: str) -> None:
        """持续消费 Redis Stream 中的 Summary 业务任务。"""

        assert self._backend is not None
        while not self._shutdown_event.is_set():
            item = self._backend.read_next_summary_job(consumer_name=consumer_name)
            if item is None:
                continue
            entry_id, request = item
            self._execute_redis_summary_job(entry_id=entry_id, request=request)

    def _execute_redis_chat_request(self, *, entry_id: str, request: SerializedChatRequest) -> None:
        """执行单条 Redis Chat 请求并写回结果。"""

        assert self._backend is not None
        if request.stream_channel:
            self._execute_redis_streaming_chat_request(
                request=request, entry_id=entry_id
            )
            return
        breaker = self._circuit_breakers[request.task_type]
        try:
            with self._global_semaphore:
                task = ScheduledLLMTask(
                    sequence=next(self._sequence),
                    task_id=request.task_id,
                    task_type=request.task_type,
                    operation=lambda: self._invoke_chat_request(request),
                    timeout_seconds=request.timeout_seconds,
                    max_retries=request.max_retries,
                    dedup_key=request.dedup_key,
                )
                message = self._run_with_retries(task)
                self._backend.write_result(
                    task_id=request.task_id,
                    result=SerializedChatResult.from_message(message),
                )
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            self._backend.write_result(task_id=request.task_id, result=SerializedChatResult.from_exception(exc))
            self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
            self._backend.ack_and_delete(task_type=request.task_type, entry_id=entry_id)
            return
        breaker.record_success()
        self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
        self._backend.ack_and_delete(task_type=request.task_type, entry_id=entry_id)

    def _execute_redis_streaming_chat_request(self, *, request: SerializedChatRequest, entry_id: str) -> None:
        """流式执行 Redis Chat 请求,通过 Pub/Sub 逐 token 推送,自行处理清理。"""

        assert self._backend is not None
        channel = request.stream_channel
        assert channel is not None
        breaker = self._circuit_breakers[request.task_type]
        success = False
        try:
            with self._global_semaphore:
                final_message: Any = None
                for chunk in self._stream_chat_request(request):
                    reasoning_delta = chunk.get("reasoning_delta", "")
                    if reasoning_delta:
                        self._backend.publish_stream_chunk(
                            channel=channel,
                            data={"reasoning_delta": reasoning_delta},
                        )
                    content_delta = chunk.get("content_delta", "")
                    if content_delta:
                        self._backend.publish_stream_chunk(
                            channel=channel,
                            data={"content_delta": content_delta},
                        )
                    if chunk.get("status") == "complete":
                        final_message = chunk.get("message")
                if final_message is not None:
                    self._backend.write_result(
                        task_id=request.task_id,
                        result=SerializedChatResult.from_message(final_message),
                    )
                self._backend.publish_stream_chunk(channel=channel, data={"status": "done"})
            success = True
        except Exception as exc:
            breaker.record_failure()
            self._backend.write_result(
                task_id=request.task_id,
                result=SerializedChatResult.from_exception(exc),
            )
            self._backend.publish_stream_chunk(
                channel=channel,
                data={"status": "error", "error_message": str(exc)},
            )
        finally:
            if success:
                breaker.record_success()
            self._backend.release_dedup_if_owner(
                dedup_key=request.dedup_key, task_id=request.task_id
            )
            self._backend.ack_and_delete(
                task_type=request.task_type, entry_id=entry_id
            )

    def _execute_redis_summary_job(self, *, entry_id: str, request: SerializedSummaryJobRequest) -> None:
        """执行单条 Redis Summary 业务任务并写回结果。"""

        assert self._backend is not None
        try:
            summary_text = self._run_summary_business_task(
                user_id=request.user_id,
                session_id=request.session_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._backend.write_result(
                task_id=request.task_id,
                result=SerializedSummaryJobResult.from_exception(exc),
            )
            self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
            self._backend.ack_and_delete_summary_job(entry_id=entry_id)
            return
        self._backend.write_result(
            task_id=request.task_id,
            result=SerializedSummaryJobResult.from_summary(summary_text),
        )
        self._backend.release_dedup_if_owner(dedup_key=request.dedup_key, task_id=request.task_id)
        self._backend.ack_and_delete_summary_job(entry_id=entry_id)

    def _invoke_chat_request(self, request: SerializedChatRequest) -> BaseMessage:
        """根据序列化请求构造模型并执行真实 Chat 调用。"""

        messages, _context_budget = self.prepare_messages_for_model(
            messages=request.restore_messages(),
            tool_names=request.tool_names,
            model_tier=request.model_tier,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            small_api_key=request.small_api_key,
            small_base_url=request.small_base_url,
            small_model_name=request.small_model_name,
            context_window_tokens=request.context_window_tokens,
            max_output_tokens=request.max_output_tokens,
        )
        model = self._get_chat_model(
            tool_names=request.tool_names,
            temperature=request.temperature,
            timeout_seconds=request.timeout_seconds,
            model_tier=request.model_tier,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            small_api_key=request.small_api_key,
            small_base_url=request.small_base_url,
            small_model_name=request.small_model_name,
        )
        with self._acquire_model_pool(request.model_tier):
            response = model.invoke(messages)
        if not isinstance(response, BaseMessage):
            raise TypeError("ChatOpenAI.invoke 未返回 LangChain BaseMessage。")
        if request.tool_names:
            response = recover_deepseek_dsml_tool_calls(
                response,
                allowed_tool_names=request.tool_names,
            )
        return response

    def _stream_chat_request(self, request: SerializedChatRequest) -> Iterator[dict[str, Any]]:
        """
        流式执行 Chat 请求,逐 token yield 增量内容。

        与 _invoke_chat_request() 不同,本方法使用 model.stream() 获取
        AIMessageChunk 流,实时产出每个 token 的增量文本。

        request: 序列化的 Chat 请求。
        """

        messages, _context_budget = self.prepare_messages_for_model(
            messages=request.restore_messages(),
            tool_names=request.tool_names,
            model_tier=request.model_tier,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            small_api_key=request.small_api_key,
            small_base_url=request.small_base_url,
            small_model_name=request.small_model_name,
            context_window_tokens=request.context_window_tokens,
            max_output_tokens=request.max_output_tokens,
        )
        model = self._get_chat_model(
            tool_names=request.tool_names,
            temperature=request.temperature,
            timeout_seconds=request.timeout_seconds,
            model_tier=request.model_tier,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            small_api_key=request.small_api_key,
            small_base_url=request.small_base_url,
            small_model_name=request.small_model_name,
        )
        recover_dsml = bool(request.tool_names)
        breaker = self._circuit_breakers[request.task_type]
        try:
            with self._acquire_model_pool(request.model_tier):
                merged: Any = None
                streamed_content_parts: list[str] = []
                dsml_stream_buffer = ""
                suppressing_dsml = False
                raw_content_chars = 0
                content_chunk_count = 0
                max_content_chunk_chars = 0
                mixed_reasoning_content_chunks = 0
                mixed_tool_content_chunks = 0
                # DeepSeek 等模型的思考内容(reasoning_content)与正文分开推送:
                # 单独 yield reasoning_delta 供上层实时透传,不污染 content_delta。
                for chunk in model.stream(messages):
                    if not isinstance(chunk, BaseMessage):
                        continue
                    tool_calls = getattr(chunk, "tool_calls", None) or []
                    reasoning = getattr(chunk, "additional_kwargs", {}).get("reasoning_content") or ""
                    # 个别 provider 以列表形式返回思考片段,统一拼接为字符串。
                    if isinstance(reasoning, list):
                        reasoning = "".join(str(part) for part in reasoning)
                    if isinstance(reasoning, str) and reasoning:
                        yield {"reasoning_delta": reasoning}
                    content_delta = getattr(chunk, "content", "") or ""
                    if isinstance(content_delta, str) and content_delta:
                        raw_content_chars += len(content_delta)
                        content_chunk_count += 1
                        max_content_chunk_chars = max(max_content_chunk_chars, len(content_delta))
                        streamed_content_parts.append(content_delta)
                        if reasoning:
                            mixed_reasoning_content_chunks += 1
                        if tool_calls:
                            mixed_tool_content_chunks += 1
                        # reasoning/content/tool_calls 是三个独立通道；DeepSeek
                        # 若把 DSML 错放进正文，则在流式边界先隐藏再于终态恢复。
                        visible_delta = content_delta
                        if recover_dsml:
                            visible_delta, dsml_stream_buffer, suppressing_dsml = (
                                filter_deepseek_dsml_stream_delta(
                                    dsml_stream_buffer,
                                    content_delta,
                                    suppressing=suppressing_dsml,
                                )
                            )
                        if visible_delta:
                            yield {"content_delta": visible_delta}
                    if merged is None:
                        merged = chunk
                    else:
                        merged += chunk
                if merged is None:
                    yield {"content_delta": "", "message": AIMessage(content=""), "status": "complete"}
                    return
                if recover_dsml and dsml_stream_buffer and not suppressing_dsml:
                    yield {"content_delta": dsml_stream_buffer}
                full_content: str = getattr(merged, "content", "") or ""
                if not isinstance(full_content, str):
                    full_content = ""
                merged_additional = getattr(merged, "additional_kwargs", None) or {}
                streamed_content = "".join(streamed_content_parts)
                content_mismatch = streamed_content != full_content
                reconciled_content_chars = (
                    len(full_content) - len(streamed_content)
                    if full_content.startswith(streamed_content)
                    else max(0, len(full_content) - len(streamed_content))
                )
                stream_diagnostics = {
                    "raw_content_chars": raw_content_chars,
                    "streamed_content_chars": len(streamed_content),
                    "final_content_chars": len(full_content),
                    "reconciled_content_chars": reconciled_content_chars,
                    "content_chunk_count": content_chunk_count,
                    "max_content_chunk_chars": max_content_chunk_chars,
                    "mixed_reasoning_content_chunks": mixed_reasoning_content_chunks,
                    "mixed_tool_content_chunks": mixed_tool_content_chunks,
                    "content_mismatch": content_mismatch,
                }
                if content_mismatch:
                    logger.warning(
                        "LLM 流式正文与终态不一致 | task_type=%s model_tier=%s "
                        "streamed_chars=%d final_chars=%d reconciled_chars=%d",
                        request.task_type,
                        request.model_tier,
                        len(streamed_content),
                        len(full_content),
                        reconciled_content_chars,
                    )
                final_message_kwargs = {
                    "content": full_content,
                    "tool_calls": getattr(merged, "tool_calls", None) or [],
                    "additional_kwargs": {
                        **merged_additional,
                        "stream_diagnostics": stream_diagnostics,
                    },
                    "response_metadata": getattr(merged, "response_metadata", None) or {},
                }
                usage_metadata = getattr(merged, "usage_metadata", None)
                if usage_metadata:
                    final_message_kwargs["usage_metadata"] = usage_metadata
                final_message = AIMessage(**final_message_kwargs)
                if recover_dsml:
                    final_message = recover_deepseek_dsml_tool_calls(
                        final_message,
                        allowed_tool_names=request.tool_names,
                    )
                yield {
                    "content_delta": final_message.content,
                    "message": final_message,
                    "status": "complete",
                    "stream_diagnostics": stream_diagnostics,
                }
        except Exception:
            breaker.record_failure()
            raise
        breaker.record_success()

    def _stream_chat_request_with_retries(self, request: SerializedChatRequest) -> Iterator[dict[str, Any]]:
        """
        流式执行 Chat 请求并在未输出任何 chunk 前对可恢复错误做退避重试。

        流式响应一旦已经向前端输出内容就不能安全重试,否则会造成重复 token。
        工具调用决策类响应通常在完成前不会输出自然语言 token,因此 429/Connection
        error 发生在首个 chunk 前时可以安全重试。
        """

        attempt = 0
        while True:
            emitted_any_chunk = False
            try:
                for chunk in self._stream_chat_request(request):
                    emitted_any_chunk = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                if emitted_any_chunk or attempt >= request.max_retries or not self._is_retryable_error(exc):
                    raise
                backoff_seconds = min(
                    self.task_config.initial_backoff_seconds * (2**attempt),
                    self.task_config.max_backoff_seconds,
                )
                jitter = random.uniform(0.0, backoff_seconds * 0.2)
                logger.warning(
                    "LLM Chat 流式调用失败,准备重试 | task_type=%s model_tier=%s attempt=%d/%d error=%s",
                    request.task_type,
                    request.model_tier,
                    attempt + 1,
                    request.max_retries,
                    exc,
                )
                time.sleep(backoff_seconds + jitter)
                attempt += 1

    def _run_summary_business_task(self, *, user_id: str, session_id: str) -> str | None:
        """执行 Summary 业务任务。"""

        if self.settings_service is not None and not self.settings_service.get_memory_config(
            user_id=user_id
        ).get("long_term_memory_enabled", True):
            logger.info("长期记忆已关闭,跳过会话摘要写入 | user=%s session=%s", user_id, session_id)
            return None

        from agent_service.services.memory.summary_service import SessionSummaryService

        summary_service = SessionSummaryService(
            config=self.config,
            task_scheduler=self,
        )
        return summary_service.summarize_session(user_id=user_id, session_id=session_id)

_SCHEDULER_REGISTRY: dict[str, LLMTaskScheduler] = {}
_SCHEDULER_REGISTRY_LOCK = threading.Lock()


def get_llm_task_scheduler(config: AgentConfig, settings_service: Any = None) -> LLMTaskScheduler:
    """获取按项目路径缓存的进程内调度器单例。"""

    scheduler_key = f"{config.storage.project_root}|{config.task_schedule.redis_url}"
    with _SCHEDULER_REGISTRY_LOCK:
        scheduler = _SCHEDULER_REGISTRY.get(scheduler_key)
        if scheduler is not None:
            if settings_service is not None:
                scheduler.settings_service = settings_service
            return scheduler
        scheduler = LLMTaskScheduler(config=config, settings_service=settings_service)
        _SCHEDULER_REGISTRY[scheduler_key] = scheduler
        return scheduler


def reset_llm_task_schedulers() -> None:
    """关闭并清空当前进程中的调度器注册表,主要供测试使用。"""

    with _SCHEDULER_REGISTRY_LOCK:
        for scheduler in _SCHEDULER_REGISTRY.values():
            scheduler.shutdown()
        _SCHEDULER_REGISTRY.clear()


atexit.register(reset_llm_task_schedulers)
