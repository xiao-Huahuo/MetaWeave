"""模型自动下载用户设置的持久化测试。

使用说明:
验证自动下载默认关闭，且只把用户显式选择写入正式 user_settings 表。
"""

from __future__ import annotations

from tests.db_test_utils import create_test_engine as create_engine
from sqlalchemy import text

from agent_service.core.agent_config import AgentConfig
from agent_service.services.settings.service import SettingsService


class _MemoryServiceStub:
    """提供 SettingsService 所需的隔离数据库。"""

    def __init__(self) -> None:
        """创建当前测试独占的内存数据库。"""

        self.engine = create_engine("sqlite:///:memory:")


def _make_settings_service() -> SettingsService:
    """创建不下载任何真实模型的设置服务。"""

    config = AgentConfig.load_config({}, load_env=False, ensure_directories=False, ensure_models=False)
    return SettingsService(config=config, memory_service=_MemoryServiceStub())  # type: ignore[arg-type]


def test_model_auto_download_defaults_to_false_and_persists() -> None:
    """新用户必须默认关闭自动下载，开启后由后端档案稳定返回。"""

    service = _make_settings_service()

    assert service.ensure_user_profile(user_id="u1")["model_auto_download_enabled"] is False

    saved = service.save_model_preferences(user_id="u1", auto_download_enabled=True)

    assert saved == {"user_id": "u1", "auto_download_enabled": True}
    assert service.get_model_preferences(user_id="u1")["auto_download_enabled"] is True
    assert service.ensure_user_profile(user_id="u1")["model_auto_download_enabled"] is True


def test_vision_understanding_defaults_to_false_and_persists() -> None:
    """识图必须默认关闭，并通过正式用户设置保存显式开启值。"""

    service = _make_settings_service()
    assert service.ensure_user_profile(user_id="u1")["vision_understanding_enabled"] is False

    saved = service.save_knowledge_ingestion_config(user_id="u1", vision_understanding_enabled=True)

    assert saved["vision_understanding_enabled"] is True
    assert service.is_vision_understanding_enabled_for_user(user_id="u1") is True


def test_dsh_coding_agent_defaults_to_false_and_persists() -> None:
    """DSH必须默认关闭，只有用户显式开启后调度门禁才放行。"""

    service = _make_settings_service()
    assert service.ensure_user_profile(user_id="u1")["dsh_coding_agent_enabled"] is False
    assert service.is_dsh_coding_agent_enabled_for_user(user_id="u1") is False

    service.save_llm_config(user_id="u1", model_name="deepseek-chat", api_key="key", base_url="https://example.test/v1")
    saved = service.save_knowledge_ingestion_config(user_id="u1", dsh_coding_agent_enabled=True)

    assert saved["dsh_coding_agent_enabled"] is True
    assert service.is_dsh_coding_agent_enabled_for_user(user_id="u1") is True


def test_ocr_flag_lookup_ignores_unrelated_newer_columns() -> None:
    """模型管理读取 OCR 时不得因热重载数据库暂缺其他设置列而整体 500。"""

    service = _make_settings_service()
    with service.engine.begin() as connection:
        connection.execute(text("DROP TABLE user_settings"))
        connection.execute(text(
            "CREATE TABLE user_settings (user_id VARCHAR(128) PRIMARY KEY, ocr_enabled BOOLEAN NOT NULL)"
        ))
        connection.execute(text("INSERT INTO user_settings (user_id, ocr_enabled) VALUES ('u1', 1)"))

    assert service.is_ocr_enabled_for_user(user_id="u1") is True
