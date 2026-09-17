"""
LLM 调度器共享类型模块。

功能说明:
本文件集中定义调度器常量、异常、任务句柄和本地任务数据结构,供 scheduler.py、
runtime.py 与包级导出复用,避免主调度器文件继续膨胀。

使用说明:
业务层通常不直接导入本模块,而是通过 `agent_service.services.scheduler`
包级入口获取公开常量和调度器类。
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

LLMOperation = Callable[[], Any]
LARGE_MODEL_TIER = "large"
SMALL_MODEL_TIER = "small"
VISION_MODEL_TIER = "vision"
FOREGROUND_AGENT_TASK = "foreground_agent"
BACKGROUND_SUMMARY_TASK = "background_summary"
BACKGROUND_FACT_RESOLUTION_TASK = "background_fact_resolution"
VISION_UNDERSTANDING_TASK = "vision_understanding"
SUPPORTED_TASK_TYPES = {
    FOREGROUND_AGENT_TASK,
    BACKGROUND_SUMMARY_TASK,
    BACKGROUND_FACT_RESOLUTION_TASK,
    VISION_UNDERSTANDING_TASK,
}
SUPPORTED_MODEL_TIERS = {LARGE_MODEL_TIER, SMALL_MODEL_TIER, VISION_MODEL_TIER}


class LLMTaskSchedulerError(RuntimeError):
    """LLM 调度器基础异常。"""


class LLMTaskOverloadedError(LLMTaskSchedulerError):
    """调度队列或熔断器拒绝新任务时抛出的异常。"""


class LLMConfigurationError(LLMTaskSchedulerError):
    """远程模型名称、凭据或端点组合无效时抛出的配置异常。"""


@dataclass(slots=True)
class LLMTaskHandle:
    """
    调度任务句柄。

    task_id: 调度任务 ID。
    task_type: 任务类型。
    future: 对应的本地 Future。
    result_loader: 可选的外部结果加载函数,用于 Redis 分布式结果等待。
    """

    task_id: str
    task_type: str
    future: Future[Any]
    result_loader: Callable[[float | None], Any] | None = None

    def wait(self, timeout: float | None = None) -> Any:
        """等待任务完成并返回结果。"""

        if self.future.done():
            return self.future.result(timeout=timeout)
        if self.result_loader is not None:
            result = self.result_loader(timeout)
            if not self.future.done():
                self.future.set_result(result)
            return result
        return self.future.result(timeout=timeout)

    def join(self, timeout: float | None = None) -> Any:
        """兼容线程风格的等待接口。"""

        return self.wait(timeout=timeout)


@dataclass(slots=True)
class ScheduledLLMTask:
    """
    本地 generic 队列任务对象。

    sequence: 单调递增序号。
    task_id: 任务 ID。
    task_type: 任务类型。
    operation: 实际执行函数。
    timeout_seconds: 超时时间。
    max_retries: 最大重试次数。
    dedup_key: 可选去重键。
    future: 对应 Future。
    """

    sequence: int
    task_id: str
    task_type: str
    operation: LLMOperation
    timeout_seconds: float
    max_retries: int
    dedup_key: str | None
    future: Future[Any] = field(default_factory=Future)
