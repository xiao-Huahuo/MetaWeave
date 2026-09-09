"""
本地 Qwen 消息解析与工具调用适配测试。

使用说明:
这些测试只验证纯文本协议，不加载真实模型权重。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_service.services.local_qwen.service import (
    LocalQwenChatModel,
    LocalQwenService,
    parse_qwen_response,
    start_local_qwen_download,
)
from agent_service.core.model_status import ModelState, get_model_status
from agent_service.services.scheduler import get_llm_task_scheduler, reset_llm_task_schedulers
from langchain_core.messages import HumanMessage, SystemMessage
from agent_service.core.agent_config import AgentConfig
from agent_service.tools.tool_registry import ToolRegistry


def test_parse_qwen_response_extracts_tool_calls_without_leaking_markup() -> None:
    """Qwen 工具标签必须转换成 LangChain tool_calls。"""

    message = parse_qwen_response(
        '<tool_call>{"name":"understand_image","arguments":{"attachment":"a.png"}}</tool_call>'
    )

    assert message.content == ""
    assert message.tool_calls[0]["name"] == "understand_image"
    assert message.tool_calls[0]["args"] == {"attachment": "a.png"}


def test_parse_qwen_response_preserves_normal_text() -> None:
    """没有工具标签时保持普通生成文本。"""

    message = parse_qwen_response("这是本地模型的回答。")

    assert message.content == "这是本地模型的回答。"
    assert message.tool_calls == []


def test_local_qwen_serializes_text_as_multimodal_content_blocks() -> None:
    """Qwen3.5 Processor 要求纯文本消息也使用多模态内容块列表。"""

    serialized = LocalQwenService._serialize_messages([HumanMessage(content="你好")])

    assert serialized == [{
        "role": "user",
        "content": [{"type": "text", "text": "你好"}],
    }]


def test_local_qwen_compacts_long_system_context_for_cpu_prefill() -> None:
    """本地 CPU 模型应保留长系统上下文首尾，但不得预填充完整云端提示。"""

    serialized = LocalQwenService._serialize_messages([
        SystemMessage(content="开" * 1200),
        SystemMessage(content="结" * 1200),
        HumanMessage(content="你好"),
    ])
    system_text = serialized[0]["content"][0]["text"]

    assert len(system_text) == 2402
    assert system_text.startswith("开")
    assert system_text.endswith("结")
    assert "本地上下文已压缩" not in system_text


def test_local_qwen_runtime_dependencies_stay_cpu_compatible() -> None:
    """本地多模态模型必须声明匹配版本的 CPU Torch、Torchvision 与 Transformers。"""

    project_root = Path(__file__).resolve().parents[1]
    requirements = (project_root / "agent_service" / "requirements.txt").read_text(encoding="utf-8")
    spec = (project_root / "AgentService.spec").read_text(encoding="utf-8")

    assert "torch==2.11.0+cpu" in requirements
    assert "torchvision==0.26.0+cpu" in requirements
    assert "transformers==5.2.0" in requirements
    assert "sentence-transformers==6.0.0" in requirements
    assert "['xlrd', 'torchvision', *_paddlex_hiddenimports]" in spec
    assert "'torchvision'," not in spec.split("excludes=[", maxsplit=1)[1]


def test_local_qwen_loads_fp32_on_avx2_cpu(tmp_path, monkeypatch: object) -> None:
    """AVX2 CPU 不得使用会落入极慢软件模拟路径的 BF16 权重。"""

    import agent_service.services.local_qwen.service as local_module

    config = AgentConfig.load_config(
        {"storage": {"local_model_dir": str(tmp_path / "models")}},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    captured: dict[str, object] = {}
    fake_torch = SimpleNamespace(float32=object(), bfloat16=object())

    class _FakeProcessorFactory:
        """返回不加载真实权重的 processor 占位对象。"""

        @staticmethod
        def from_pretrained(path: str) -> object:  # noqa: ARG004
            return object()

    class _FakeModel:
        """模拟 Transformers 模型的链式加载接口。"""

        def eval(self):  # noqa: ANN201
            return self

        def to(self, device: str):  # noqa: ANN201, ARG002
            return self

    class _FakeModelFactory:
        """记录本地 Qwen 实际请求的权重 dtype。"""

        @staticmethod
        def from_pretrained(path: str, **kwargs: object) -> _FakeModel:  # noqa: ARG004
            captured.update(kwargs)
            return _FakeModel()

    monkeypatch.setattr(local_module, "is_model_available", lambda _path: True)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModelForImageTextToText=_FakeModelFactory,
            AutoProcessor=_FakeProcessorFactory,
        ),
    )

    LocalQwenService(config=config).ensure_loaded()

    assert captured["dtype"] is fake_torch.float32


def test_image_understanding_tool_is_registered() -> None:
    """主 Agent 必须能够显式选择识图工具。"""

    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    definition = ToolRegistry.with_builtin_tools(config=config).get("understand_image")

    assert definition is not None
    assert definition.display_name == "识图"


def test_image_understanding_tool_does_not_load_qwen_when_disabled(monkeypatch: object) -> None:
    """用户关闭识图时，即使 Agent 选择工具也必须在 Qwen 服务调用前返回。"""

    import agent_service.services.local_qwen.service as local_module
    import agent_service.tools.builtin.knowledge as knowledge_module

    settings = SimpleNamespace(
        is_vision_understanding_enabled_for_user=lambda *, user_id: False,
    )
    runtime = SimpleNamespace(user_id="u1", settings_service=settings)
    monkeypatch.setattr(knowledge_module, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(
        local_module,
        "get_local_qwen_service",
        lambda _config: (_ for _ in ()).throw(AssertionError("Qwen must not load")),
    )

    result = knowledge_module.understand_image()

    assert "识图功能未开启" in result
    assert "不会加载本地 Qwen" in result


def test_scheduler_builds_local_qwen_adapter_without_remote_credentials() -> None:
    """完全未配置远程模型时，调度器必须构造本地适配器而非 ChatOpenAI。"""

    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    scheduler = get_llm_task_scheduler(config)
    try:
        model = scheduler._get_chat_model(
            tool_names=[],
            temperature=0.0,
            timeout_seconds=3,
            model_tier="large",
        )
    finally:
        reset_llm_task_schedulers()

    assert isinstance(model, LocalQwenChatModel)


def test_local_qwen_stream_buffers_tool_markup_into_tool_call_chunk() -> None:
    """工具绑定时不得把内部标签流给用户，完成后应形成结构化 tool call。"""

    class _FakeService:
        """返回拆分后的 Qwen 工具标签。"""

        def stream_chat(self, **kwargs: object):  # noqa: ANN201, ARG002
            yield '<tool_call>{"name":"understand_image",'
            yield '"arguments":{"attachment":"a.png"}}</tool_call>'

    model = LocalQwenChatModel(
        service=_FakeService(),  # type: ignore[arg-type]
        temperature=0.0,
        tools=[object()],
    )

    chunks = list(model.stream([HumanMessage(content="看图")]))

    assert len(chunks) == 1
    assert chunks[0].content == ""
    assert chunks[0].tool_calls[0]["name"] == "understand_image"


def test_local_qwen_does_not_send_unrelated_tool_schemas_for_plain_chat() -> None:
    """普通对话不得让 CPU 模型预填充整份工具注册表。"""

    class _FakeService:
        """记录本轮实际传给本地模型的工具。"""

        def __init__(self) -> None:
            self.tools: tuple[object, ...] = ()

        def stream_chat(self, **kwargs: object):  # noqa: ANN201
            self.tools = tuple(kwargs.get("tools", ()))
            yield "你好"

    service = _FakeService()
    model = LocalQwenChatModel(
        service=service,  # type: ignore[arg-type]
        temperature=0.0,
        tools=[
            SimpleNamespace(name="web_search", description="联网搜索公开网页内容"),
            SimpleNamespace(name="run_terminal_command", description="执行终端命令"),
        ],
    )

    chunks = list(model.stream([HumanMessage(content="你好")]))

    assert service.tools == ()
    assert "".join(str(chunk.content) for chunk in chunks) == "你好"


def test_local_qwen_sends_only_the_relevant_tool_schema() -> None:
    """需要工具时只绑定与当前请求最相关的一个工具。"""

    class _FakeService:
        """记录本轮实际传给本地模型的工具。"""

        def __init__(self) -> None:
            self.tools: tuple[object, ...] = ()

        def stream_chat(self, **kwargs: object):  # noqa: ANN201
            self.tools = tuple(kwargs.get("tools", ()))
            yield "已搜索"

    web_tool = SimpleNamespace(name="web_search", description="联网搜索公开网页内容")
    terminal_tool = SimpleNamespace(name="run_terminal_command", description="执行终端命令")
    service = _FakeService()
    model = LocalQwenChatModel(
        service=service,  # type: ignore[arg-type]
        temperature=0.0,
        tools=[terminal_tool, web_tool],
    )

    list(model.stream([HumanMessage(content="请搜索网页上的最新资料")]))

    assert service.tools == (web_tool,)


def test_local_qwen_download_start_is_idempotent(tmp_path, monkeypatch: object) -> None:
    """重复点击或启动恢复不得创建两个并发下载线程。"""

    from threading import Event

    import agent_service.services.local_qwen.service as local_module

    config = AgentConfig.load_config(
        {"storage": {"local_model_dir": str(tmp_path / "models")}},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    started = Event()
    release = Event()

    def fake_ensure_model(*args: object, **kwargs: object):  # noqa: ANN202, ARG001
        started.set()
        release.wait(timeout=2)
        return tmp_path / "models" / "Qwen__Qwen3.5-2B"

    monkeypatch.setattr(local_module, "ensure_model", fake_ensure_model)
    monkeypatch.setattr(local_module, "is_model_available", lambda path: True)

    first = start_local_qwen_download(config, load_after=False)
    assert started.wait(timeout=1)
    second = start_local_qwen_download(config, load_after=False)
    release.set()

    assert first is True
    assert second is False


def test_backend_startup_resumes_detected_local_qwen_partial(tmp_path, monkeypatch: object) -> None:
    """启动恢复入口应识别断点并委托唯一下载线程续传。"""

    import agent_service.services.local_qwen.service as local_module

    config = AgentConfig.load_config(
        {"storage": {"local_model_dir": str(tmp_path / "models")}},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    calls: list[bool] = []
    monkeypatch.setattr(local_module, "is_model_available", lambda path: False)
    monkeypatch.setattr(local_module, "has_partial_model_download", lambda path: True)
    monkeypatch.setattr(local_module, "restore_partial_download_progress", lambda model_type, path: {})
    monkeypatch.setattr(
        local_module,
        "start_local_qwen_download",
        lambda config, load_after: calls.append(load_after) or True,
    )

    resumed = local_module.resume_interrupted_local_qwen_download(config)

    assert resumed is True
    assert calls == [True]


def test_local_qwen_missing_weights_waits_for_confirmed_download(tmp_path, monkeypatch: object) -> None:
    """任意 AI 首次触发本地 Qwen 时只验证磁盘，缺失权重不得隐式下载。"""

    import agent_service.services.local_qwen.service as local_module

    config = SimpleNamespace(
        model=SimpleNamespace(local_model_name="Qwen/test-local"),
        storage=SimpleNamespace(local_model_dir=tmp_path / "models"),
    )
    monkeypatch.setattr(local_module, "ensure_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not download")))
    service = LocalQwenService(config=config)

    with pytest.raises(RuntimeError, match="确认下载"):
        service.ensure_loaded()

    assert get_model_status().local_qwen is ModelState.AWAITING_DOWNLOAD
