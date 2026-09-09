"""
存储管理服务。

用途:
- 提供知识库与运行目录的只读路径定义、容量查询和安全清理功能。
- 知识库根目录通过独立设置切换，`.mw` 托管目录和运行目录不接受用户覆盖。
- 供 REST API 和前端"存储管理"设置页使用。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# 路径定义：key → (label, parent_key, can_clear, requires_restart)
STORAGE_PATH_DEFINITIONS: dict[str, dict[str, Any]] = {
    "knowledge_dir": {"label": "知识库路径", "parent": None, "can_clear": False, "requires_restart": False},
    "managed_root": {"label": "MetaWeave 托管目录 (.mw)", "parent": "knowledge_dir", "can_clear": False, "requires_restart": False},
    "markdown_dir": {"label": "Markdown 中间层", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "frontmatter_dir": {"label": "JSON Frontmatter", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "library_storage_dir": {"label": "图书馆存储路径", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "forms_dir": {"label": "智能表单资产", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "components_dir": {"label": "组件库", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "scanner_dir": {"label": "扫描器历史", "parent": "managed_root", "can_clear": False, "requires_restart": False},
    "base_data_dir": {"label": "运行时数据", "parent": None, "can_clear": False, "requires_restart": False},
    "assets_dir": {"label": "受管资源", "parent": "base_data_dir", "can_clear": False, "requires_restart": False},
    "dsh_sdk_dir": {"label": "DeepSeek Harness SDK", "parent": "assets_dir", "can_clear": False, "requires_restart": False},
    "db_dir": {"label": "数据库", "parent": "base_data_dir", "can_clear": False, "requires_restart": False},
    "relation_db_dir": {"label": "关系库路径", "parent": "db_dir", "can_clear": False, "requires_restart": False},
    "sqlite_path": {"label": "SQLite 数据库", "parent": "relation_db_dir", "can_clear": False, "requires_restart": False},
    "vector_db_dir": {"label": "向量数据库根路径", "parent": "db_dir", "can_clear": False, "requires_restart": False},
    "chroma_persist_dir": {"label": "Chroma 向量库", "parent": "vector_db_dir", "can_clear": False, "requires_restart": False},
    "log_dir": {"label": "日志文件", "parent": "base_data_dir", "can_clear": False, "requires_restart": False},
    "models_dir": {"label": "模型路径", "parent": "base_data_dir", "can_clear": False, "requires_restart": False},
    "embedding_model_dir": {"label": "Embedding 模型", "parent": "models_dir", "can_clear": False, "requires_restart": False},
    "local_model_dir": {"label": "本地 Qwen 大语言模型", "parent": "models_dir", "can_clear": False, "requires_restart": False},
    "paddleocr_model_dir": {"label": "结构化 OCR 流水线", "parent": "models_dir", "can_clear": False, "requires_restart": False},
    "rerank_model_dir": {"label": "CrossEncoder 模型", "parent": "models_dir", "can_clear": False, "requires_restart": False},
    "latex_runtime_dir": {"label": "LaTeX 运行环境", "parent": "base_data_dir", "can_clear": False, "requires_restart": False},
    "latex_distribution_dir": {"label": "MiKTeX 核心与宏包", "parent": "latex_runtime_dir", "can_clear": False, "requires_restart": False},
    "latex_repository_dir": {"label": "MiKTeX 下载仓库", "parent": "latex_runtime_dir", "can_clear": True, "requires_restart": False},
    "latex_temp_dir": {"label": "LaTeX 临时文件", "parent": "latex_runtime_dir", "can_clear": True, "requires_restart": False},
    "latex_build_cache_dir": {"label": "LaTeX 编译缓存", "parent": "managed_root", "can_clear": True, "requires_restart": False},
    "trash_dir": {"label": "最近删除", "parent": "base_data_dir", "can_clear": True, "requires_restart": False},
}

# 虚拟节点 key（不对应实际 config.storage 属性）
VIRTUAL_KEYS = {"models_dir", "db_dir", "latex_runtime_dir", "managed_root", "markdown_dir", "frontmatter_dir", "forms_dir", "components_dir", "scanner_dir"}

MANAGED_KNOWLEDGE_PATHS = {
    "managed_root": ".mw",
    "markdown_dir": ".mw/md",
    "frontmatter_dir": ".mw/frontmatter",
    "forms_dir": ".mw/forms",
    "components_dir": ".mw/components",
    "scanner_dir": ".mw/scan",
    "latex_build_cache_dir": ".mw/latex",
}

RUNTIME_VIRTUAL_PATHS = {
    "models_dir": "models",
    "db_dir": "db",
    "latex_runtime_dir": "latex",
}

RUNTIME_LATEX_PATHS = {
    "latex_distribution_dir": "latex/miktex",
    "latex_repository_dir": "latex/repository",
    "latex_temp_dir": "latex/temp",
}

# 明确可清空的路径 key 列表
CLEARABLE_KEYS = {k for k, v in STORAGE_PATH_DEFINITIONS.items() if v["can_clear"]}


def _dir_size(path: Path) -> int:
    """递归计算目录下所有文件的总字节数（不存在则返回 0）。"""

    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    except PermissionError:
        pass
    return total


def _directory_distribution(path: Path) -> list[dict[str, int | str]]:
    """统计目录的一级子目录占用，并将根目录文件合并为一个图表分类。"""

    if not path.exists() or not path.is_dir():
        return []
    distribution: list[dict[str, int | str]] = []
    root_file_bytes = 0
    try:
        for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
            size_bytes = _dir_size(child)
            if child.is_file():
                root_file_bytes += size_bytes
            elif size_bytes > 0:
                distribution.append({"name": child.name, "size_bytes": size_bytes})
    except PermissionError:
        return []
    if root_file_bytes > 0:
        distribution.append({"name": "根目录文件", "size_bytes": root_file_bytes})
    return distribution


class StorageService:
    """存储管理服务：展示真实路径，并只清理运行中可安全回收的目录。"""

    def __init__(self, config, settings_service):
        self.config = config
        self.settings_service = settings_service

    def get_storage_config(self, *, user_id: str) -> dict:
        """返回当前所有路径的值、大小和配置元数据。"""

        from agent_service.core.agent_config import AgentConfig  # noqa: F811

        storage = self.config.storage
        paths = []
        active_library = self.settings_service.get_active_knowledge_library(user_id=user_id)
        active_knowledge_dir = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        for key, definition in STORAGE_PATH_DEFINITIONS.items():
            if key == "knowledge_dir":
                size_bytes = _dir_size(active_knowledge_dir)
                paths.append({
                    "key": key,
                    "label": definition["label"],
                    "value": str(active_knowledge_dir),
                    "size_bytes": size_bytes,
                    "requires_restart": definition["requires_restart"],
                    "can_clear": definition["can_clear"],
                    "parent": definition["parent"],
                })
                continue
            if key == "library_storage_dir":
                current_path = (active_knowledge_dir / ".mw" / "library").resolve()
                size_bytes = _dir_size(current_path)
                paths.append({
                    "key": key,
                    "label": definition["label"],
                    "value": str(current_path),
                    "size_bytes": size_bytes,
                    "requires_restart": definition["requires_restart"],
                    "can_clear": definition["can_clear"],
                    "parent": definition["parent"],
                })
                continue
            if key in MANAGED_KNOWLEDGE_PATHS:
                current_path = (active_knowledge_dir / MANAGED_KNOWLEDGE_PATHS[key]).resolve()
                paths.append({
                    "key": key,
                    "label": definition["label"],
                    "value": str(current_path),
                    "size_bytes": _dir_size(current_path),
                    "requires_restart": definition["requires_restart"],
                    "can_clear": definition["can_clear"],
                    "parent": definition["parent"],
                })
                continue
            if key in VIRTUAL_KEYS:
                # 虚拟节点：路径基于 base_data_dir 拼接，大小为子项之和
                base = Path(getattr(storage, "base_data_dir")).expanduser().resolve()
                sub = RUNTIME_VIRTUAL_PATHS.get(key, "")
                virtual_path = base / sub
                size_bytes = _dir_size(virtual_path)
                paths.append({
                    "key": key,
                    "label": definition["label"],
                    "value": str(virtual_path),
                    "size_bytes": size_bytes,
                    "requires_restart": definition["requires_restart"],
                    "can_clear": definition["can_clear"],
                    "parent": definition["parent"],
                })
                continue
            if key in RUNTIME_LATEX_PATHS:
                current_path = (Path(storage.base_data_dir) / RUNTIME_LATEX_PATHS[key]).resolve()
                paths.append({
                    "key": key,
                    "label": definition["label"],
                    "value": str(current_path),
                    "size_bytes": _dir_size(current_path),
                    "requires_restart": definition["requires_restart"],
                    "can_clear": definition["can_clear"],
                    "parent": definition["parent"],
                })
                continue
            current_path = Path(getattr(storage, key)).expanduser().resolve()
            size_bytes = _dir_size(current_path)
            paths.append({
                "key": key,
                "label": definition["label"],
                "value": str(current_path),
                "size_bytes": size_bytes,
                "requires_restart": definition["requires_restart"],
                "can_clear": definition["can_clear"],
                "parent": definition["parent"],
            })

        # 计算顶层汇总
        knowledge_dir_total = _dir_size(active_knowledge_dir)
        runtime_total = _dir_size(Path(getattr(storage, "base_data_dir")))

        return {
            "paths": paths,
            "knowledge_dir_total_bytes": knowledge_dir_total,
            "runtime_total_bytes": runtime_total,
            "managed_resource_distribution": _directory_distribution(Path(storage.assets_dir)),
        }

    def save_storage_config(self, *, user_id: str, paths: dict[str, str]) -> dict:
        """拒绝修改只读存储路径；知识库根目录由独立接口负责切换。"""

        if paths:
            raise ValueError("存储路径为只读配置；仅知识库根目录可以切换")
        return {"requires_restart": False, "saved": []}

    def clear_path(self, *, path_key: str, user_id: str = "") -> dict:
        """删除精确白名单缓存内容并保留目录本身；用户源文件永不进入目标集合。"""

        if path_key not in CLEARABLE_KEYS:
            raise ValueError(f"不允许清空路径: {path_key}")

        storage = self.config.storage
        if path_key == "latex_build_cache_dir":
            active_library = self.settings_service.get_active_knowledge_library(user_id=user_id)
            target = (Path(str(active_library["knowledge_dir"])).expanduser().resolve() / ".mw" / "latex").resolve()
        elif path_key in RUNTIME_LATEX_PATHS:
            target = (Path(storage.base_data_dir) / RUNTIME_LATEX_PATHS[path_key]).resolve()
        else:
            target = Path(getattr(storage, path_key)).expanduser().resolve()
        freed = _dir_size(target)

        if not target.exists():
            return {"path_key": path_key, "freed_bytes": 0}

        if target.is_file():
            # sqlite_path 是文件，需要特殊处理：同时移除 WAL/SHM 日志文件
            if path_key == "sqlite_path":
                for suffix in ("", "-wal", "-shm"):
                    journal = target.with_suffix(target.suffix + suffix if suffix else target.suffix)
                    if journal.exists():
                        journal.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            # 重建空文件避免下游报错
            target.touch()
            return {"path_key": path_key, "freed_bytes": freed}

        # 目录路径：删除所有内容后重建空目录
        target.mkdir(parents=True, exist_ok=True)
        for child in target.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
        return {"path_key": path_key, "freed_bytes": freed}
