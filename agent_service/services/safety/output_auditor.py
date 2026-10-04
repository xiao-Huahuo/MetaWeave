"""
输出审核层 (Layer 3)。

功能说明:
本文件实现 `OutputAuditor`,在 Agent 生成最终回复后,对输出内容做安全校验。
审核策略:
- 关键词 + 正则快速扫描输出中的敏感内容
- 必要时可扩展为小模型二次校验

审核结果分为: pass(通过) / block(拦截) / sanitized(已清洗)

使用说明:
auditor = OutputAuditor(config=config)
result = auditor.audit(output_text="Agent生成的回复...", user_input="原始用户输入...")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_service.core.agent_config import AgentConfig
from agent_service.services.safety.sensitive_word_checker import SensitiveWordChecker, SensitiveWordHit


@dataclass(slots=True)
class OutputAuditResult:
    """输出审核结果。"""

    verdict: str  # "pass" | "block" | "sanitized"
    original_output: str
    cleaned_output: str | None = None
    hits: list[SensitiveWordHit] = field(default_factory=list)
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def sanitized(self) -> bool:
        return self.verdict == "sanitized"

    @property
    def safe_output(self) -> str:
        """返回安全可用的输出文本。"""

        if self.verdict == "block":
            return "抱歉,当前回复因安全原因无法显示。如需帮助请重新描述您的问题。"
        return self.cleaned_output or self.original_output


class OutputAuditor:
    """输出审核器,校验 Agent 生成的回复内容安全性。"""

    BLOCK_ON_CATEGORIES = {"politics", "pornography", "violence", "illegal"}
    SANITIZE_ON_CATEGORIES = {"spam_ad", "prompt_injection", "data_exfiltration"}

    def __init__(self, *, config: AgentConfig, sensitive_checker: SensitiveWordChecker | None = None) -> None:
        self.config = config
        self._sensitive_checker = sensitive_checker

    def audit(self, output_text: str, *, user_input: str = "", sensitive_enabled: bool | None = None) -> OutputAuditResult:
        """对 Agent 输出文本做安全审核。"""

        if self._sensitive_checker is None or sensitive_enabled is False:
            return OutputAuditResult(verdict="pass", original_output=output_text, reason="敏感词检查器未配置,跳过")

        result = self._sensitive_checker.check(output_text, enabled=sensitive_enabled)
        if not result.has_hits:
            return OutputAuditResult(verdict="pass", original_output=output_text)

        block_hits = [h for h in result.hits if h.category in self.BLOCK_ON_CATEGORIES]
        if block_hits:
            return OutputAuditResult(
                verdict="block",
                original_output=output_text,
                hits=block_hits,
                reason=f"输出命中拦截类敏感词: {[h.category_name for h in block_hits]}",
            )

        sanitize_hits = [h for h in result.hits if h.category in self.SANITIZE_ON_CATEGORIES]
        cleaned = output_text
        for hit in sanitize_hits:
            cleaned = cleaned.replace(hit.matched_text, "***")
        if sanitize_hits:
            return OutputAuditResult(
                verdict="sanitized",
                original_output=output_text,
                cleaned_output=cleaned,
                hits=sanitize_hits,
                reason=f"输出命中清洗类敏感词: {[h.category_name for h in sanitize_hits]}",
            )

        return OutputAuditResult(verdict="pass", original_output=output_text)
