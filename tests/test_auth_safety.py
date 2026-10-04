"""Account safety switches must affect input/output auditing without shared mutable policy."""
from pathlib import Path
from types import SimpleNamespace
from agent_service.services.safety.safety_service import SafetyService
from agent_service.services.safety.output_auditor import OutputAuditor
from agent_service.services.safety.sensitive_word_checker import SensitiveWordChecker
from agent_service.services.safety.intent_auditor import IntentAuditResult
from tests.test_auth_rest import fixture, register


def test_two_users_have_independent_input_and_output_policy(tmp_path: Path) -> None:
    """A disabled user cannot disable another user's checker or safety system."""
    client, auth, settings, engine = fixture(tmp_path)
    try:
        first = register(client, "first")
        second = register(client, "second")
        settings.save_safety_config(user_id=first["user_id"], sensitive_words_enabled=False, safety_enabled=True)
        service = SafetyService(config=auth.config)
        service.settings_service = settings
        checker = SensitiveWordChecker({"violence": {"name": "test", "exact": ["forbidden"], "patterns": [], "block": True, "risk_level": "high"}}, disabled=True, safety_disabled=True)
        service._sensitive_checker = checker
        service._output_auditor = OutputAuditor(config=auth.config, sensitive_checker=checker)
        service._intent_auditor = SimpleNamespace(audit=lambda *args, **kwargs: IntentAuditResult.default_pass())
        assert service.audit_input("forbidden", user_id=first["user_id"]).passed
        assert service.audit_input("forbidden", user_id=second["user_id"]).blocked
        assert not service.audit_output("forbidden", user_id=first["user_id"]).blocked
        assert service.audit_output("forbidden", user_id=second["user_id"]).blocked
        settings.save_safety_config(user_id=second["user_id"], safety_enabled=False)
        assert service.audit_input("forbidden", user_id=second["user_id"]).passed
        assert not service.audit_output("forbidden", user_id=second["user_id"]).blocked
        assert checker.disabled and checker.safety_disabled
    finally:
        auth.close(); engine.dispose()
