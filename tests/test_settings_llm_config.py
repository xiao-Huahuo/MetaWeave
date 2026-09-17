"""
用户 LLM 配置测试。

覆盖大/小/视觉模型配置继承和已保存模型配置的持久化行为。
"""

from __future__ import annotations

from typing import Any

from tests.db_test_utils import create_test_engine as create_engine

from agent_service.core.agent_config import AgentConfig
from agent_service.services.settings.service import SettingsService


class _MemoryServiceStub:
    def __init__(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")


def make_settings_service() -> SettingsService:
    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    return SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]


def test_vlm_config_requires_key_and_merges_user_limits() -> None:
    """VLM 总开关必须有 Key，用户限制覆盖服务默认且 OCR 可独立开启。"""

    service = make_settings_service()
    try:
        service.save_vlm_config(user_id="u-vlm", enabled=True)
    except ValueError as exc:
        assert "API Key" in str(exc)
    else:
        raise AssertionError("enabled VLM without a key must fail")

    saved = service.save_vlm_config(
        user_id="u-vlm",
        api_key="token-secret",
        enabled=True,
        model="vlm",
        max_concurrency=3,
        max_file_bytes=209715200,
        max_pages=600,
        submit_rate_per_minute=300,
        result_rate_per_minute=1000,
        ocr_enabled=True,
    )
    assert saved["enabled"] is True
    assert saved["configured"] is True
    assert saved["max_concurrency"] == 3
    assert saved["max_pages"] == 600
    assert saved["ocr_enabled"] is True


def test_vlm_config_presets_persist_load_fields_and_delete() -> None:
    """VLM 预设必须保存凭据、模型和全部限制，并保持用户隔离。"""

    service = make_settings_service()
    saved = service.save_vlm_config_preset(
        user_id="u-vlm",
        label="MinerU 精准",
        api_key="preset-secret",
        model="vlm",
        max_concurrency=2,
        max_file_bytes=209715200,
        max_pages=600,
        submit_rate_per_minute=300,
        result_rate_per_minute=1000,
    )

    assert saved["label"] == "MinerU 精准"
    assert saved["api_key"] == "preset-secret"
    assert saved["max_pages"] == 600
    assert service.list_vlm_config_presets(user_id="other") == []
    assert service.list_vlm_config_presets(user_id="u-vlm") == [saved]
    assert service.delete_vlm_config_preset(config_id=saved["config_id"], user_id="other") is False
    assert service.delete_vlm_config_preset(config_id=saved["config_id"], user_id="u-vlm") is True


def test_llm_config_small_model_inherits_large_model_fields() -> None:
    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u1",
        api_key="large-key",
        base_url="https://large.example.com/v1",
        model_name="large-model",
        small_api_key="",
        small_base_url="",
        small_model_name="",
    )

    assert config["api_key"] == "large-key"
    assert config["base_url"] == "https://large.example.com/v1"
    assert config["model_name"] == "large-model"
    assert config["small_api_key"] == ""
    assert config["small_base_url"] == ""
    assert config["small_model_name"] == ""
    assert config["effective_small_api_key"] == "large-key"
    assert config["effective_small_base_url"] == "https://large.example.com/v1"
    assert config["effective_small_model_name"] == "large-model"


def test_llm_config_without_remote_models_reports_unconfigured() -> None:
    """没有有效远程大模型时，三类模型都必须明确报告未配置。"""

    service = make_settings_service()

    config = service.get_llm_config(user_id="u-local")

    assert config["model_name"] == ""
    assert config["small_model_name"] == ""
    assert config["effective_model_name"] == ""
    assert config["effective_small_model_name"] == ""
    assert config["effective_vision_model_name"] == ""
    assert config["effective_model_source"] == "unconfigured"
    assert config["effective_small_model_source"] == "unconfigured"
    assert config["effective_vision_model_source"] == "unconfigured"


def test_llm_config_without_large_model_ignores_orphan_small_model() -> None:
    """只配置小模型不构成有效远程配置，大小模型都保持未配置。"""

    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u-orphan-small",
        small_api_key="small-key",
        small_base_url="https://small.example.com/v1",
        small_model_name="small-model",
    )

    assert config["effective_model_name"] == ""
    assert config["effective_small_model_name"] == ""
    assert config["effective_small_api_key"] == ""
    assert config["effective_model_source"] == "unconfigured"
    assert config["effective_small_model_source"] == "unconfigured"


def test_llm_config_with_model_name_but_without_key_is_unconfigured() -> None:
    """未填写 API Key 的远程模型配置不得伪装成可用模型。"""

    service = make_settings_service()

    config = service.save_llm_config(user_id="u-incomplete", model_name="remote-without-key")

    assert config["effective_model_name"] == ""
    assert config["effective_small_model_name"] == ""
    assert config["effective_model_source"] == "unconfigured"


def test_llm_config_empty_vision_fields_inherit_large_model() -> None:
    """视觉模型三项全空时必须整组继承有效大模型。"""

    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u-vision-inherit",
        api_key="large-key",
        base_url="https://large.example.com/v1",
        model_name="large-model",
        vision_api_key="",
        vision_base_url="",
        vision_model_name="",
    )

    assert config["vision_api_key"] == ""
    assert config["vision_base_url"] == ""
    assert config["vision_model_name"] == ""
    assert config["effective_vision_api_key"] == "large-key"
    assert config["effective_vision_base_url"] == "https://large.example.com/v1"
    assert config["effective_vision_model_name"] == "large-model"
    assert config["effective_vision_model_source"] == "large"


def test_llm_config_vision_model_only_reuses_large_endpoint_credentials() -> None:
    """只覆盖视觉模型名时，凭据和端点可以安全继承同一个大模型端点。"""

    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u-vision-model",
        api_key="large-key",
        base_url="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        vision_model_name="deepseek-flash",
    )

    assert config["effective_vision_api_key"] == "large-key"
    assert config["effective_vision_base_url"] == "https://api.deepseek.com/v1"
    assert config["effective_vision_model_name"] == "deepseek-flash"
    assert config["effective_vision_model_source"] == "explicit"


def test_llm_config_changed_vision_endpoint_requires_explicit_key() -> None:
    """视觉 Base URL 改到其他端点时不得泄露大模型 API Key。"""

    service = make_settings_service()

    try:
        service.save_llm_config(
            user_id="u-vision-isolated",
            api_key="large-key",
            base_url="https://large.example.com/v1",
            model_name="large-model",
            vision_base_url="https://vision.example.com/v1",
            vision_model_name="vision-model",
        )
    except ValueError as exc:
        assert "vision_api_key" in str(exc)
    else:
        raise AssertionError("a different vision endpoint must require its own key")

    config = service.save_llm_config(
        user_id="u-vision-isolated",
        api_key="large-key",
        base_url="https://large.example.com/v1",
        model_name="large-model",
        vision_api_key="vision-key",
        vision_base_url="https://vision.example.com/v1",
        vision_model_name="vision-model",
    )

    assert config["effective_vision_api_key"] == "vision-key"
    assert config["effective_vision_base_url"] == "https://vision.example.com/v1"
    assert config["effective_vision_model_source"] == "explicit"


def test_explicit_vision_model_works_without_a_large_model() -> None:
    """完整独立视觉配置不依赖大模型是否已配置。"""

    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u-vision-only",
        vision_api_key="vision-key",
        vision_base_url="https://vision.example.com/v1",
        vision_model_name="vision-model",
    )

    assert config["effective_model_source"] == "unconfigured"
    assert config["effective_vision_api_key"] == "vision-key"
    assert config["effective_vision_base_url"] == "https://vision.example.com/v1"
    assert config["effective_vision_model_name"] == "vision-model"
    assert config["effective_vision_model_source"] == "explicit"


def test_agent_config_exposes_remote_vision_runtime_limits(monkeypatch: Any) -> None:
    """远程视觉服务限制必须集中在 AgentConfig 并支持环境变量覆盖。"""

    config = AgentConfig.load_config(
        {},
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    assert config.model.vision_timeout_seconds == 60
    assert config.model.vision_max_image_bytes == 32 * 1024 * 1024
    assert config.model.vision_max_dimension == 8192
    assert config.model.vision_max_output_tokens == 1024
    assert config.model.vision_api_key == ""
    assert config.model.vision_base_url == ""
    assert config.model.vision_model_name == ""

    monkeypatch.setenv("AGENT_VISION_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AGENT_VISION_MAX_IMAGE_BYTES", "1048576")
    monkeypatch.setenv("AGENT_VISION_MAX_DIMENSION", "4096")
    monkeypatch.setenv("AGENT_VISION_MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("AGENT_VISION_API_KEY", "service-vision-key")
    monkeypatch.setenv("AGENT_VISION_BASE_URL", "https://service-vision.example/v1")
    monkeypatch.setenv("AGENT_VISION_MODEL_NAME", "service-vision-model")
    overridden = AgentConfig.load_config(
        {},
        load_env=True,
        load_dotenv=False,
        ensure_directories=False,
        ensure_models=False,
    )
    assert overridden.model.vision_timeout_seconds == 45
    assert overridden.model.vision_max_image_bytes == 1_048_576
    assert overridden.model.vision_max_dimension == 4096
    assert overridden.model.vision_max_output_tokens == 512
    assert overridden.model.vision_api_key == "service-vision-key"
    assert overridden.model.vision_base_url == "https://service-vision.example/v1"
    assert overridden.model.vision_model_name == "service-vision-model"


def test_llm_config_uses_grouped_service_vision_defaults() -> None:
    """用户未覆盖视觉三项时，SettingsService 必须使用服务级视觉配置。"""

    config = AgentConfig.load_config(
        {
            "model": {
                "api_key": "large-key",
                "base_url": "https://large.example/v1",
                "model_name": "large-model",
                "vision_api_key": "vision-key",
                "vision_base_url": "https://vision.example/v1",
                "vision_model_name": "vision-model",
            }
        },
        load_env=False,
        ensure_directories=False,
        ensure_models=False,
    )
    service = SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]

    effective = service.get_llm_config(user_id="u-service-vision")

    assert effective["effective_vision_api_key"] == "vision-key"
    assert effective["effective_vision_base_url"] == "https://vision.example/v1"
    assert effective["effective_vision_model_name"] == "vision-model"
    assert effective["effective_vision_model_source"] == "explicit"


def test_llm_config_empty_small_fields_clear_stale_values() -> None:
    service = make_settings_service()

    service.save_llm_config(
        user_id="u1",
        api_key="large-key",
        base_url="https://large.example.com/v1",
        model_name="large-model",
        small_api_key="stale-small-key",
        small_base_url="https://stale.example.com/v1",
        small_model_name="stale-small-model",
    )

    config = service.save_llm_config(
        user_id="u1",
        small_api_key="",
        small_base_url="",
        small_model_name="",
    )

    assert config["small_api_key"] == ""
    assert config["small_base_url"] == ""
    assert config["small_model_name"] == ""
    assert config["effective_small_api_key"] == "large-key"
    assert config["effective_small_base_url"] == "https://large.example.com/v1"
    assert config["effective_small_model_name"] == "large-model"


def test_llm_config_persists_explicit_model_capacity_overrides() -> None:
    """主/小模型容量覆盖必须独立持久化，0 保留为继承语义。"""

    service = make_settings_service()

    saved = service.save_llm_config(
        user_id="u-capacity",
        model_context_window_tokens=1_000_000,
        model_max_output_tokens=65_536,
        small_model_context_window_tokens=131_072,
        small_model_max_output_tokens=8_192,
    )
    loaded = service.get_llm_config(user_id="u-capacity")

    assert saved["model_context_window_tokens"] == 1_000_000
    assert loaded["model_max_output_tokens"] == 65_536
    assert loaded["small_model_context_window_tokens"] == 131_072
    assert loaded["small_model_max_output_tokens"] == 8_192


def test_llm_context_window_defaults_to_service_million_for_new_and_existing_zero_rows() -> None:
    """无用户覆盖或旧记录为 0 时，设置 API 都应展示并使用 100 万默认窗口。"""

    service = make_settings_service()

    default_config = service.get_llm_config(user_id="u-default-capacity")
    service.save_llm_config(user_id="u-existing-zero", model_name="deepseek-v4-flash")
    existing_config = service.get_llm_config(user_id="u-existing-zero")

    assert default_config["model_context_window_tokens"] == 1_000_000
    assert default_config["small_model_context_window_tokens"] == 1_000_000
    assert existing_config["model_context_window_tokens"] == 1_000_000
    assert existing_config["small_model_context_window_tokens"] == 1_000_000


def test_llm_config_presets_can_be_saved_listed_and_deleted() -> None:
    service = make_settings_service()

    preset = service.save_llm_config_preset(
        user_id="u1",
        label="DeepSeek",
        api_key="key",
        base_url="https://api.example.com/v1",
        model_name="model-a",
    )

    presets = service.list_llm_config_presets(user_id="u1")

    assert len(presets) == 1
    assert presets[0]["config_id"] == preset["config_id"]
    assert presets[0]["label"] == "DeepSeek"
    assert presets[0]["model_name"] == "model-a"
    assert service.delete_llm_config_preset(config_id=preset["config_id"]) is True
    assert service.list_llm_config_presets(user_id="u1") == []


def test_memory_config_defaults_on_and_persists_user_override() -> None:
    service = make_settings_service()

    assert service.get_memory_config(user_id="u1")["long_term_memory_enabled"] is True
    saved = service.save_memory_config(user_id="u1", long_term_memory_enabled=False)

    assert saved["long_term_memory_enabled"] is False
    assert service.get_memory_config(user_id="u1")["long_term_memory_enabled"] is False


def test_browser_config_persists_separate_proxy_and_home_page() -> None:
    service = make_settings_service()

    initial = service.get_web_search_config(user_id="u1")
    saved = service.save_web_search_config(
        user_id="u1",
        proxy_url="http://127.0.0.1:7890",
        browser_proxy_url="socks5://127.0.0.1:1080",
        browser_home_url="https://example.com/start",
    )

    assert initial["browser_proxy_url"] == ""
    assert initial["browser_home_url"] == "https://www.google.com"
    assert saved["browser_proxy_url"] == "socks5://127.0.0.1:1080"
    assert saved["browser_home_url"] == "https://example.com/start"
    assert service.get_web_search_config(user_id="u1")["proxy_url"] == "http://127.0.0.1:7890"


def test_browser_proxy_override_can_be_cleared_to_restore_inheritance() -> None:
    service = make_settings_service()
    service.save_web_search_config(
        user_id="u1",
        browser_proxy_url="http://127.0.0.1:7891",
    )

    saved = service.save_web_search_config(user_id="u1", browser_proxy_url="")

    assert saved["browser_proxy_url"] == ""


def test_memory_tools_are_disabled_in_available_tool_catalog_when_memory_is_off() -> None:
    service = make_settings_service()
    service.save_memory_config(user_id="u1", long_term_memory_enabled=False)

    groups = service.list_available_tools(user_id="u1")["groups"]
    memory_group = next(group for group in groups if group["category"] == "MEMORY")

    assert memory_group["tools"]
    assert all(tool["enabled"] is False for tool in memory_group["tools"])


def test_floating_launch_setting_persists_in_user_profile() -> None:
    service = make_settings_service()

    saved = service.save_floating_config(user_id="u1", floating_launch_enabled=True)
    profile = service.ensure_user_profile(user_id="u1")

    assert saved["floating_launch_enabled"] is True
    assert profile["floating_launch_enabled"] is True


def test_user_profile_reports_the_effective_supported_knowledge_suffixes() -> None:
    service = make_settings_service()
    service.config.constants.knowledge_supported_suffixes = [".md", ".custom"]

    profile = service.ensure_user_profile(user_id="u1")

    assert profile["knowledge_supported_suffixes"] == [".md", ".custom"]


def test_video_types_are_blocked_by_default_without_becoming_ingestion_types() -> None:
    """默认屏蔽常见视频扩展,同时不得把视频伪装成可灌库知识格式。"""

    service = make_settings_service()

    ingestion = service.get_knowledge_ingestion_config(user_id="u1")
    profile = service.ensure_user_profile(user_id="u1")

    assert "*.mp4" in ingestion["knowledge_ignore_patterns"].splitlines()
    assert "*.webm" in ingestion["knowledge_ignore_patterns"].splitlines()
    assert ".mp4" not in profile["knowledge_supported_suffixes"]
