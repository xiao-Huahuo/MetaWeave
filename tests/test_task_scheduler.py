"""
LLM 任务调度器测试脚本。

功能说明:
本文件用于验证 `agent_service.task_schedule` 第一版多级调度器的关键行为,重点覆盖
重试退避、任务去重和结果复用等基础能力,避免后续把主 Agent 与后台任务重新改回
直接调用模型。

使用说明:
在项目根目录执行 `python -m pytest tests/test_task_scheduler.py`。
"""

from __future__ import annotations

from threading import Event
from threading import Thread
import time

from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.services.scheduler import BACKGROUND_SUMMARY_TASK
from agent_service.services.scheduler import FOREGROUND_AGENT_TASK
from agent_service.services.scheduler import SMALL_MODEL_TIER
from agent_service.services.scheduler import get_llm_task_scheduler
from agent_service.services.scheduler import reset_llm_task_schedulers
from agent_service.services.scheduler.redis_backend import SerializedChatRequest
from agent_service.services.scheduler.runtime import DeepSeekChatOpenAI


def make_scheduler_test_config() -> AgentConfig:
    """创建调度器测试专用配置。"""

    return AgentConfig.load_config(
        {
            "task_schedule": {
                "global_max_concurrency": 2,
                "foreground_agent_worker_count": 1,
                "background_summary_worker_count": 1,
                "background_fact_worker_count": 1,
                "foreground_queue_max_size": 8,
                "background_queue_max_size": 8,
                "max_retries": 1,
                "initial_backoff_seconds": 0.01,
                "max_backoff_seconds": 0.02,
                "foreground_timeout_seconds": 3,
                "summary_timeout_seconds": 3,
                "fact_resolution_timeout_seconds": 3,
                "circuit_breaker_failure_threshold": 3,
                "circuit_breaker_recovery_seconds": 1,
            }
        },
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )


def teardown_function() -> None:
    """每个测试结束后关闭调度器单例。"""

    reset_llm_task_schedulers()


def test_default_small_model_pool_allows_three_concurrent_calls() -> None:
    """默认小模型池必须提供三个并发许可。"""

    assert AgentConfig.TaskScheduleConfig().small_model_max_concurrency == 3


def test_llm_task_scheduler_retries_retryable_error() -> None:
    """验证调度器会对 overload/429 类错误进行重试。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    attempts = {"count": 0}

    def flaky_operation() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    result = scheduler.run(task_type=FOREGROUND_AGENT_TASK, operation=flaky_operation)

    assert result == "ok"
    assert attempts["count"] == 2


def test_llm_task_scheduler_deduplicates_summary_task_by_session() -> None:
    """验证同一 session 的 summary 任务会合并到同一个执行实例。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    started = Event()
    release = Event()
    calls = {"count": 0}

    def slow_summary() -> str:
        calls["count"] += 1
        started.set()
        release.wait(timeout=2)
        return "summary-ok"

    results: list[str] = []

    first_handle = scheduler.submit(
        task_type=BACKGROUND_SUMMARY_TASK,
        operation=slow_summary,
        dedup_key="session-1",
    )
    assert started.wait(timeout=1)

    def wait_duplicate() -> None:
        duplicate_handle = scheduler.submit(
            task_type=BACKGROUND_SUMMARY_TASK,
            operation=slow_summary,
            dedup_key="session-1",
        )
        results.append(duplicate_handle.wait(timeout=2))

    duplicate_thread = Thread(target=wait_duplicate, daemon=True)
    duplicate_thread.start()
    time.sleep(0.05)
    release.set()

    results.append(first_handle.wait(timeout=2))
    duplicate_thread.join(timeout=2)

    assert calls["count"] == 1
    assert results == ["summary-ok", "summary-ok"]


def test_llm_task_scheduler_invoke_chat_uses_local_fallback_without_redis(monkeypatch: object) -> None:
    """验证未配置 Redis 时,可序列化 Chat 请求会回退到本地队列执行。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    def fake_invoke_chat_request(_request: object) -> AIMessage:
        return AIMessage(content="chat-ok")

    monkeypatch.setattr(scheduler, "_invoke_chat_request", fake_invoke_chat_request)

    response = scheduler.invoke_chat(
        task_type=FOREGROUND_AGENT_TASK,
        messages=[HumanMessage(content="你好")],
    )

    assert isinstance(response, AIMessage)
    assert response.content == "chat-ok"


def test_llm_task_scheduler_stream_chat_retries_connection_error_before_first_chunk(monkeypatch: object) -> None:
    """流式 Chat 在首个 chunk 前遇到 Connection error 应按调度器退避重试。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    calls = {"count": 0}

    def fake_stream_chat_request(_request: object):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Connection error.")
        yield {"content_delta": "ok"}
        yield {"content_delta": "ok", "message": AIMessage(content="ok"), "status": "complete"}

    monkeypatch.setattr(scheduler, "_stream_chat_request", fake_stream_chat_request)

    chunks = list(
        scheduler.stream_chat(
            task_type=FOREGROUND_AGENT_TASK,
            messages=[HumanMessage(content="hello")],
        )
    )

    assert calls["count"] == 2
    assert chunks[-1]["status"] == "complete"


def test_llm_task_scheduler_submit_summary_job_uses_local_fallback_without_redis(monkeypatch: object) -> None:
    """验证未配置 Redis 时,Summary 业务任务会回退到本地队列执行。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    def fake_run_summary_business_task(*, user_id: str, session_id: str) -> str:
        return f"{user_id}:{session_id}"

    monkeypatch.setattr(scheduler, "_run_summary_business_task", fake_run_summary_business_task)

    handle = scheduler.submit_summary_job(user_id="u1", session_id="s1", dedup_key="s1")

    assert handle.wait(timeout=2) == "u1:s1"


def test_llm_task_scheduler_resolves_small_model_runtime() -> None:
    """验证调度器会为 `small` 模型池解析独立的小模型配置。"""

    config = AgentConfig.load_config(
        {
            "model": {
                "model_name": "large-model",
                "api_key": "large-key",
                "base_url": "https://large.example.com/v1",
                "small_model_name": "small-model",
                "small_model_api_key": "small-key",
                "small_model_base_url": "https://small.example.com/v1",
                "small_model_temperature": 0.3,
            }
        },
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    scheduler = get_llm_task_scheduler(config)

    model_name, api_key, base_url, temperature = scheduler._resolve_model_runtime(
        model_tier=SMALL_MODEL_TIER,
        requested_temperature=None,
    )

    assert model_name == "small-model"
    assert api_key == "small-key"
    assert base_url == "https://small.example.com/v1"
    assert temperature == 0.3


def test_observability_snapshot_matches_resolved_request_without_secrets() -> None:
    """Debug 快照必须保留最终消息、工具 schema 和实际模型参数，但不得泄露密钥。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    snapshot = scheduler.build_observability_snapshot(
        messages=[HumanMessage(content="inspect")],
        tool_names=["list_available_tools"],
        model_name="remote-model",
        api_key="secret-key",
        base_url="https://example.invalid/v1",
        node="agent",
    )

    assert snapshot["messages"] == [{"role": "user", "content": "inspect"}]
    assert snapshot["model"] == "remote-model"
    assert snapshot["context_budget"]["capacity_source"] == "service_ceiling_default"
    assert snapshot["context_budget"]["final_input_tokens"] <= snapshot["context_budget"]["input_budget_tokens"]
    assert snapshot["node"] == "agent"
    assert snapshot["tools"][0]["function"]["name"] == "list_available_tools"
    assert "secret-key" not in str(snapshot)


def test_llm_task_scheduler_small_model_falls_back_to_runtime_primary_key() -> None:
    """验证用户只配置主模型 key 时,small 模型池会复用该运行时 key 和 base_url。"""

    config = AgentConfig.load_config(
        {
            "model": {
                "model_name": "large-model",
                "small_model_name": "small-model",
                "small_model_temperature": 0.3,
            }
        },
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    scheduler = get_llm_task_scheduler(config)

    model_name, api_key, base_url, temperature = scheduler._resolve_model_runtime(
        model_tier=SMALL_MODEL_TIER,
        requested_temperature=None,
        api_key="user-large-key",
        base_url="https://user-large.example.com/v1",
        small_api_key=None,
        small_base_url=None,
    )

    assert model_name == "small-model"
    assert api_key == "user-large-key"
    assert base_url == "https://user-large.example.com/v1"
    assert temperature == 0.3


def test_llm_task_scheduler_small_model_inherits_runtime_large_model() -> None:
    """验证小模型未单独配置时,运行时复用用户配置的大模型。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    model_name, api_key, base_url, _temperature = scheduler._resolve_model_runtime(
        model_tier=SMALL_MODEL_TIER,
        requested_temperature=None,
        model_name="user-large-model",
        api_key="user-large-key",
        base_url="https://user-large.example.com/v1",
    )

    assert model_name == "user-large-model"
    assert api_key == "user-large-key"
    assert base_url == "https://user-large.example.com/v1"


def test_llm_task_scheduler_uses_local_qwen_for_both_tiers_without_remote_config() -> None:
    """大模型完全未配置时，前后台模型池都必须回退到同一个本地 Qwen。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    large = scheduler._resolve_model_runtime(model_tier=None, requested_temperature=None)
    small = scheduler._resolve_model_runtime(model_tier=SMALL_MODEL_TIER, requested_temperature=None)

    assert large[:3] == (scheduler.config.model.local_model_name, "", "")
    assert small[:3] == (scheduler.config.model.local_model_name, "", "")


def test_llm_task_scheduler_ignores_small_only_config_without_large_model() -> None:
    """大模型缺失时，即使残留小模型字段也必须统一使用本地 Qwen。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    resolved = scheduler._resolve_model_runtime(
        model_tier=SMALL_MODEL_TIER,
        requested_temperature=None,
        small_model_name="orphan-small",
        small_api_key="orphan-key",
        small_base_url="https://orphan.example.com/v1",
    )

    assert resolved[:3] == (scheduler.config.model.local_model_name, "", "")


def test_llm_task_scheduler_uses_local_qwen_for_incomplete_large_config() -> None:
    """只有模型名但没有 API Key 不算配置完成，必须回退本地 Qwen。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    large = scheduler._resolve_model_runtime(
        model_tier="large",
        requested_temperature=None,
        model_name="remote-without-key",
    )
    small = scheduler._resolve_model_runtime(
        model_tier=SMALL_MODEL_TIER,
        requested_temperature=None,
        model_name="remote-without-key",
    )

    assert large[:3] == (scheduler.config.model.local_model_name, "", "")
    assert small[:3] == (scheduler.config.model.local_model_name, "", "")


def test_llm_task_scheduler_stream_chat_yields_reasoning_delta(monkeypatch: object) -> None:
    """流式 Chat 应把 DeepSeek 思考文本(reasoning_content)作为 reasoning_delta 单独产出。

    思考文本与正文独立 yield,供上层实时透传渲染 Think 条;合并后的最终消息
    仍保留完整思考内容,便于落库后历史消息展示。
    """

    from langchain_core.messages import AIMessageChunk

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    class FakeModel:
        def stream(self, messages: object):
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "让我"})
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "想想"})
            yield AIMessageChunk(content="答案")

    monkeypatch.setattr(scheduler, "_get_chat_model", lambda **kwargs: FakeModel())

    chunks = list(
        scheduler.stream_chat(
            task_type=FOREGROUND_AGENT_TASK,
            messages=[HumanMessage(content="hi")],
        )
    )

    reasoning = [chunk["reasoning_delta"] for chunk in chunks if "reasoning_delta" in chunk]
    assert reasoning == ["让我", "想想"]
    content = [chunk["content_delta"] for chunk in chunks if "content_delta" in chunk and "status" not in chunk]
    assert content == ["答案"]
    assert chunks[-1]["status"] == "complete"
    final_message = chunks[-1]["message"]
    merged_reasoning = final_message.additional_kwargs.get("reasoning_content")
    assert "".join(merged_reasoning) == "让我想想"


def test_llm_task_scheduler_stream_chat_preserves_mixed_chunk_channels(monkeypatch: object) -> None:
    """Reasoning、正文和工具调用共存时不得静默丢弃正文 delta。"""

    from langchain_core.messages import AIMessageChunk

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())

    class FakeModel:
        """生成 DeepSeek thinking/tool-call 的混合字段 chunk。"""

        def stream(self, _messages: object):
            yield AIMessageChunk(
                content="正文一。",
                additional_kwargs={"reasoning_content": "思考一"},
            )
            yield AIMessageChunk(
                content="正文二。",
                tool_call_chunks=[{"name": "demo_tool", "args": "{}", "id": "call-1", "index": 0}],
            )

    monkeypatch.setattr(scheduler, "_get_chat_model", lambda **_kwargs: FakeModel())
    chunks = list(scheduler.stream_chat(
        task_type=FOREGROUND_AGENT_TASK,
        messages=[HumanMessage(content="hi")],
    ))

    assert [
        chunk["content_delta"]
        for chunk in chunks
        if chunk.get("status") != "complete" and chunk.get("content_delta")
    ] == ["正文一。", "正文二。"]
    assert [chunk["reasoning_delta"] for chunk in chunks if chunk.get("reasoning_delta")] == ["思考一"]
    assert chunks[-1]["stream_diagnostics"] == {
        "raw_content_chars": 8,
        "streamed_content_chars": 8,
        "final_content_chars": 8,
        "reconciled_content_chars": 0,
        "content_chunk_count": 2,
        "max_content_chunk_chars": 4,
        "mixed_reasoning_content_chunks": 1,
        "mixed_tool_content_chunks": 1,
        "content_mismatch": False,
    }


def test_redis_streaming_worker_publishes_reasoning_and_content(monkeypatch: object) -> None:
    """Redis worker 必须与本地流保持 reasoning/content 事件一致。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    request = SerializedChatRequest.from_messages(
        task_id="stream-1",
        task_type=FOREGROUND_AGENT_TASK,
        messages=[HumanMessage(content="hi")],
        tool_names=[],
        timeout_seconds=3,
        max_retries=0,
        dedup_key="",
        temperature=None,
        model_tier="large",
    )
    request.stream_channel = "stream:test"

    class FakeBackend:
        """记录 Redis worker 对外发布的无正文事件。"""

        def __init__(self) -> None:
            self.published: list[dict[str, object]] = []

        def publish_stream_chunk(self, *, channel: str, data: dict[str, object]) -> None:
            assert channel == "stream:test"
            self.published.append(data)

        def write_result(self, **_kwargs: object) -> None:
            pass

        def release_dedup_if_owner(self, **_kwargs: object) -> None:
            pass

        def ack_and_delete(self, **_kwargs: object) -> None:
            pass

    backend = FakeBackend()
    scheduler._backend = backend  # type: ignore[assignment]
    monkeypatch.setattr(scheduler, "_stream_chat_request", lambda _request: iter([
        {"reasoning_delta": "思考"},
        {"content_delta": "回答"},
        {"message": AIMessage(content="回答"), "status": "complete"},
    ]))

    scheduler._execute_redis_streaming_chat_request(request=request, entry_id="entry-1")

    assert {"reasoning_delta": "思考"} in backend.published
    assert {"content_delta": "回答"} in backend.published
    assert backend.published[-1] == {"status": "done"}


def test_deepseek_adapter_preserves_reasoning_chunks_results_and_requests() -> None:
    """DeepSeek 非标准 reasoning_content 必须稳定双向转换，不能依赖 LangChain 偶然透传。"""

    from langchain_core.messages import AIMessageChunk

    model = DeepSeekChatOpenAI(model="deepseek-v4-flash", api_key="test-key")
    generation = model._convert_chunk_to_generation_chunk(
        {
            "model": "deepseek-v4-flash",
            "choices": [{
                "delta": {"role": "assistant", "content": "回答", "reasoning_content": "思考"},
                "finish_reason": None,
            }],
        },
        AIMessageChunk,
        None,
    )
    assert generation is not None
    assert generation.message.additional_kwargs["reasoning_content"] == "思考"

    result = model._create_chat_result({
        "model": "deepseek-v4-flash",
        "choices": [{
            "message": {"role": "assistant", "content": "回答", "reasoning_content": "完整思考"},
            "finish_reason": "stop",
        }],
    })
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "完整思考"

    payload = model._get_request_payload([
        HumanMessage(content="先查询"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "应回传思考"},
            tool_calls=[{"name": "demo_tool", "args": {}, "id": "call-1", "type": "tool_call"}],
        ),
        ToolMessage(content="工具结果", tool_call_id="call-1"),
    ])
    assert payload["messages"] == [
        {"content": "先查询", "role": "user"},
        {
            "content": None,
            "role": "assistant",
            "tool_calls": [{"type": "function", "id": "call-1", "function": {"name": "demo_tool", "arguments": "{}"}}],
            "reasoning_content": "应回传思考",
        },
        {"content": "工具结果", "role": "tool", "tool_call_id": "call-1"},
    ]


def test_deepseek_dsml_content_is_recovered_as_tool_calls(monkeypatch: object) -> None:
    """DeepSeek V4 的正文 DSML 必须转回工具调用，不能作为最终回复泄漏。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    dsml = (
        "正在生成挂载地址。\n"
        '<｜DSML｜tool_calls>\n<｜DSML｜invoke name="get_knowledge_file_url">\n'
        '<｜DSML｜parameter name="path" string="true">游戏资料/原神/日月前事.md'
        '</｜DSML｜parameter>\n</｜DSML｜invoke>\n'
        '<｜DSML｜invoke name="get_knowledge_file_url">\n'
        '<｜DSML｜parameter name="path" string="true">游戏资料/原神/日月前事_来源存档.html'
        '</｜DSML｜parameter>\n</｜DSML｜invoke>\n</｜DSML｜tool_calls>'
    )
    request = SerializedChatRequest.from_messages(
        task_id="dsml-invoke",
        task_type=FOREGROUND_AGENT_TASK,
        messages=[HumanMessage(content="展示日月前事")],
        tool_names=["get_knowledge_file_url"],
        timeout_seconds=3,
        max_retries=0,
        api_key="test-key",
        model_name="deepseek-v4-flash",
    )

    class FakeModel:
        """返回提供商未结构化的 DeepSeek V4 DSML 正文。"""

        @staticmethod
        def invoke(_messages: object) -> AIMessage:
            """模拟一次非流式模型调用。"""

            return AIMessage(content=dsml)

    monkeypatch.setattr(scheduler, "prepare_messages_for_model", lambda **_kwargs: ([], {}))
    monkeypatch.setattr(scheduler, "_get_chat_model", lambda **_kwargs: FakeModel())

    response = scheduler._invoke_chat_request(request)

    assert response.content == "正在生成挂载地址。\n"
    assert [call["name"] for call in response.tool_calls] == [
        "get_knowledge_file_url",
        "get_knowledge_file_url",
    ]
    assert [call["args"] for call in response.tool_calls] == [
        {"path": "游戏资料/原神/日月前事.md"},
        {"path": "游戏资料/原神/日月前事_来源存档.html"},
    ]


def test_deepseek_dsml_is_hidden_while_streaming_and_recovered(monkeypatch: object) -> None:
    """真实双竖线 DSML 经本地模型回退且跨 chunk 分割时也不得泄漏。"""

    scheduler = get_llm_task_scheduler(make_scheduler_test_config())
    request = SerializedChatRequest.from_messages(
        task_id="dsml-stream",
        task_type=FOREGROUND_AGENT_TASK,
        messages=[HumanMessage(content="展示日月前事")],
        tool_names=["get_current_time"],
        timeout_seconds=3,
        max_retries=0,
        model_name="deepseek-v4-flash",
    )

    class FakeStreamingModel:
        """把 DSML 起始标记拆开，复现真实 token 流边界。"""

        @staticmethod
        def stream(_messages: object) -> object:
            """依次返回普通正文与被拆分的 DSML token。"""

            yield AIMessageChunk(content="正在生成挂载地址。\n<｜｜DS")
            yield AIMessageChunk(
                content=(
                    'ML｜｜calls>\n<｜｜DSML｜｜invoke name="get_current_time">\n'
                    '</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜calls>'
                )
            )

    monkeypatch.setattr(scheduler, "prepare_messages_for_model", lambda **_kwargs: ([], {}))
    monkeypatch.setattr(scheduler, "_get_chat_model", lambda **_kwargs: FakeStreamingModel())

    chunks = list(scheduler._stream_chat_request(request))
    visible = "".join(chunk.get("content_delta", "") for chunk in chunks if chunk.get("status") != "complete")
    final_message = chunks[-1]["message"]

    assert visible == "正在生成挂载地址。\n"
    assert final_message.content == "正在生成挂载地址。\n"
    assert final_message.tool_calls[0]["name"] == "get_current_time"
    assert final_message.tool_calls[0]["args"] == {}


def test_namespaced_deepseek_model_uses_reasoning_adapter() -> None:
    """模型市场常见的命名空间标识也必须启用 DeepSeek thinking 协议。"""

    config = make_scheduler_test_config()
    scheduler = get_llm_task_scheduler(config)

    model = scheduler._get_chat_model(
        tool_names=[],
        temperature=0,
        timeout_seconds=3,
        model_tier="large",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model_name="unsloth/deepseek-v3.2",
    )

    assert isinstance(model, DeepSeekChatOpenAI)
