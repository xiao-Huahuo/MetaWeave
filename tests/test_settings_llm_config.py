"""
用户 LLM 配置测试。

覆盖大/小模型配置继承和已保存模型配置的持久化行为。
"""

from __future__ import annotations

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


def test_llm_config_without_remote_models_reports_local_qwen_fallback() -> None:
    """没有任何用户模型配置时，前端和运行时都应看到本地 Qwen 的有效配置。"""

    service = make_settings_service()

    config = service.get_llm_config(user_id="u-local")

    assert config["model_name"] == ""
    assert config["small_model_name"] == ""
    assert config["effective_model_name"] == service.config.model.local_model_name
    assert config["effective_small_model_name"] == service.config.model.local_model_name
    assert config["effective_model_source"] == "local"
    assert config["effective_small_model_source"] == "local"


def test_llm_config_without_large_model_ignores_orphan_small_model() -> None:
    """只配置小模型不构成有效远程配置，大小模型仍统一回退本地 Qwen。"""

    service = make_settings_service()

    config = service.save_llm_config(
        user_id="u-orphan-small",
        small_api_key="small-key",
        small_base_url="https://small.example.com/v1",
        small_model_name="small-model",
    )

    assert config["effective_model_name"] == service.config.model.local_model_name
    assert config["effective_small_model_name"] == service.config.model.local_model_name
    assert config["effective_small_api_key"] == ""


def test_llm_config_with_model_name_but_without_key_uses_local_qwen() -> None:
    """未填写 API Key 的远程模型配置不得阻断本地回退。"""

    service = make_settings_service()

    config = service.save_llm_config(user_id="u-incomplete", model_name="remote-without-key")

    assert config["effective_model_name"] == service.config.model.local_model_name
    assert config["effective_small_model_name"] == service.config.model.local_model_name
    assert config["effective_model_source"] == "local"


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
