"""
模型加载状态追踪模块。

用途:
- 全局单例追踪 Embedding / ReRank / PaddleOCR 的下载和加载状态。
- 模型 provider 在开始下载/加载/完成/失败时调用 set_model_state() 更新状态。
- 前端通过 GET /settings/models/status 轮询状态快照并显示独立悬浮进度，不阻断其他业务。

线程安全: 使用 threading.Lock 保护状态读写。
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass


class ModelState(enum.Enum):
    """模型加载状态枚举。"""

    NOT_DOWNLOADED = "not_downloaded"
    VERIFYING = "verifying"
    AWAITING_DOWNLOAD = "awaiting_download"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class ModelStatusSnapshot:
    """三类受管模型的当前状态快照。"""

    embedding: ModelState = ModelState.NOT_DOWNLOADED
    rerank: ModelState = ModelState.NOT_DOWNLOADED
    paddleocr: ModelState = ModelState.NOT_DOWNLOADED

    def to_dict(self) -> dict:
        return {
            "embedding": self.embedding.value,
            "rerank": self.rerank.value,
            "paddleocr": self.paddleocr.value,
        }


# 模块级单例与锁
_model_status = ModelStatusSnapshot()
_lock = threading.Lock()


def get_model_status() -> ModelStatusSnapshot:
    """返回当前模型状态快照（线程安全）。"""

    with _lock:
        return ModelStatusSnapshot(
            embedding=_model_status.embedding,
            rerank=_model_status.rerank,
            paddleocr=_model_status.paddleocr,
        )


def set_model_state(model: str, state: ModelState) -> None:
    """更新指定模型的状态（线程安全）。

    Args:
        model: "embedding" | "rerank" | "paddleocr"
        state: 新状态
    """

    with _lock:
        if model == "embedding":
            _model_status.embedding = state
        elif model == "rerank":
            _model_status.rerank = state
        elif model == "paddleocr":
            _model_status.paddleocr = state
        else:
            raise ValueError(f"未知模型类型: {model}")
