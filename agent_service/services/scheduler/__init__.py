"""
LLM 任务调度包。

功能说明:
本包统一提供 AgentService 内部所有 LLM 调用的调度入口,包括多级队列、熔断、
重试和全局调度器单例。

使用说明:
业务模块应通过 `get_llm_task_scheduler(config)` 获取调度器实例,再调用
`run(...)` 或 `submit(...)` 提交具体 LLM 任务。
"""

from agent_service.services.scheduler.scheduler import (
    BACKGROUND_FACT_RESOLUTION_TASK,
    BACKGROUND_SUMMARY_TASK,
    FOREGROUND_AGENT_TASK,
    LARGE_MODEL_TIER,
    LLMConfigurationError,
    LLMTaskHandle,
    LLMTaskOverloadedError,
    LLMTaskScheduler,
    SMALL_MODEL_TIER,
    VISION_MODEL_TIER,
    VISION_UNDERSTANDING_TASK,
    get_llm_task_scheduler,
    reset_llm_task_schedulers,
)

__all__ = [
    "BACKGROUND_FACT_RESOLUTION_TASK",
    "BACKGROUND_SUMMARY_TASK",
    "FOREGROUND_AGENT_TASK",
    "LARGE_MODEL_TIER",
    "LLMConfigurationError",
    "LLMTaskHandle",
    "LLMTaskOverloadedError",
    "LLMTaskScheduler",
    "SMALL_MODEL_TIER",
    "VISION_MODEL_TIER",
    "VISION_UNDERSTANDING_TASK",
    "get_llm_task_scheduler",
    "reset_llm_task_schedulers",
]
