"""
Redis Stream 调度后端模块。

功能说明:
本文件实现 `LLMTaskScheduler` 的 Redis 生产后端。它负责把可序列化的 LLM 请求
写入 Redis Stream,由 worker 使用 consumer group 消费,并把结果回写到 Redis
 结果键中,供提交请求的进程轮询等待。第一版重点覆盖:

1. 多进程共享任务队列
2. 基于 consumer group 的 ACK
3. stale pending message 认领
4. 结果回写与轮询等待
5. 基于 Redis 的去重键共享

使用说明:
仅供 `scheduler.py` 内部使用。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict


@dataclass(slots=True)
class SerializedChatRequest:
    """
    可序列化的 Chat 模型请求。

    task_id: 任务 ID。
    task_type: 任务类型。
    messages_json: LangChain message 序列化结果。
    tool_names: 需要绑定的工具名称列表。
    timeout_seconds: 任务超时时间。
    max_retries: 最大重试次数。
    dedup_key: 可选去重键。
    temperature: 可选温度覆盖值。
    model_tier: 模型池等级,支持 `large`、`small` 或 `vision`。
    """

    task_id: str
    task_type: str
    messages_json: list[dict[str, Any]]
    tool_names: list[str]
    timeout_seconds: float
    max_retries: int
    dedup_key: str | None = None
    temperature: float | None = None
    model_tier: str = "large"
    stream_channel: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    small_api_key: str | None = None
    small_base_url: str | None = None
    small_model_name: str | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None

    @classmethod
    def from_messages(
        cls,
        *,
        task_id: str,
        task_type: str,
        messages: list[BaseMessage],
        tool_names: list[str] | None,
        timeout_seconds: float,
        max_retries: int,
        dedup_key: str | None = None,
        temperature: float | None = None,
        model_tier: str = "large",
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        context_window_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> "SerializedChatRequest":
        """从 LangChain messages 构造可序列化请求。"""

        return cls(
            task_id=task_id,
            task_type=task_type,
            messages_json=messages_to_dict(messages),
            tool_names=list(tool_names or []),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            dedup_key=dedup_key,
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

    def to_stream_fields(self) -> dict[str, str]:
        """转换为 Redis Stream 字段映射。"""

        return {"payload": json.dumps(self.to_dict(), ensure_ascii=False)}

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "messages_json": self.messages_json,
            "tool_names": self.tool_names,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "dedup_key": self.dedup_key,
            "temperature": self.temperature,
            "model_tier": self.model_tier,
            "stream_channel": self.stream_channel,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "small_api_key": self.small_api_key,
            "small_base_url": self.small_base_url,
            "small_model_name": self.small_model_name,
            "context_window_tokens": self.context_window_tokens,
            "max_output_tokens": self.max_output_tokens,
        }

    @classmethod
    def from_stream_entry(cls, entry_fields: dict[str, Any]) -> "SerializedChatRequest":
        """从 Redis Stream 条目恢复请求对象。"""

        payload = json.loads(str(entry_fields["payload"]))
        return cls(
            task_id=str(payload["task_id"]),
            task_type=str(payload["task_type"]),
            messages_json=list(payload["messages_json"]),
            tool_names=[str(name) for name in payload.get("tool_names", [])],
            timeout_seconds=float(payload["timeout_seconds"]),
            max_retries=int(payload["max_retries"]),
            dedup_key=str(payload["dedup_key"]) if payload.get("dedup_key") else None,
            temperature=float(payload["temperature"]) if payload.get("temperature") is not None else None,
            model_tier=str(payload.get("model_tier") or "large"),
            stream_channel=str(payload["stream_channel"]) if payload.get("stream_channel") else None,
            api_key=str(payload["api_key"]) if payload.get("api_key") else None,
            base_url=str(payload["base_url"]) if payload.get("base_url") else None,
            model_name=str(payload["model_name"]) if payload.get("model_name") else None,
            small_api_key=str(payload["small_api_key"]) if payload.get("small_api_key") else None,
            small_base_url=str(payload["small_base_url"]) if payload.get("small_base_url") else None,
            small_model_name=str(payload["small_model_name"]) if payload.get("small_model_name") else None,
            context_window_tokens=(
                int(payload["context_window_tokens"])
                if payload.get("context_window_tokens") is not None
                else None
            ),
            max_output_tokens=(
                int(payload["max_output_tokens"])
                if payload.get("max_output_tokens") is not None
                else None
            ),
        )

    def restore_messages(self) -> list[BaseMessage]:
        """将序列化消息恢复为 LangChain messages。"""

        return list(messages_from_dict(self.messages_json))


@dataclass(slots=True)
class SerializedChatResult:
    """
    Redis 中保存的 LLM 请求结果。

    status: `success` 或 `error`。
    response_message_json: 成功时返回的单条消息 JSON。
    error_type: 失败异常类型。
    error_message: 失败异常文本。
    """

    status: str
    response_message_json: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None

    @classmethod
    def from_message(cls, message: BaseMessage) -> "SerializedChatResult":
        """从 LangChain message 生成成功结果。"""

        return cls(
            status="success",
            response_message_json=messages_to_dict([message])[0],
        )

    @classmethod
    def from_exception(cls, exc: Exception) -> "SerializedChatResult":
        """从异常生成失败结果。"""

        return cls(
            status="error",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )

    def to_mapping(self) -> dict[str, str]:
        """转换为 Redis Hash 字段映射。"""

        payload = {
            "status": self.status,
            "response_message_json": self.response_message_json,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
        return {"payload": json.dumps(payload, ensure_ascii=False)}

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "SerializedChatResult | None":
        """从 Redis Hash 恢复结果对象。"""

        payload = mapping.get("payload")
        if not payload:
            return None
        raw = json.loads(str(payload))
        response_message_json = raw.get("response_message_json")
        if response_message_json is not None and not isinstance(response_message_json, dict):
            response_message_json = None
        return cls(
            status=str(raw["status"]),
            response_message_json=response_message_json,
            error_type=str(raw["error_type"]) if raw.get("error_type") else None,
            error_message=str(raw["error_message"]) if raw.get("error_message") else None,
        )

    def to_python(self) -> BaseMessage:
        """将结果恢复为 Python 对象或抛出异常。"""

        if self.status == "success" and self.response_message_json is not None:
            return messages_from_dict([self.response_message_json])[0]
        error_type = self.error_type or "LLMTaskSchedulerError"
        error_message = self.error_message or "LLM 任务失败但缺少错误信息。"
        raise RuntimeError(f"{error_type}: {error_message}")


@dataclass(slots=True)
class SerializedSummaryJobRequest:
    """
    可序列化的 Summary 业务任务请求。

    task_id: 任务 ID。
    user_id: 用户 ID。
    session_id: 会话 ID。
    dedup_key: 可选去重键。
    """

    task_id: str
    user_id: str
    session_id: str
    dedup_key: str | None = None

    def to_stream_fields(self) -> dict[str, str]:
        """转换为 Redis Stream 字段映射。"""

        return {"payload": json.dumps(self.to_dict(), ensure_ascii=False)}

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "dedup_key": self.dedup_key,
        }

    @classmethod
    def from_stream_entry(cls, entry_fields: dict[str, Any]) -> "SerializedSummaryJobRequest":
        """从 Redis Stream 条目恢复请求对象。"""

        payload = json.loads(str(entry_fields["payload"]))
        dedup_key = payload.get("dedup_key")
        return cls(
            task_id=str(payload["task_id"]),
            user_id=str(payload["user_id"]),
            session_id=str(payload["session_id"]),
            dedup_key=str(dedup_key) if dedup_key else None,
        )


@dataclass(slots=True)
class SerializedSummaryJobResult:
    """
    Summary 业务任务结果。

    status: `success` 或 `error`。
    summary_text: 成功时的摘要文本,可为空。
    error_type: 异常类型。
    error_message: 异常信息。
    """

    status: str
    summary_text: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @classmethod
    def from_summary(cls, summary_text: str | None) -> "SerializedSummaryJobResult":
        """从摘要文本生成成功结果。"""

        return cls(status="success", summary_text=summary_text)

    @classmethod
    def from_exception(cls, exc: Exception) -> "SerializedSummaryJobResult":
        """从异常生成失败结果。"""

        return cls(
            status="error",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )

    def to_mapping(self) -> dict[str, str]:
        """转换为 Redis Hash 字段映射。"""

        payload = {
            "status": self.status,
            "summary_text": self.summary_text,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
        return {"payload": json.dumps(payload, ensure_ascii=False)}

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "SerializedSummaryJobResult | None":
        """从 Redis Hash 恢复结果对象。"""

        payload = mapping.get("payload")
        if not payload:
            return None
        raw = json.loads(str(payload))
        summary_text = raw.get("summary_text")
        return cls(
            status=str(raw["status"]),
            summary_text=str(summary_text) if summary_text is not None else None,
            error_type=str(raw["error_type"]) if raw.get("error_type") else None,
            error_message=str(raw["error_message"]) if raw.get("error_message") else None,
        )

    def to_python(self) -> str | None:
        """将结果恢复为 Python 对象或抛出异常。"""

        if self.status == "success":
            return self.summary_text
        error_type = self.error_type or "SummaryJobError"
        error_message = self.error_message or "Summary 任务失败但缺少错误信息。"
        raise RuntimeError(f"{error_type}: {error_message}")


class RedisStreamLLMBackend:
    """
    基于 Redis Stream 的 LLM 调度后端。

    redis_url: Redis 连接地址。
    key_prefix: 键前缀。
    consumer_group: consumer group 名称。
    result_ttl_seconds: 结果保留秒数。
    dedup_ttl_seconds: 去重键保留秒数。
    block_timeout_ms: 阻塞读取超时毫秒数。
    visibility_timeout_ms: stale pending message 认领阈值毫秒数。
    result_poll_interval_seconds: 结果轮询间隔。
    stream_maxlen: Stream 近似裁剪上限。
    """

    def __init__(
        self,
        *,
        redis_url: str,
        key_prefix: str,
        consumer_group: str,
        result_ttl_seconds: int,
        dedup_ttl_seconds: int,
        block_timeout_ms: int,
        visibility_timeout_ms: int,
        result_poll_interval_seconds: float,
        stream_maxlen: int,
    ) -> None:
        """初始化 Redis 客户端和基础配置。"""

        try:
            from redis import Redis
            from redis.exceptions import ResponseError
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("启用 Redis 任务队列前请先安装 redis 依赖。") from exc

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.response_error_class = ResponseError
        self.key_prefix = key_prefix
        self.consumer_group = consumer_group
        self.result_ttl_seconds = max(result_ttl_seconds, 1)
        self.dedup_ttl_seconds = max(dedup_ttl_seconds, 1)
        self.block_timeout_ms = max(block_timeout_ms, 1)
        self.visibility_timeout_ms = max(visibility_timeout_ms, 1)
        self.result_poll_interval_seconds = max(result_poll_interval_seconds, 0.01)
        self.stream_maxlen = max(stream_maxlen, 1)

    def enqueue_chat_request(self, request: SerializedChatRequest, *, queue_max_size: int) -> None:
        """将序列化请求写入对应 Stream。"""

        stream_key = self._stream_key(request.task_type)
        self.ensure_group(request.task_type)
        if self.client.xlen(stream_key) >= queue_max_size:
            raise RuntimeError(f"Redis Stream {stream_key} 已达到上限 {queue_max_size}。")
        self.client.xadd(
            stream_key,
            fields=request.to_stream_fields(),
            maxlen=self.stream_maxlen,
            approximate=True,
        )

    def enqueue_summary_job(self, request: SerializedSummaryJobRequest, *, queue_max_size: int) -> None:
        """将 Summary 业务任务写入专用 Stream。"""

        stream_key = self._summary_stream_key()
        self.ensure_summary_group()
        if self.client.xlen(stream_key) >= queue_max_size:
            raise RuntimeError(f"Redis Stream {stream_key} 已达到上限 {queue_max_size}。")
        self.client.xadd(
            stream_key,
            fields=request.to_stream_fields(),
            maxlen=self.stream_maxlen,
            approximate=True,
        )

    def ensure_group(self, task_type: str) -> None:
        """确保任务类型对应的 consumer group 已存在。"""

        stream_key = self._stream_key(task_type)
        try:
            self.client.xgroup_create(
                name=stream_key,
                groupname=self.consumer_group,
                id="0-0",
                mkstream=True,
            )
        except self.response_error_class as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def ensure_summary_group(self) -> None:
        """确保 Summary 业务队列 consumer group 已存在。"""

        stream_key = self._summary_stream_key()
        try:
            self.client.xgroup_create(
                name=stream_key,
                groupname=self.consumer_group,
                id="0-0",
                mkstream=True,
            )
        except self.response_error_class as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def register_dedup_or_get_existing(self, *, dedup_key: str, task_id: str) -> str:
        """注册 Redis 去重键,若已存在则返回现有 task_id。"""

        redis_key = self._dedup_key(dedup_key)
        if self.client.set(redis_key, task_id, ex=self.dedup_ttl_seconds, nx=True):
            return task_id
        existing_task_id = self.client.get(redis_key)
        return str(existing_task_id or task_id)

    def release_dedup_if_owner(self, *, dedup_key: str | None, task_id: str) -> None:
        """仅在当前 task_id 是所有者时释放去重键。"""

        if not dedup_key:
            return
        redis_key = self._dedup_key(dedup_key)
        current_task_id = self.client.get(redis_key)
        if current_task_id == task_id:
            self.client.delete(redis_key)

    def write_result(self, *, task_id: str, result: SerializedChatResult) -> None:
        """将任务结果写入 Redis。"""

        result_key = self._result_key(task_id)
        self.client.hset(result_key, mapping=result.to_mapping())
        self.client.expire(result_key, self.result_ttl_seconds)

    def wait_for_result(self, *, task_id: str, timeout: float | None) -> BaseMessage:
        """轮询等待任务结果。"""

        deadline = None if timeout is None else time.time() + timeout
        result_key = self._result_key(task_id)
        while True:
            mapping = self.client.hgetall(result_key)
            result = SerializedChatResult.from_mapping(mapping)
            if result is not None:
                return result.to_python()
            if deadline is not None and time.time() >= deadline:
                raise TimeoutError(f"等待 Redis LLM 任务 {task_id} 结果超时。")
            time.sleep(self.result_poll_interval_seconds)

    def wait_for_summary_result(self, *, task_id: str, timeout: float | None) -> str | None:
        """轮询等待 Summary 业务任务结果。"""

        deadline = None if timeout is None else time.time() + timeout
        result_key = self._result_key(task_id)
        while True:
            mapping = self.client.hgetall(result_key)
            result = SerializedSummaryJobResult.from_mapping(mapping)
            if result is not None:
                return result.to_python()
            if deadline is not None and time.time() >= deadline:
                raise TimeoutError(f"等待 Redis Summary 任务 {task_id} 结果超时。")
            time.sleep(self.result_poll_interval_seconds)

    # ---- Streaming (Pub/Sub) ----

    def publish_stream_chunk(self, *, channel: str, data: dict[str, Any]) -> None:
        """向指定 Pub/Sub 频道推送流式 chunk。"""

        self.client.publish(channel, json.dumps(data, ensure_ascii=False))

    def subscribe_stream(self, *, channel: str):
        """订阅流式频道,返回可迭代的 pubsub 对象。"""

        pubsub = self.client.pubsub()
        pubsub.subscribe(channel)
        return pubsub

    def read_next_request(
        self,
        *,
        task_type: str,
        consumer_name: str,
    ) -> tuple[str, SerializedChatRequest] | None:
        """读取一条新任务或认领一条超时 pending 任务。"""

        self.ensure_group(task_type)
        stream_key = self._stream_key(task_type)
        response = self.client.xreadgroup(
            groupname=self.consumer_group,
            consumername=consumer_name,
            streams={stream_key: ">"},
            count=1,
            block=self.block_timeout_ms,
        )
        if response:
            _, entries = response[0]
            entry_id, entry_fields = entries[0]
            return str(entry_id), SerializedChatRequest.from_stream_entry(entry_fields)
        claimed = self.client.xautoclaim(
            name=stream_key,
            groupname=self.consumer_group,
            consumername=consumer_name,
            min_idle_time=self.visibility_timeout_ms,
            start_id="0-0",
            count=1,
        )
        claimed_entries = claimed[1] if len(claimed) > 1 else []
        if claimed_entries:
            entry_id, entry_fields = claimed_entries[0]
            return str(entry_id), SerializedChatRequest.from_stream_entry(entry_fields)
        return None

    def read_next_summary_job(self, *, consumer_name: str) -> tuple[str, SerializedSummaryJobRequest] | None:
        """读取一条新的 Summary 业务任务或认领超时 pending 任务。"""

        self.ensure_summary_group()
        stream_key = self._summary_stream_key()
        response = self.client.xreadgroup(
            groupname=self.consumer_group,
            consumername=consumer_name,
            streams={stream_key: ">"},
            count=1,
            block=self.block_timeout_ms,
        )
        if response:
            _, entries = response[0]
            entry_id, entry_fields = entries[0]
            return str(entry_id), SerializedSummaryJobRequest.from_stream_entry(entry_fields)
        claimed = self.client.xautoclaim(
            name=stream_key,
            groupname=self.consumer_group,
            consumername=consumer_name,
            min_idle_time=self.visibility_timeout_ms,
            start_id="0-0",
            count=1,
        )
        claimed_entries = claimed[1] if len(claimed) > 1 else []
        if claimed_entries:
            entry_id, entry_fields = claimed_entries[0]
            return str(entry_id), SerializedSummaryJobRequest.from_stream_entry(entry_fields)
        return None

    def ack_and_delete(self, *, task_type: str, entry_id: str) -> None:
        """ACK 并删除已处理完成的 Stream 条目。"""

        stream_key = self._stream_key(task_type)
        self.client.xack(stream_key, self.consumer_group, entry_id)
        self.client.xdel(stream_key, entry_id)

    def ack_and_delete_summary_job(self, *, entry_id: str) -> None:
        """ACK 并删除已处理完成的 Summary 业务条目。"""

        stream_key = self._summary_stream_key()
        self.client.xack(stream_key, self.consumer_group, entry_id)
        self.client.xdel(stream_key, entry_id)

    def _stream_key(self, task_type: str) -> str:
        """构造任务类型对应的 Stream 键名。"""

        return f"{self.key_prefix}:stream:{task_type}"

    def _summary_stream_key(self) -> str:
        """构造 Summary 业务队列的 Stream 键名。"""

        return f"{self.key_prefix}:stream:summary_job"

    def _result_key(self, task_id: str) -> str:
        """构造结果键名。"""

        return f"{self.key_prefix}:result:{task_id}"

    def _dedup_key(self, dedup_key: str) -> str:
        """构造去重键名。"""

        return f"{self.key_prefix}:dedup:{dedup_key}"
