"""
用户设置数据库模型。

功能说明:
- UserSystemPromptEntry: 用户自定义系统提示词条目，每条独立存储，启动时全部加载拼接。
- UserSettingsRecord: 用户级 editor/console 共享设置档案。
- UserKnowledgeLibrary: 用户知识库配置,一个用户可拥有多个互相隔离的知识库。
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, Field, SQLModel, Text

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.models.session import utc_now


# Video files remain visible in the workspace player but are never knowledge-ingestion sources.
DEFAULT_VIDEO_IGNORE_PATTERNS = "\n".join(("*.mp4", "*.webm", "*.ogg", "*.ogv", "*.mov", "*.m4v"))


class UserSystemPromptEntry(SQLModel, table=True):
    """用户自定义系统提示词条目。"""

    __tablename__ = "user_system_prompts"

    prompt_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    content: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)


class UserSettingsRecord(SQLModel, table=True):
    """用户设置档案记录。"""

    __tablename__ = "user_settings"

    user_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    knowledge_dir: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    proxy_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    browser_proxy_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    browser_home_url: str = Field(default="https://www.google.com", max_length=DEFAULT_BUSINESS_LIMITS.path_max_length)
    web_search_enabled: bool = Field(default=False)
    web_search_max_results: int = Field(default=DEFAULT_BUSINESS_LIMITS.default_web_search_max_results)
    auto_ingest_on_upload: bool = Field(default=False)
    ocr_enabled: bool = Field(default=False)
    # 用户显式开启后，Agent 图片附件和 understand_image 工具才允许调用本地 Qwen。
    vision_understanding_enabled: bool = Field(default=False)
    # 用户显式启用后，启动后验证到的缺失模型才允许自动下载。
    model_auto_download_enabled: bool = Field(default=False)
    # 用户显式开启后，主 Agent才可调度 DSH，并在界面启动后后台安装 Runtime。
    dsh_coding_agent_enabled: bool = Field(default=False)
    long_term_memory_enabled: bool = Field(default=True)
    knowledge_ignore_patterns: str = Field(default=DEFAULT_VIDEO_IGNORE_PATTERNS, sa_column=Column(Text))
    disabled_tools: str = Field(default="", sa_column=Column(Text))
    terminal_sandbox_config: str = Field(default="", sa_column=Column(Text))
    ui_font_families: str = Field(default="", sa_column=Column(Text))
    text_font_families: str = Field(default="", sa_column=Column(Text))
    ui_font_size_percent: int = Field(default=DEFAULT_BUSINESS_LIMITS.default_font_size_percent)
    text_font_size_percent: int = Field(default=DEFAULT_BUSINESS_LIMITS.default_font_size_percent)
    # Legacy clients still read/write this field; the service mirrors the UI size into it.
    font_size_percent: int = Field(default=DEFAULT_BUSINESS_LIMITS.default_font_size_percent)
    theme_primary_color: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.short_status_max_length)
    theme_soft_color: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.short_status_max_length)
    tag_colors: str = Field(default="", sa_column=Column(Text))
    tag_colors_translucent: bool | None = Field(default=None, nullable=True)
    background_cover_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.path_max_length)
    show_backlinks: bool = Field(default=False)
    graph_node_limit: int = Field(default=DEFAULT_BUSINESS_LIMITS.graph_default_node_limit)
    floating_launch_enabled: bool = Field(default=False)
    editor_image_assets_dir: str = Field(default="./assets/", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    storage_path_overrides: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserKnowledgeLibrary(SQLModel, table=True):
    """用户知识库配置记录。"""

    __tablename__ = "user_knowledge_libraries"

    library_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.graph_identifier_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    name: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    knowledge_dir: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    library_storage_dir: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    is_active: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserLLMConfig(SQLModel, table=True):
    """用户自定义 LLM 配置，支持一大一小两个模型。

    每个用户一条记录，存储大模型和小模型的 API Key、Base URL、模型名称。
    """

    __tablename__ = "user_llm_config"

    user_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)

    # 大模型
    api_key: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    base_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    model_name: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    model_context_window_tokens: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)
    model_max_output_tokens: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)

    # 小模型
    small_api_key: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    small_base_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    small_model_name: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    small_model_context_window_tokens: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)
    small_model_max_output_tokens: int = Field(default=0, ge=DEFAULT_BUSINESS_LIMITS.nonnegative_min_value)

    updated_at: datetime = Field(default_factory=utc_now)


class UserLLMConfigPreset(SQLModel, table=True):
    """用户保存的可复用 LLM 单模型配置。

    每条记录只描述一个模型端点,可在设置页导入为大模型或小模型。
    """

    __tablename__ = "user_llm_config_presets"

    config_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    label: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    api_key: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    base_url: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.secret_max_length)
    model_name: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.title_max_length)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
