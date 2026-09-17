"""远程视觉模型服务测试。

使用说明:
通过假的 SettingsService 与调度器验证图片请求结构、配置解析和错误边界；测试不会
访问真实模型 API，也不会把凭据或图片内容写入日志。
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from agent_service.services.vision.service import (
    VisionConfigurationError,
    VisionInputError,
    VisionModelService,
    VisionRequestError,
)


class _SettingsStub:
    """返回测试指定的最终视觉配置。"""

    def __init__(self, payload: dict[str, str]) -> None:
        """保存一次测试使用的设置响应。"""

        self.payload = payload

    def get_llm_config(self, *, user_id: str) -> dict[str, str]:
        """返回设置服务已经合并完成的有效配置。"""

        assert user_id == "u1"
        return dict(self.payload)


class _SchedulerStub:
    """记录视觉模型请求并返回稳定文本。"""

    def __init__(self, response: object = None) -> None:
        """初始化调用记录和可选异常/响应。"""

        self.response = response if response is not None else AIMessage(content="图中有蓝色箭头。")
        self.calls: list[dict[str, object]] = []

    def invoke_chat(self, **kwargs: object) -> AIMessage:
        """记录完整调用参数；异常对象用于验证错误映射。"""

        self.calls.append(dict(kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        assert isinstance(self.response, AIMessage)
        return self.response


class _RemoteError(RuntimeError):
    """模拟 OpenAI-compatible SDK 携带状态码的异常。"""

    def __init__(self, status_code: int, detail: str) -> None:
        """保存 HTTP 状态并模拟可能包含敏感信息的上游消息。"""

        super().__init__(detail)
        self.status_code = status_code


def _config(*, max_bytes: int = 32 * 1024 * 1024, max_dimension: int = 8192) -> SimpleNamespace:
    """构造视觉服务需要的最小服务级配置。"""

    return SimpleNamespace(
        model=SimpleNamespace(
            vision_timeout_seconds=60,
            vision_max_image_bytes=max_bytes,
            vision_max_dimension=max_dimension,
            vision_max_output_tokens=1024,
        )
    )


def _write_image(path: Path, *, size: tuple[int, int] = (32, 24), image_format: str = "PNG") -> bytes:
    """创建具有稳定尺寸和格式的测试图片。"""

    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=image_format)
    payload = buffer.getvalue()
    path.write_bytes(payload)
    return payload


def _effective_config() -> dict[str, str]:
    """返回一套有效的 DeepSeek 视觉配置。"""

    return {
        "effective_vision_api_key": "vision-secret",
        "effective_vision_base_url": "https://api.deepseek.com",
        "effective_vision_model_name": "deepseek-flash",
        "effective_vision_model_source": "explicit",
    }


def test_vision_service_sends_original_image_ocr_and_user_prompt(tmp_path: Path) -> None:
    """视觉请求必须同时携带原图、OCR 补充文本和用户问题。"""

    image_path = tmp_path / "diagram.png"
    image_bytes = _write_image(image_path)
    scheduler = _SchedulerStub()
    service = VisionModelService(
        config=_config(),
        settings_service=_SettingsStub(_effective_config()),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )

    result = service.understand_image(
        user_id="u1",
        image_path=image_path,
        ocr_text="OCR: 输入文档",
        prompt="箭头指向哪里？",
    )

    assert result.text == "图中有蓝色箭头。"
    assert result.model_name == "deepseek-flash"
    call = scheduler.calls[0]
    assert call["model_name"] == "deepseek-flash"
    assert call["api_key"] == "vision-secret"
    assert call["base_url"] == "https://api.deepseek.com"
    messages = call["messages"]
    human = messages[-1]  # type: ignore[index]
    blocks = human.content
    text_block = next(block for block in blocks if block["type"] == "text")
    image_block = next(block for block in blocks if block["type"] == "image_url")
    assert "箭头指向哪里" in text_block["text"]
    assert "OCR: 输入文档" in text_block["text"]
    encoded = image_block["image_url"]["url"].removeprefix("data:image/png;base64,")
    assert base64.b64decode(encoded) == image_bytes


def test_vision_service_rejects_unconfigured_model_before_scheduling(tmp_path: Path) -> None:
    """无有效视觉模型时必须快速失败，不能构造空凭据请求。"""

    image_path = tmp_path / "image.png"
    _write_image(image_path)
    scheduler = _SchedulerStub()
    service = VisionModelService(
        config=_config(),
        settings_service=_SettingsStub({}),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )

    with pytest.raises(VisionConfigurationError, match="视觉模型"):
        service.understand_image(user_id="u1", image_path=image_path, ocr_text="")

    assert scheduler.calls == []


def test_vision_service_validates_real_image_size_and_dimensions(tmp_path: Path) -> None:
    """图片字节数和真实尺寸超过服务限制时均应在联网前拒绝。"""

    image_path = tmp_path / "large.png"
    image_bytes = _write_image(image_path, size=(20, 12))
    scheduler = _SchedulerStub()
    size_limited = VisionModelService(
        config=_config(max_bytes=len(image_bytes) - 1),
        settings_service=_SettingsStub(_effective_config()),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )
    dimension_limited = VisionModelService(
        config=_config(max_dimension=16),
        settings_service=_SettingsStub(_effective_config()),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )

    with pytest.raises(VisionInputError, match="大小"):
        size_limited.understand_image(user_id="u1", image_path=image_path, ocr_text="")
    with pytest.raises(VisionInputError, match="尺寸"):
        dimension_limited.understand_image(user_id="u1", image_path=image_path, ocr_text="")

    assert scheduler.calls == []


def test_vision_service_maps_auth_error_without_leaking_upstream_detail(tmp_path: Path) -> None:
    """上游错误即使包含 Key 或图片内容，也只能暴露稳定脱敏文案。"""

    image_path = tmp_path / "image.png"
    _write_image(image_path)
    scheduler = _SchedulerStub(_RemoteError(401, "bad vision-secret data:image/png;base64,private"))
    service = VisionModelService(
        config=_config(),
        settings_service=_SettingsStub(_effective_config()),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )

    with pytest.raises(VisionRequestError) as captured:
        service.understand_image(user_id="u1", image_path=image_path, ocr_text="OCR")

    message = str(captured.value)
    assert "凭据" in message
    assert "vision-secret" not in message
    assert "base64" not in message


def test_vision_service_rejects_corrupt_or_unsupported_files(tmp_path: Path) -> None:
    """扩展名伪装或不受支持的真实格式不能进入远程请求。"""

    corrupt = tmp_path / "fake.png"
    corrupt.write_bytes(b"not-an-image")
    bmp = tmp_path / "image.bmp"
    _write_image(bmp, image_format="BMP")
    scheduler = _SchedulerStub()
    service = VisionModelService(
        config=_config(),
        settings_service=_SettingsStub(_effective_config()),  # type: ignore[arg-type]
        task_scheduler=scheduler,  # type: ignore[arg-type]
    )

    with pytest.raises(VisionInputError, match="无法读取"):
        service.understand_image(user_id="u1", image_path=corrupt, ocr_text="")
    with pytest.raises(VisionInputError, match="格式"):
        service.understand_image(user_id="u1", image_path=bmp, ocr_text="")

    assert scheduler.calls == []
