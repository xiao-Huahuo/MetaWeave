"""校验 Agent 工具条和文档与正式内置注册表保持一致。

使用说明：新增或删除内置工具后执行本模块，发现名称、图标或工具明细遗漏。
"""

import json
import re
from pathlib import Path

from agent_service.tools.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_native_tools_have_shared_display_names_and_category_icons() -> None:
    """每个正式工具都有同源中文名和显式分类图标，而不是未知工具兜底。"""

    definitions = ToolRegistry.with_builtin_tools().definitions
    base = ROOT / "editor/src/components/editor_workspace/agent_chat"
    display_source = (base / "toolDisplayNames.ts").read_text(encoding="utf-8")
    display_names = json.loads(re.search(r"=\s*(\{[\s\S]*?\})", display_source).group(1))
    assert display_names == {name: definition.display_name or name for name, definition in definitions.items()}
    icons_source = (base / "toolIcons.ts").read_text(encoding="utf-8")
    icon_groups = re.findall(r"\['[^']+',\s*\[([^\]]*)\]\s*\]", icons_source)
    icon_names = set(re.findall(r"'([^']+)'", "\n".join(icon_groups)))
    assert set(definitions).issubset(icon_names), set(definitions) - icon_names


def test_documented_tools_match_the_native_registry() -> None:
    """工具明细只列当前实际注册的工具；README 引用同一份完整清单。"""

    definitions = ToolRegistry.with_builtin_tools().definitions
    text = (ROOT / "docs/TOOLS.md").read_text(encoding="utf-8")
    documented = re.findall(r"^\| `([^`]+)` \|", text, re.MULTILINE)
    assert len(documented) == len(set(documented))
    assert set(documented) == set(definitions)
    assert "[K#]` 时挂载" not in text
    assert "get_knowledge_url" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[完整工具明细](docs/TOOLS.md)" in readme
    assert f"**{len(definitions)} 项内置工具**" in readme
