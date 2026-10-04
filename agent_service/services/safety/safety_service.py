"""
统一安全审核服务。

功能说明:
本文件实现 `SafetyService`,整合三层安全审核:
1. 敏感词初检 (SensitiveWordChecker) — 输入阶段,快速关键词+正则拦截
2. 意图审核 (IntentAuditor) — 输入阶段,小模型语义级安全判断
3. 输出审核 (OutputAuditor) — 输出阶段,校验 Agent 回复内容

使用说明:
service = SafetyService(config=config, task_scheduler=scheduler)
input_result = service.audit_input(user_input="用户消息")
if input_result.blocked:
    return input_result.block_message
output_result = service.audit_output(output_text="Agent回复", user_input="原始输入")
return output_result.safe_output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.core.agent_config import AgentConfig
from agent_service.services.safety.intent_auditor import (
    IntentAuditResult,
    IntentAuditor,
    resolve_llm_overrides_from_config,
)
from agent_service.services.safety.output_auditor import OutputAuditResult, OutputAuditor
from agent_service.services.safety.sensitive_word_checker import SensitiveWordChecker, SensitiveWordResult
from agent_service.services.scheduler import (
    FOREGROUND_AGENT_TASK,
    SMALL_MODEL_TIER,
    get_llm_task_scheduler,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InputAuditResult:
    """输入审核综合结果(敏感词 + 意图)。"""

    passed: bool
    sensitive_result: SensitiveWordResult | None = None
    intent_result: IntentAuditResult | None = None
    block_reason: str = ""
    is_political: bool = False

    @property
    def blocked(self) -> bool:
        return not self.passed


class SafetyService:
    """统一安全审核服务,管理三层审核流水线。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        task_scheduler: Any | None = None,
        sensitive_words_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.settings_service = None
        self.sensitive_words_path = (
            Path(sensitive_words_path).expanduser().resolve()
            if sensitive_words_path is not None
            else config.storage.sensitive_words_path
        )
        self._sensitive_checker = (
            SensitiveWordChecker.from_file(self.sensitive_words_path)
            if self.sensitive_words_path.exists()
            else None
        )
        self._intent_auditor = IntentAuditor(config=config, task_scheduler=task_scheduler)
        self._output_auditor = OutputAuditor(
            config=config,
            sensitive_checker=self._sensitive_checker,
        )

    def audit_input(
        self,
        user_input: str,
        *,
        llm_config: dict[str, Any] | None = None,
        user_id: str = "",
    ) -> InputAuditResult:
        """
        对用户输入执行完整输入审核流水线。
        Layer 1 (敏感词) → Layer 2 (意图审核)。
        """

        audit_text = self._extract_user_question_for_audit(user_input)

        # 安全审核系统一键关闭
        policy = self.settings_service.get_safety_config(user_id=user_id) if self.settings_service and user_id else None
        if (policy is not None and not policy["safety_enabled"]) or (policy is None and self._sensitive_checker and self._sensitive_checker.safety_disabled):
            return InputAuditResult(passed=True)

        if self._sensitive_checker is not None:
            sensitive_result = self._sensitive_checker.check(audit_text, enabled=policy["sensitive_words_enabled"] if policy else None)
            if sensitive_result.blocked:
                logger.warning(
                    "输入审核拦截(敏感词) | categories=%s input_len=%d",
                    sensitive_result.blocked_categories,
                    len(audit_text),
                )
                is_political = "politics" in sensitive_result.blocked_categories
                return InputAuditResult(
                    passed=False,
                    sensitive_result=sensitive_result,
                    block_reason=f"敏感词拦截: {sensitive_result.blocked_categories}",
                    is_political=is_political,
                )
        else:
            sensitive_result = None

        if not audit_text.strip():
            return InputAuditResult(passed=True)

        intent_result = self._intent_auditor.audit(audit_text, llm_config=llm_config)
        if intent_result.blocked:
            logger.warning(
                "输入审核拦截(意图) | risk_type=%s input_len=%d",
                intent_result.risk_type,
                len(audit_text),
            )
            is_political = (
                intent_result.risk_type == "政治抹黑"
                or (sensitive_result is not None and "politics" in sensitive_result.blocked_categories)
            )
            return InputAuditResult(
                passed=False,
                sensitive_result=sensitive_result,
                intent_result=intent_result,
                block_reason=f"意图审核拦截: {intent_result.risk_type}",
                is_political=is_political,
            )

        return InputAuditResult(
            passed=True,
            sensitive_result=sensitive_result,
            intent_result=intent_result,
        )

    @staticmethod
    def _extract_user_question_for_audit(user_input: str) -> str:
        """
        Audit only the user's actual request, not quoted document material.

        ContextBuilder wraps selected text as:
        用户问题引用了以下文档片段...
        ----- 引用结束 -----

        用户问题:
        <actual prompt>

        The quoted document may legitimately contain terms that would be unsafe
        as instructions, but the user's intent is represented by the final
        question. Falling back to the full text preserves normal behavior for
        plain messages and older history.
        """

        marker = "用户问题:"
        marker_index = user_input.rfind(marker)
        if marker_index < 0:
            return user_input
        question = user_input[marker_index + len(marker):].strip()
        return question or user_input

    def generate_block_message(
        self,
        audit_result: InputAuditResult,
        user_input: str,
        *,
        llm_config: dict[str, Any] | None = None,
    ) -> str:
        """根据审核结果类型,使用小模型生成差异化的拦截回复。

        - 政治敏感: 生成政治立场正确的反驳性回复。
        - 其他拦截: 生成脱敏的礼貌拒绝回复。
        """

        if not self._should_generate_block_message(audit_result):
            return "您的问题包含不当内容,暂时无法处理。如需帮助,请调整措辞后重试。"

        try:
            scheduler = get_llm_task_scheduler(self.config)
            system_prompt = self._get_block_message_prompt(audit_result)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
            ]
            api_key, base_url, small_api_key, small_base_url = resolve_llm_overrides_from_config(llm_config)
            response = scheduler.invoke_chat(
                task_type=FOREGROUND_AGENT_TASK,
                messages=messages,
                temperature=0.3,
                model_tier=SMALL_MODEL_TIER,
                timeout_seconds=self.config.limits.safety_output_timeout_seconds,
                api_key=api_key,
                base_url=base_url,
                small_api_key=small_api_key,
                small_base_url=small_base_url,
            )
            return str(response.content).strip()
        except Exception:
            return self._fallback_block_message(audit_result)

    def _get_block_message_prompt(self, audit_result: InputAuditResult) -> str:
        """根据拦截类型选择对应的系统提示词。"""

        if audit_result.is_political:
            return self.config.prompts.safety_political_block_system_prompt.format(
                min_chars=self.config.limits.safety_political_reply_min_chars,
                max_chars=self.config.limits.safety_political_reply_max_chars,
            )
        return self.config.prompts.safety_general_block_system_prompt.format(
            max_chars=self.config.limits.safety_general_reply_max_chars,
        )

    @staticmethod
    def _should_generate_block_message(audit_result: InputAuditResult) -> bool:
        """判断是否需要调用小模型生成拦截回复。"""

        if audit_result.is_political:
            return True
        if audit_result.sensitive_result and audit_result.sensitive_result.blocked:
            return True
        if audit_result.intent_result and audit_result.intent_result.blocked:
            return True
        return False

    @staticmethod
    def _fallback_block_message(audit_result: InputAuditResult) -> str:
        """小模型调用失败时的静态后备回复。"""

        if audit_result.is_political:
            return (
                "您所提及的内容与事实严重不符。中国共产党始终坚持以人民为中心的发展思想,"
                "带领中国人民取得了举世瞩目的成就。请基于客观事实进行讨论。"
            )
        return "对不起,我不能回答这个问题,因为这超出了我能讨论的范围。如需其他帮助请随时告诉我。"

    def audit_output(self, output_text: str, *, user_input: str = "", user_id: str = "") -> OutputAuditResult:
        """对 Agent 输出执行 Layer 3 输出审核。"""

        # 安全审核系统一键关闭
        policy = self.settings_service.get_safety_config(user_id=user_id) if self.settings_service and user_id else None
        if (policy is not None and not policy["safety_enabled"]) or (policy is None and self._sensitive_checker and self._sensitive_checker.safety_disabled):
            return OutputAuditResult(verdict="pass", original_output=output_text)

        result = self._output_auditor.audit(output_text, user_input=user_input, sensitive_enabled=policy["sensitive_words_enabled"] if policy else None)
        if result.blocked or result.sanitized:
            logger.warning(
                "输出审核 | blocked=%s sanitized=%s output_len=%d",
                result.blocked,
                result.sanitized,
                len(output_text),
            )
        return result

    def reload_sensitive_words(self) -> None:
        """从磁盘重新加载敏感词库（热重载）。由 POST /settings/safety/sensitive-words 触发调用。"""

        path = self.sensitive_words_path
        self._sensitive_checker = SensitiveWordChecker.from_file(path) if path.exists() else None
        self._output_auditor = OutputAuditor(
            config=self.config,
            sensitive_checker=self._sensitive_checker,
        )
        logger.info("敏感词库已热重载 | path=%s", path)

    @property
    def supports_input_audit(self) -> bool:
        """是否支持输入审核(至少敏感词检查器或意图审核器可用)。"""

        return self._sensitive_checker is not None or self._intent_auditor is not None
