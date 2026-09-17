"""OpenAI-compatible 远程图片理解服务。

使用说明:
应用生命周期创建一个 `VisionModelService` 并注入附件服务和工具运行时。服务按
`user_id` 实时读取 SettingsService 已解析的视觉模型配置，将原图、OCR 补充文本和
用户问题组成多模态消息，再通过统一 LLM 调度器调用远程模型。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from PIL import Image, UnidentifiedImageError

from agent_service.core.agent_config import AgentConfig
from agent_service.services.scheduler import (
    VISION_MODEL_TIER,
    VISION_UNDERSTANDING_TASK,
    LLMTaskScheduler,
    get_llm_task_scheduler,
)
from agent_service.services.settings.service import SettingsService

logger = logging.getLogger(__name__)

_SUPPORTED_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class VisionConfigurationError(RuntimeError):
    """视觉模型没有形成可调用配置时抛出。"""


class VisionInputError(ValueError):
    """输入图片不存在、损坏、超限或格式不受支持时抛出。"""


class VisionRequestError(RuntimeError):
    """远程视觉服务拒绝或未能完成请求时抛出。"""


@dataclass(frozen=True, slots=True)
class VisionUnderstandingResult:
    """一次远程识图的文本结果与真实模型标识。"""

    text: str
    model_name: str


class VisionModelService:
    """验证本地图片并通过用户配置的远程视觉模型生成语义描述。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        settings_service: SettingsService,
        task_scheduler: LLMTaskScheduler | None = None,
    ) -> None:
        """保存服务依赖；调度器由应用生命周期拥有并复用。"""

        self.config = config
        self.settings_service = settings_service
        self.task_scheduler = task_scheduler or get_llm_task_scheduler(
            config,
            settings_service=settings_service,
        )

    def understand_image(
        self,
        *,
        user_id: str,
        image_path: Path,
        ocr_text: str,
        prompt: str = "",
    ) -> VisionUnderstandingResult:
        """把原图、OCR 补充和问题发送给当前用户的有效视觉模型。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise VisionConfigurationError("视觉模型调用缺少用户标识。")
        llm_config = self.settings_service.get_llm_config(user_id=normalized_user_id)
        model_name = str(llm_config.get("effective_vision_model_name") or "").strip()
        api_key = str(llm_config.get("effective_vision_api_key") or "").strip()
        base_url = str(llm_config.get("effective_vision_base_url") or "").strip()
        if not model_name or not api_key:
            raise VisionConfigurationError("视觉模型未配置，请先在 LLM 设置中配置视觉模型或有效大模型。")

        image_bytes, media_type = self._read_image(image_path)
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        question = prompt.strip() or (
            "请描述图片中的对象、布局、空间关系、图表趋势和 OCR 无法表达的视觉含义。"
            "不要重复抄写 OCR 文本，不确定的内容请明确说明。"
        )
        normalized_ocr = ocr_text.strip()
        text = (
            "依据原图回答，并把 OCR 仅作为可纠错的辅助证据。"
            f"\n\n{question}"
        )
        if normalized_ocr:
            text += f"\n\n以下是先行 OCR 文本，仅作为辅助证据：\n{normalized_ocr}"
        messages = [
            HumanMessage(content=[
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{encoded_image}",
                        "detail": "original",
                    },
                },
            ]),
        ]
        try:
            response = self.task_scheduler.invoke_chat(
                task_type=VISION_UNDERSTANDING_TASK,
                messages=messages,
                model_tier=VISION_MODEL_TIER,
                api_key=api_key,
                base_url=base_url or None,
                model_name=model_name,
                temperature=0.0,
                timeout_seconds=float(self.config.model.vision_timeout_seconds),
                max_output_tokens=int(self.config.model.vision_max_output_tokens),
            )
        except Exception as exc:  # noqa: BLE001 - SDK types vary by compatible provider.
            status_code = self._status_code(exc)
            logger.warning(
                "远程视觉模型调用失败 | user=%s model=%s status=%s error_type=%s",
                normalized_user_id,
                model_name,
                status_code or "unknown",
                type(exc).__name__,
            )
            raise self._request_error(status_code) from exc

        content = self._response_text(response)
        if not content:
            raise VisionRequestError("视觉模型返回了空结果，请稍后重试或检查模型能力。")
        return VisionUnderstandingResult(text=content, model_name=model_name)

    def _read_image(self, image_path: Path) -> tuple[bytes, str]:
        """读取并验证图片真实格式、字节大小和像素尺寸。"""

        path = image_path.expanduser().resolve()
        if not path.is_file():
            raise VisionInputError("图片文件不存在或不可读取。")
        image_bytes = path.read_bytes()
        if len(image_bytes) > int(self.config.model.vision_max_image_bytes):
            raise VisionInputError("图片大小超过视觉模型允许的上限。")
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise VisionInputError("图片无法读取或文件内容已损坏。") from exc
        media_type = _SUPPORTED_IMAGE_FORMATS.get(image_format)
        if media_type is None:
            raise VisionInputError("图片格式不受视觉模型支持，仅支持 JPEG、PNG、GIF 和 WebP。")
        max_dimension = int(self.config.model.vision_max_dimension)
        if width > max_dimension or height > max_dimension:
            raise VisionInputError("图片尺寸超过视觉模型允许的上限。")
        return image_bytes, media_type

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        """从 OpenAI-compatible 异常或其 response 中读取 HTTP 状态码。"""

        direct = getattr(exc, "status_code", None)
        if isinstance(direct, int):
            return direct
        response = getattr(exc, "response", None)
        nested = getattr(response, "status_code", None)
        return nested if isinstance(nested, int) else None

    @staticmethod
    def _request_error(status_code: int | None) -> VisionRequestError:
        """把上游状态转换成不会泄露响应体或凭据的稳定领域错误。"""

        if status_code in {401, 403}:
            return VisionRequestError("视觉模型凭据无效或没有访问权限。")
        if status_code == 429:
            return VisionRequestError("视觉模型服务当前限流，请稍后重试。")
        if status_code == 400:
            return VisionRequestError("视觉模型拒绝了图片请求，请检查模型是否支持图片输入。")
        if status_code is not None and status_code >= 500:
            return VisionRequestError("视觉模型服务暂时不可用，请稍后重试。")
        return VisionRequestError("视觉模型调用失败，请检查网络、Base URL 和模型配置。")

    @staticmethod
    def _response_text(response: Any) -> str:
        """兼容纯字符串和 OpenAI 内容块形式的模型回复。"""

        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""
        parts = [
            str(block.get("text") or "").strip()
            for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
        ]
        return "\n".join(part for part in parts if part).strip()
