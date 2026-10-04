"""
敏感词审核层 (Layer 1)。

功能说明:
本文件实现 `SensitiveWordChecker`,负责对用户输入做快速关键词 + 正则匹配,
在请求进入 Agent 主循环之前拦截明显违规内容。匹配分为:
- exact: 精确子串匹配
- regex: 正则模式匹配

每类敏感词都有 `risk_level` (high/medium/low) 和 `block` 标记,high 级别直接拒绝,
medium 级别交由下游意图审核进一步判断。

使用说明:
checker = SensitiveWordChecker.from_file("resources/safety/sensitive_words.json")
result = checker.check(text="用户输入")
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SensitiveWordHit:
    """单条敏感词命中结果。"""

    category: str
    category_name: str
    risk_level: str
    matched_text: str
    match_type: str  # "exact" | "regex"
    pattern: str


@dataclass(slots=True)
class SensitiveWordResult:
    """敏感词检查结果。"""

    blocked: bool
    hits: list[SensitiveWordHit] = field(default_factory=list)
    blocked_categories: list[str] = field(default_factory=list)

    @property
    def has_hits(self) -> bool:
        return len(self.hits) > 0


class SensitiveWordChecker:
    """敏感词检查器,加载分类词库进行双层匹配。"""

    def __init__(self, categories: dict[str, dict[str, Any]], *, disabled: bool = False, safety_disabled: bool = False) -> None:
        self.disabled = disabled
        self.safety_disabled = safety_disabled
        self._categories = categories
        self._compiled: dict[str, list[tuple[str, re.Pattern, str, str, bool]]] = {}
        for cat_key, cat_def in categories.items():
            entries: list[tuple[str, re.Pattern, str, str, bool]] = []
            for word in cat_def.get("exact", []):
                entries.append((word, re.compile(re.escape(word), re.IGNORECASE), "exact", word, cat_def.get("block", True)))
            for pattern in cat_def.get("regex", []):
                entries.append((pattern, re.compile(pattern, re.IGNORECASE), "regex", pattern, cat_def.get("block", True)))
            self._compiled[cat_key] = entries

    @classmethod
    def from_file(cls, filepath: str | Path) -> "SensitiveWordChecker":
        """从 JSON 词库文件加载并构造检查器。"""

        raw = json.loads(Path(filepath).read_text(encoding="utf-8"))
        return cls(
            categories=raw.get("categories", {}),
            disabled=raw.get("_sensitive_words_disabled", False),
            safety_disabled=raw.get("_safety_disabled", False),
        )

    def check(self, text: str, *, enabled: bool | None = None) -> SensitiveWordResult:
        """对输入文本执行全量敏感词匹配。"""

        if enabled is False or (enabled is None and (self.disabled or self.safety_disabled)):
            return SensitiveWordResult(blocked=False)

        hits: list[SensitiveWordHit] = []
        blocked_categories: list[str] = []
        for cat_key, entries in self._compiled.items():
            cat_def = self._categories[cat_key]
            for original, pattern, match_type, display, block in entries:
                match = pattern.search(text)
                if not match:
                    continue
                hits.append(SensitiveWordHit(
                    category=cat_key,
                    category_name=cat_def.get("name", cat_key),
                    risk_level=cat_def.get("risk_level", "medium"),
                    matched_text=match.group(),
                    match_type=match_type,
                    pattern=display,
                ))
                if block and cat_key not in blocked_categories:
                    blocked_categories.append(cat_key)
        return SensitiveWordResult(
            blocked=len(blocked_categories) > 0,
            hits=hits,
            blocked_categories=blocked_categories,
        )
