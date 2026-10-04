"""DSH eligibility follows the effective main model and persists automatic disabling."""

from sqlmodel import Session

from agent_service.models.user_settings import UserSettingsRecord
from tests.test_settings_llm_config import make_settings_service


def test_dsh_rejects_unconfigured_and_non_deepseek_main_models() -> None:
    """Incomplete credentials and a DeepSeek small model cannot enable DSH."""
    service = make_settings_service()
    for fields in (
        {},
        {"model_name": "deepseek-chat"},
        {"model_name": "deepseek-chat", "api_key": "key"},
        {"model_name": "gpt-test", "api_key": "key", "base_url": "https://example.test/v1", "small_model_name": "deepseek-chat"},
    ):
        service.save_llm_config(user_id="u1", **{"api_key": "", "base_url": "", "model_name": "", **fields})
        result = service.save_knowledge_ingestion_config(user_id="u1", dsh_coding_agent_enabled=True)
        assert result["dsh_coding_agent_enabled"] is False
        assert service.is_dsh_coding_agent_enabled_for_user(user_id="u1") is False


def test_llm_changes_disable_dsh_and_do_not_reenable_it() -> None:
    """Changing backbone or removing a required credential disables only this user."""
    service = make_settings_service()
    for user in ("u1", "u2"):
        service.save_llm_config(user_id=user, model_name="deepseek-chat", api_key="key", base_url="https://example.test/v1")
        assert service.save_knowledge_ingestion_config(user_id=user, dsh_coding_agent_enabled=True)["dsh_coding_agent_enabled"] is True
    for change in ({"model_name": "gpt-test"}, {"api_key": ""}, {"base_url": ""}, {"model_name": ""}):
        service.save_llm_config(user_id="u1", **change)
        with Session(service.engine) as db:
            assert db.get(UserSettingsRecord, "u1").dsh_coding_agent_enabled is False
            assert db.get(UserSettingsRecord, "u2").dsh_coding_agent_enabled is True
        service.save_llm_config(user_id="u1", model_name="deepseek-chat", api_key="key", base_url="https://example.test/v1")
        assert service.get_knowledge_ingestion_config(user_id="u1")["dsh_coding_agent_enabled"] is False
        service.save_knowledge_ingestion_config(user_id="u1", dsh_coding_agent_enabled=True)


def test_service_defaults_and_namespaced_deepseek_models_allow_dsh() -> None:
    """Service defaults and namespaced model identifiers use the same eligibility rule."""
    service = make_settings_service()
    service.config.model.model_name = "deepseek-chat"
    service.config.model.api_key = "key"
    service.config.model.base_url = "https://example.test/v1"
    assert service.save_knowledge_ingestion_config(user_id="defaults", dsh_coding_agent_enabled=True)["dsh_coding_agent_enabled"] is True
    service.save_llm_config(user_id="namespaced", model_name="DeepSeek/DeepSeek-V3", api_key="key", base_url="https://example.test/v1")
    assert service.save_knowledge_ingestion_config(user_id="namespaced", dsh_coding_agent_enabled=True)["dsh_coding_agent_enabled"] is True


def test_legacy_enabled_dsh_is_persistently_disabled_on_profile_load() -> None:
    """Opening settings repairs an old enabled flag against the current backbone."""
    service = make_settings_service()
    with Session(service.engine) as db:
        db.add(UserSettingsRecord(user_id="legacy", knowledge_dir=str(service.config.storage.knowledge_dir), dsh_coding_agent_enabled=True))
        db.commit()
    assert service.ensure_user_profile(user_id="legacy")["dsh_coding_agent_enabled"] is False
    with Session(service.engine) as db:
        assert db.get(UserSettingsRecord, "legacy").dsh_coding_agent_enabled is False


def test_executor_rejects_non_deepseek_and_incomplete_main_models() -> None:
    """Runtime launch cannot bypass the same main-model eligibility check."""
    from types import SimpleNamespace
    import pytest
    from agent_service.services.dsh_adapter.executor import DshChildAgentExecutor

    executor = object.__new__(DshChildAgentExecutor)
    for change in ({"effective_model_name": "gpt-test"}, {"effective_api_key": ""}, {"effective_base_url": ""}):
        fields = {"effective_model_source": "remote", "effective_model_name": "deepseek-chat", "effective_api_key": "key", "effective_base_url": "https://example.test/v1", **change}
        executor.settings_service = SimpleNamespace(get_llm_config=lambda **_: fields)
        with pytest.raises(ValueError, match="DeepSeek"):
            executor._resolve_model("u1")
