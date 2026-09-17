"""Typed REST DTOs for user-owned LLM settings.

The stored fields remain optional overrides. Effective fields describe the endpoint selected
after service defaults and inheritance have been applied.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS


class LLMConfigSaveRequest(BaseModel):
    """Partially update one user's large, small, and vision-model overrides."""

    user_id: str = Field(
        min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length,
        max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length,
    )
    api_key: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    base_url: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    model_name: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    small_api_key: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    small_base_url: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    small_model_name: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    vision_api_key: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    vision_base_url: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    vision_model_name: str | None = Field(default=None, max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    model_context_window_tokens: int | None = Field(
        default=None,
        ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value,
    )
    model_max_output_tokens: int | None = Field(
        default=None,
        ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value,
    )
    small_model_context_window_tokens: int | None = Field(
        default=None,
        ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value,
    )
    small_model_max_output_tokens: int | None = Field(
        default=None,
        ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value,
    )


class LLMConfigResponse(BaseModel):
    """Return persisted/default overrides together with all effective model endpoints."""

    user_id: str
    api_key: str
    base_url: str
    model_name: str
    small_api_key: str
    small_base_url: str
    small_model_name: str
    vision_api_key: str
    vision_base_url: str
    vision_model_name: str
    effective_api_key: str
    effective_base_url: str
    effective_model_name: str
    effective_model_source: Literal["remote", "unconfigured"]
    effective_small_api_key: str
    effective_small_base_url: str
    effective_small_model_name: str
    effective_small_model_source: Literal["remote", "unconfigured"]
    effective_vision_api_key: str
    effective_vision_base_url: str
    effective_vision_model_name: str
    effective_vision_model_source: Literal["explicit", "large", "unconfigured"]
    model_context_window_tokens: int
    model_max_output_tokens: int
    small_model_context_window_tokens: int
    small_model_max_output_tokens: int
    summary_trigger_tokens: int
    context_window_tokens: int
    context_output_reserve_tokens: int
    context_compression_trigger_ratio: float
    context_compression_target_ratio: float
    updated_at: str
