"""
用户设置服务。

管理用户自定义系统提示词条目(数据库持久化)和用户自定义长期记忆(向量库持久化)。
系统提示词以条目形式存储，启动时全部加载并拼接注入到 agent 系统提示词。
"""

from __future__ import annotations

import logging
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.user_settings import (
    DEFAULT_VIDEO_IGNORE_PATTERNS,
    UserKnowledgeLibrary,
    UserLLMConfig,
    UserLLMConfigPreset,
    UserVlmConfigPreset,
    UserSettingsRecord,
    UserSystemPromptEntry,
)
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate

if TYPE_CHECKING:
    from agent_service.services.memory.longterm_memory_service import LongTermMemoryService

logger = logging.getLogger(__name__)


def _with_default_video_ignore_patterns(patterns: str | None) -> str:
    """Append mandatory preview-only video rules without duplicating user rules."""

    lines = [line for line in str(patterns or "").splitlines() if line.strip()]
    known = {line.strip().lower() for line in lines}
    lines.extend(
        rule for rule in DEFAULT_VIDEO_IGNORE_PATTERNS.splitlines()
        if rule.lower() not in known
    )
    return "\n".join(lines)


class SettingsService:
    """用户设置服务 — 系统提示词条目 + 自定义长期记忆管理。"""

    def __init__(
        self,
        *,
        config: AgentConfig,
        memory_service: LongTermMemoryService,
    ) -> None:
        self.config = config
        self.memory_service = memory_service
        self.engine = memory_service.engine

    def _generate_prompt_id(self) -> str:
        return f"prompt_{uuid4().hex[:self.config.limits.generated_id_suffix_chars]}"

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    # ---- 用户设置档案 ----

    def ensure_user_profile(self, *, user_id: str) -> dict:
        """确保用户设置档案存在,并返回 editor/console 可共享的基础设置。"""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")

        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                now = self._utc_now()
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
                db.commit()
                db.refresh(record)
            active_library = self._ensure_active_library(db=db, record=record)
            self._migrate_managed_directories(db=db, user_id=normalized_user_id, library=active_library)
            return self._serialize_user_profile(record)

    def update_knowledge_dir(self, *, user_id: str, knowledge_dir: str, name: str | None = None) -> dict:
        """
        更新用户当前知识库目录并返回设置档案。

        user_id: 用户 ID。
        knowledge_dir: 用户选择的知识库目录,可为绝对路径或项目根相对路径。
        name: 用户显式设置的知识库显示名,为空时保留已有名称或使用目录名。
        """

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        normalized_knowledge_dir = self._resolve_knowledge_dir(knowledge_dir)
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(normalized_knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
            else:
                record.knowledge_dir = str(normalized_knowledge_dir)
                record.updated_at = now
            db.add(record)
            active_library = self._upsert_active_library(
                db=db,
                user_id=normalized_user_id,
                knowledge_dir=normalized_knowledge_dir,
                name=name,
                now=now,
            )
            db.commit()
            db.refresh(record)
            db.refresh(active_library)
            self._migrate_library_storage(db=db, record=record, library=active_library)
            return self._serialize_user_profile(record)

    def get_active_knowledge_library(self, *, user_id: str) -> dict:
        """
        获取用户当前 active 知识库配置。

        user_id: 用户 ID。
        """

        profile = self.ensure_user_profile(user_id=user_id)
        return dict(profile["active_knowledge_library"])

    def update_library_storage_dir(self, *, user_id: str, library_storage_dir: str) -> dict:
        """
        拒绝修改固定的图书馆托管目录。

        user_id: 旧调用签名中的用户 ID，仅用于兼容。
        library_storage_dir: 旧调用签名中的目标目录，仅用于兼容。
        """

        raise ValueError("图书馆存储目录固定为 .mw/library，不允许修改")

    def resolve_active_knowledge_owner_id(self, *, user_id: str) -> str:
        """
        返回当前 active 知识库在长期记忆表中的隔离 owner ID。

        user_id: 用户 ID。
        """

        active_library = self.get_active_knowledge_library(user_id=user_id)
        return self.build_knowledge_owner_id(
            user_id=user_id.strip(),
            library_id=str(active_library["library_id"]),
        )

    def _resolve_knowledge_dir(self, knowledge_dir: str) -> Path:
        """
        将用户传入的知识库目录解析为绝对路径。

        knowledge_dir: 用户输入目录;为空时使用默认知识库目录。
        """

        normalized = knowledge_dir.strip()
        if not normalized:
            return self.config.storage.knowledge_dir
        path = Path(normalized).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.config.storage.project_root / path).resolve()

    def _ensure_active_library(self, *, db: Session, record: UserSettingsRecord) -> UserKnowledgeLibrary:
        """
        确保用户至少拥有一个 active 知识库。

        db: 当前数据库 session。
        record: 用户设置记录。
        """

        statement = (
            select(UserKnowledgeLibrary)
            .where(UserKnowledgeLibrary.user_id == record.user_id)
            .where(UserKnowledgeLibrary.is_active == True)  # noqa: E712
            .limit(1)
        )
        active_library = db.exec(statement).first()
        if active_library is not None:
            self._migrate_library_storage(db=db, record=record, library=active_library)
            return active_library
        libraries = list(
            db.exec(
                select(UserKnowledgeLibrary)
                .where(UserKnowledgeLibrary.user_id == record.user_id)
                .order_by(UserKnowledgeLibrary.updated_at.desc())
            ).all()
        )
        if libraries:
            active_library = libraries[0]
            now = self._utc_now()
            for library in libraries:
                library.is_active = library.library_id == active_library.library_id
                library.updated_at = now
                db.add(library)
            record.knowledge_dir = active_library.knowledge_dir
            record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(active_library)
            db.refresh(record)
            self._migrate_library_storage(db=db, record=record, library=active_library)
            return active_library
        now = self._utc_now()
        library = self._upsert_active_library(
            db=db,
            user_id=record.user_id,
            knowledge_dir=self._resolve_knowledge_dir(record.knowledge_dir),
            now=now,
        )
        record.knowledge_dir = library.knowledge_dir
        record.updated_at = now
        db.add(record)
        db.commit()
        db.refresh(library)
        db.refresh(record)
        legacy_root = Path(library.knowledge_dir).expanduser().resolve() / "library"
        managed_root = Path(library.knowledge_dir).expanduser().resolve() / ".mw" / "library"
        if legacy_root.is_dir() and not managed_root.exists():
            self._move_library_storage_dir(old_path=legacy_root, new_path=managed_root)
        return library

    def _upsert_active_library(
        self,
        *,
        db: Session,
        user_id: str,
        knowledge_dir: Path,
        name: str | None = None,
        now: datetime,
    ) -> UserKnowledgeLibrary:
        """
        创建或更新用户知识库配置,并将其设为唯一 active。

        db: 当前数据库 session。
        user_id: 用户 ID。
        knowledge_dir: 规范化后的知识库目录。
        name: 可选知识库显示名。
        now: 当前 UTC 时间。
        """

        normalized_dir = str(knowledge_dir)
        library_id = self.build_library_id(user_id=user_id, knowledge_dir=normalized_dir)
        normalized_name = (name or "").strip()
        fallback_name = knowledge_dir.name or normalized_dir
        libraries = list(db.exec(select(UserKnowledgeLibrary).where(UserKnowledgeLibrary.user_id == user_id)).all())
        library = next((item for item in libraries if item.library_id == library_id), None)
        if library is None:
            library = UserKnowledgeLibrary(
                library_id=library_id,
                user_id=user_id,
                name=normalized_name or fallback_name,
                knowledge_dir=normalized_dir,
                library_storage_dir=".mw/library",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        else:
            library.knowledge_dir = normalized_dir
            library.name = normalized_name or library.name or fallback_name
            library.library_storage_dir = self._library_storage_relative_path(library)
            library.updated_at = now
        for item in libraries:
            item.is_active = item.library_id == library_id
            item.updated_at = now
            db.add(item)
        library.is_active = True
        db.add(library)
        return library

    def _resolve_library_storage_dir(self, *, knowledge_root: Path, library_storage_dir: str) -> Path:
        """
        解析图书馆文件存储目录并确保其仍位于当前知识库内。

        knowledge_root: 当前 active 知识库根目录。
        library_storage_dir: 用户输入目录。
        """

        raw_value = library_storage_dir.strip().replace("\\", "/").strip("/")
        candidate = Path(raw_value).expanduser() if raw_value else knowledge_root / ".mw" / "library"
        if not candidate.is_absolute():
            candidate = knowledge_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(knowledge_root.resolve())
        except ValueError as exc:
            raise ValueError("library_storage_dir must stay inside active knowledge library") from exc
        return resolved

    def _library_storage_relative_path(self, library: UserKnowledgeLibrary) -> str:
        """返回知识库内图书馆存储目录相对路径。"""

        knowledge_root = Path(library.knowledge_dir).expanduser().resolve()
        raw_value = str(getattr(library, "library_storage_dir", "") or "").strip()
        resolved = self._resolve_library_storage_dir(knowledge_root=knowledge_root, library_storage_dir=raw_value)
        return resolved.relative_to(knowledge_root).as_posix()

    def _migrate_library_storage(
        self,
        *,
        db: Session,
        record: UserSettingsRecord,
        library: UserKnowledgeLibrary,
    ) -> None:
        """将任意旧图书馆目录一次性迁移到固定的 `.mw/library`。"""

        old_relative = self._library_storage_relative_path(library)
        if old_relative == ".mw/library":
            return
        knowledge_root = Path(library.knowledge_dir).expanduser().resolve()
        new_relative = ".mw/library"
        self._move_library_storage_dir(
            old_path=(knowledge_root / old_relative).resolve(),
            new_path=(knowledge_root / new_relative).resolve(),
        )
        self._rewrite_library_item_source_paths(
            db=db,
            user_id=record.user_id,
            library_id=library.library_id,
            old_relative=old_relative,
            new_relative=new_relative,
        )
        now = self._utc_now()
        library.library_storage_dir = new_relative
        library.updated_at = now
        record.updated_at = now
        db.add(library)
        db.add(record)
        db.commit()
        db.refresh(library)

    def _migrate_managed_directories(
        self,
        *,
        db: Session,
        user_id: str,
        library: UserKnowledgeLibrary,
    ) -> None:
        """Move legacy app-owned roots under `.mw` and rewrite smart-form paths."""

        knowledge_root = Path(library.knowledge_dir).expanduser().resolve()
        managed_root = knowledge_root / ".mw"
        for name in ("forms", "components"):
            legacy_path = knowledge_root / name
            managed_path = managed_root / name
            if not legacy_path.is_dir():
                continue
            if managed_path.exists():
                if any(legacy_path.iterdir()):
                    raise ValueError(f"managed {name} migration target already exists")
                continue
            managed_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_path), str(managed_path))
        try:
            db.execute(
                text("UPDATE smart_forms SET asset_dir = '.mw/' || asset_dir WHERE user_id = :user_id AND asset_dir LIKE 'forms/%'"),
                {"user_id": user_id},
            )
            db.execute(
                text(
                    "UPDATE smart_form_cells SET asset_path = '.mw/' || asset_path "
                    "WHERE asset_path LIKE 'forms/%' AND form_id IN "
                    "(SELECT form_id FROM smart_forms WHERE user_id = :user_id)"
                ),
                {"user_id": user_id},
            )
            db.commit()
        except Exception:
            db.rollback()

    def _move_library_storage_dir(self, *, old_path: Path, new_path: Path) -> None:
        """将旧图书馆存储目录内容移动到新目录,不覆盖目标同名内容。"""

        if old_path == new_path:
            new_path.mkdir(parents=True, exist_ok=True)
            return
        new_inside_old = False
        try:
            new_path.relative_to(old_path)
            new_inside_old = True
        except ValueError:
            new_inside_old = False
        if new_inside_old:
            raise ValueError("library_storage_dir cannot be inside current library storage directory")
        new_path.mkdir(parents=True, exist_ok=True)
        if not old_path.exists():
            return
        if not old_path.is_dir():
            raise ValueError("existing library storage path is not a directory")
        for child in old_path.iterdir():
            destination = new_path / child.name
            if destination.exists():
                raise ValueError(f"target library storage already contains: {child.name}")
        for child in old_path.iterdir():
            shutil.move(str(child), str(new_path / child.name))

    def _rewrite_library_item_source_paths(
        self,
        *,
        db: Session,
        user_id: str,
        library_id: str,
        old_relative: str,
        new_relative: str,
    ) -> None:
        """重写当前知识库下图书馆虚拟条目的知识库文件相对路径前缀。"""

        from agent_service.models.library import LibraryItem

        old_prefix = old_relative.strip("/").replace("\\", "/")
        new_prefix = new_relative.strip("/").replace("\\", "/")
        if not old_prefix or old_prefix == new_prefix:
            return
        statement = (
            select(LibraryItem)
            .where(LibraryItem.user_id == user_id)
            .where(LibraryItem.library_id == library_id)
        )
        for item in db.exec(statement).all():
            source_path = item.source_path.strip().replace("\\", "/")
            storage_path = item.storage_path.strip().replace("\\", "/")
            if storage_path == old_prefix:
                item.storage_path = new_prefix
            elif storage_path.startswith(f"{old_prefix}/"):
                item.storage_path = f"{new_prefix}/{storage_path[len(old_prefix) + 1:]}"
            if source_path == old_prefix:
                item.source_path = new_prefix
            elif source_path.startswith(f"{old_prefix}/"):
                item.source_path = f"{new_prefix}/{source_path[len(old_prefix) + 1:]}"
            elif storage_path == item.storage_path:
                continue
            item.updated_at = self._utc_now()
            db.add(item)

    def _list_knowledge_libraries(self, *, user_id: str) -> list[UserKnowledgeLibrary]:
        """
        列出用户全部知识库配置。

        user_id: 用户 ID。
        """

        with Session(self.engine) as db:
            statement = (
                select(UserKnowledgeLibrary)
                .where(UserKnowledgeLibrary.user_id == user_id)
                .order_by(UserKnowledgeLibrary.updated_at.desc())
            )
            return list(db.exec(statement).all())

    def _serialize_user_profile(self, record: UserSettingsRecord) -> dict:
        """将用户设置记录转换为 REST 响应。"""
        libraries = self._list_knowledge_libraries(user_id=record.user_id)
        active_library = next((item for item in libraries if item.is_active), None)
        if active_library is None and libraries:
            active_library = libraries[0]
        return {
            "user_id": record.user_id,
            "knowledge_dir": active_library.knowledge_dir if active_library else record.knowledge_dir,
            "active_library_id": active_library.library_id if active_library else "",
            "active_knowledge_library": (
                self._serialize_knowledge_library(active_library) if active_library else None
            ),
            "knowledge_libraries": [self._serialize_knowledge_library(item) for item in libraries],
            "auto_ingest_on_upload": bool(record.auto_ingest_on_upload),
            "ocr_enabled": bool(record.ocr_enabled),
            "vlm_enabled": bool(record.vlm_enabled),
            "vision_understanding_enabled": bool(record.vision_understanding_enabled),
            "model_auto_download_enabled": bool(record.model_auto_download_enabled),
            "dsh_coding_agent_enabled": bool(record.dsh_coding_agent_enabled),
            "long_term_memory_enabled": bool(record.long_term_memory_enabled),
            "knowledge_ignore_patterns": _with_default_video_ignore_patterns(record.knowledge_ignore_patterns),
            "knowledge_supported_suffixes": list(self.config.constants.knowledge_supported_suffixes),
            "terminal_sandbox": self._load_terminal_sandbox_payload(record.terminal_sandbox_config),
            "ui_font_families": self._load_font_families(record.ui_font_families),
            "text_font_families": self._load_font_families(record.text_font_families),
            "ui_font_size_percent": self._normalize_font_size_percent(record.ui_font_size_percent),
            "text_font_size_percent": self._normalize_font_size_percent(record.text_font_size_percent),
            "font_size_percent": self._normalize_font_size_percent(record.ui_font_size_percent),
            "theme_primary_color": record.theme_primary_color,
            "theme_soft_color": record.theme_soft_color,
            "tag_colors": self._effective_tag_colors(record.tag_colors),
            "tag_colors_translucent": self._effective_tag_colors_translucent(record.tag_colors_translucent),
            "background_cover_url": record.background_cover_url,
            "show_backlinks": bool(record.show_backlinks),
            "graph_node_limit": record.graph_node_limit,
            "floating_launch_enabled": bool(record.floating_launch_enabled),
            "editor_image_assets_dir": self._normalize_editor_image_assets_dir(record.editor_image_assets_dir),
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _load_font_families(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [
            str(item).strip()
            for item in payload
            if isinstance(item, str) and str(item).strip()
        ]

    @staticmethod
    def _dump_font_families(families: list[str] | None) -> str:
        if not families:
            return ""
        seen: set[str] = set()
        normalized: list[str] = []
        for item in families:
            family = str(item).replace(";", "").replace("{", "").replace("}", "").strip()
            if not family:
                continue
            key = family.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(family)
        return json.dumps(normalized, ensure_ascii=False)

    def _normalize_font_size_percent(self, value: int | float | str | None) -> int:
        """Normalize editor font size percentage to the supported 50-150 range."""

        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = self.config.limits.default_font_size_percent
        return max(
            self.config.limits.font_size_min_percent,
            min(self.config.limits.font_size_max_percent, percent),
        )

    def save_font_config(
        self,
        *,
        user_id: str,
        ui_font_families: list[str] | None = None,
        text_font_families: list[str] | None = None,
        ui_font_size_percent: int | None = None,
        text_font_size_percent: int | None = None,
        font_size_percent: int | None = None,
    ) -> dict:
        """Persist independent UI and editor-text font settings."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
            if ui_font_families is not None:
                record.ui_font_families = self._dump_font_families(ui_font_families)
            if text_font_families is not None:
                record.text_font_families = self._dump_font_families(text_font_families)
            if font_size_percent is not None:
                legacy_size = self._normalize_font_size_percent(font_size_percent)
                if ui_font_size_percent is None:
                    record.ui_font_size_percent = legacy_size
                if text_font_size_percent is None:
                    record.text_font_size_percent = legacy_size
            if ui_font_size_percent is not None:
                record.ui_font_size_percent = self._normalize_font_size_percent(ui_font_size_percent)
            if text_font_size_percent is not None:
                record.text_font_size_percent = self._normalize_font_size_percent(text_font_size_percent)
            record.font_size_percent = record.ui_font_size_percent
            record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "user_id": record.user_id,
                "ui_font_families": self._load_font_families(record.ui_font_families),
                "text_font_families": self._load_font_families(record.text_font_families),
                "ui_font_size_percent": self._normalize_font_size_percent(record.ui_font_size_percent),
                "text_font_size_percent": self._normalize_font_size_percent(record.text_font_size_percent),
                "font_size_percent": self._normalize_font_size_percent(record.ui_font_size_percent),
                "updated_at": record.updated_at.isoformat(),
            }

    def get_font_config(self, *, user_id: str) -> dict:
        """Return the persisted font settings without mutating their timestamp."""

        profile = self.ensure_user_profile(user_id=user_id)
        return {
            "user_id": profile["user_id"],
            "ui_font_families": profile["ui_font_families"],
            "text_font_families": profile["text_font_families"],
            "ui_font_size_percent": profile["ui_font_size_percent"],
            "text_font_size_percent": profile["text_font_size_percent"],
            "font_size_percent": profile["font_size_percent"],
            "updated_at": profile["updated_at"],
        }

    @staticmethod
    def _normalize_theme_color(value: str | None) -> str:
        color = str(value or "").strip()
        if not color:
            return ""
        if len(color) in (4, 7) and color.startswith("#"):
            try:
                int(color[1:], 16)
            except ValueError as exc:
                raise ValueError("theme color must be a hex color") from exc
            if len(color) == 4:
                return "#" + "".join(ch * 2 for ch in color[1:]).lower()
            return color.lower()
        raise ValueError("theme color must be a hex color")

    def _normalize_tag_colors(self, value: object) -> list[str]:
        """Validate a complete six-color palette; an empty list resets the override."""

        if value == []:
            return []
        if not isinstance(value, list) or len(value) != 6:
            raise ValueError("tag_colors must contain exactly 6 hex colors")
        try:
            colors = [self._normalize_theme_color(item if isinstance(item, str) else None) for item in value]
        except ValueError as exc:
            raise ValueError("tag_colors must contain exactly 6 hex colors") from exc
        if any(not color for color in colors):
            raise ValueError("tag_colors must contain exactly 6 hex colors")
        return colors

    def _effective_tag_colors(self, raw_value: str | None) -> list[str]:
        """Return the persisted palette or the service-level appearance default."""

        if raw_value:
            try:
                return self._normalize_tag_colors(json.loads(raw_value))
            except (json.JSONDecodeError, ValueError):
                logger.warning("Invalid persisted tag palette; using service defaults")
        return self._normalize_tag_colors(list(self.config.appearance.tag_colors))

    def _effective_tag_colors_translucent(self, value: bool | None) -> bool:
        """Resolve the nullable user override against the service default."""

        return self.config.appearance.tag_colors_translucent if value is None else bool(value)

    def save_appearance_config(
        self,
        *,
        user_id: str,
        theme_primary_color: str | None = None,
        theme_soft_color: str | None = None,
        tag_colors: list[str] | None = None,
        tag_colors_translucent: bool | None = None,
        reset_tag_colors_translucent: bool = False,
        background_cover_url: str | None = None,
        show_backlinks: bool | None = None,
    ) -> dict:
        """Persist editor appearance colors and backlinks visibility."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
            if theme_primary_color is not None:
                record.theme_primary_color = self._normalize_theme_color(theme_primary_color)
            if theme_soft_color is not None:
                record.theme_soft_color = self._normalize_theme_color(theme_soft_color)
            if tag_colors is not None:
                normalized_tag_colors = self._normalize_tag_colors(tag_colors)
                record.tag_colors = json.dumps(normalized_tag_colors, separators=(",", ":")) if normalized_tag_colors else ""
            if tag_colors_translucent is not None and not isinstance(tag_colors_translucent, bool):
                raise ValueError("tag_colors_translucent must be a boolean or null")
            if reset_tag_colors_translucent:
                record.tag_colors_translucent = None
            elif tag_colors_translucent is not None:
                record.tag_colors_translucent = tag_colors_translucent
            if background_cover_url is not None:
                record.background_cover_url = self._normalize_background_cover_url(
                    user_id=normalized_user_id,
                    value=background_cover_url,
                )
            if show_backlinks is not None:
                record.show_backlinks = bool(show_backlinks)
            record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "user_id": record.user_id,
                "theme_primary_color": record.theme_primary_color,
                "theme_soft_color": record.theme_soft_color,
                "tag_colors": self._effective_tag_colors(record.tag_colors),
                "tag_colors_translucent": self._effective_tag_colors_translucent(record.tag_colors_translucent),
                "background_cover_url": record.background_cover_url,
                "show_backlinks": bool(record.show_backlinks),
                "updated_at": record.updated_at.isoformat(),
            }

    @staticmethod
    def _normalize_editor_image_assets_dir(value: str | None) -> str:
        """Return the relative image asset directory used by editor paste."""

        raw_value = str(value or "./assets/").strip().replace("\\", "/")
        if not raw_value:
            return "./assets/"
        if "\x00" in raw_value:
            raise ValueError("editor_image_assets_dir contains invalid characters")
        parts: list[str] = []
        for part in raw_value.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                raise ValueError("editor_image_assets_dir cannot contain ..")
            parts.append(part)
        normalized = "/".join(parts) or "assets"
        return f"./{normalized}/"

    def save_editor_paste_config(
        self,
        *,
        user_id: str,
        editor_image_assets_dir: str | None = None,
    ) -> dict:
        """Persist editor paste settings for clipboard image insertion."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
            if editor_image_assets_dir is not None:
                record.editor_image_assets_dir = self._normalize_editor_image_assets_dir(editor_image_assets_dir)
            record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "user_id": record.user_id,
                "editor_image_assets_dir": self._normalize_editor_image_assets_dir(record.editor_image_assets_dir),
                "updated_at": record.updated_at.isoformat(),
            }

    def get_appearance_config(self, *, user_id: str) -> dict:
        """Return persisted appearance and backlinks visibility settings."""

        profile = self.ensure_user_profile(user_id=user_id)
        return {
            "user_id": profile["user_id"],
            "theme_primary_color": profile["theme_primary_color"],
            "theme_soft_color": profile["theme_soft_color"],
            "tag_colors": profile["tag_colors"],
            "tag_colors_translucent": profile["tag_colors_translucent"],
            "background_cover_url": profile["background_cover_url"],
            "show_backlinks": profile["show_backlinks"],
            "updated_at": profile["updated_at"],
        }

    @staticmethod
    def _normalize_background_cover_url(*, user_id: str, value: str | None) -> str:
        """Allow reset or one persistent library asset owned by the current user."""

        normalized = str(value or "").strip()
        if not normalized:
            return ""
        expected_prefix = f"/library/assets/{user_id}/"
        if not normalized.startswith(expected_prefix) or ".." in normalized or "\\" in normalized or "\x00" in normalized:
            raise ValueError("background_cover_url must reference the current user's library asset")
        return normalized

    def list_knowledge_library_dirs(self) -> list[Path]:
        """Return all configured user knowledge library directories."""

        with Session(self.engine) as db:
            records = list(db.exec(select(UserKnowledgeLibrary)).all())
        dirs: list[Path] = []
        for record in records:
            raw_dir = str(record.knowledge_dir or "").strip()
            if raw_dir:
                dirs.append(Path(raw_dir).expanduser().resolve())
        return dirs

    @staticmethod
    def _serialize_knowledge_library(record: UserKnowledgeLibrary) -> dict:
        """
        将知识库配置记录转换为 API 响应。

        record: 知识库配置记录。
        """

        return {
            "library_id": record.library_id,
            "user_id": record.user_id,
            "name": record.name,
            "knowledge_dir": record.knowledge_dir,
            "library_storage_dir": SettingsService._library_storage_relative_path_static(record),
            "is_active": record.is_active,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _library_storage_relative_path_static(record: UserKnowledgeLibrary) -> str:
        """序列化时返回稳定的图书馆存储相对路径。"""

        knowledge_root = Path(record.knowledge_dir).expanduser().resolve()
        raw_value = str(getattr(record, "library_storage_dir", "") or ".mw/library").strip()
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            candidate = knowledge_root / raw_value
        try:
            return candidate.resolve().relative_to(knowledge_root).as_posix()
        except ValueError:
            return ".mw/library"

    def build_library_id(self, *, user_id: str, knowledge_dir: str) -> str:
        """
        根据用户和知识库目录生成稳定配置 ID。

        user_id: 用户 ID。
        knowledge_dir: 规范化后的知识库目录。
        """

        digest = hashlib.sha256(f"{user_id}\0{knowledge_dir}".encode("utf-8")).hexdigest()[:self.config.limits.generated_long_id_suffix_chars]
        return f"kb_{digest}"

    @staticmethod
    def build_knowledge_owner_id(*, user_id: str, library_id: str) -> str:
        """
        构造长期记忆表中隔离知识库切片的 owner ID。

        user_id: 用户 ID。
        library_id: 知识库配置 ID。
        """

        return f"{user_id}::knowledge::{library_id}"

    # ---- 系统提示词条目 ----

    def get_system_prompt(self, *, user_id: str) -> str:
        """获取用户所有自定义系统提示词条目，拼接为完整提示词。"""
        entries = self._list_entries(user_id)
        if not entries:
            return ""
        return "\n\n".join(e.content for e in entries)

    def list_system_prompt_entries(self, *, user_id: str) -> list[dict]:
        """列出用户的所有系统提示词条目。"""
        entries = self._list_entries(user_id)
        return [
            {"prompt_id": e.prompt_id, "content": e.content, "created_at": e.created_at.isoformat()}
            for e in entries
        ]

    def add_system_prompt_entry(self, *, user_id: str, content: str) -> dict:
        """添加一条系统提示词条目。"""
        now = self._utc_now()
        entry = UserSystemPromptEntry(
            prompt_id=self._generate_prompt_id(),
            user_id=user_id,
            content=content,
            created_at=now,
        )
        with Session(self.engine) as db:
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return {"prompt_id": entry.prompt_id, "content": entry.content, "created_at": entry.created_at.isoformat()}

    def delete_system_prompt_entry(self, *, prompt_id: str) -> bool:
        """删除一条系统提示词条目。"""
        with Session(self.engine) as db:
            entry = db.get(UserSystemPromptEntry, prompt_id)
            if entry is None:
                return False
            db.delete(entry)
            db.commit()
            return True

    def _list_entries(self, user_id: str) -> list[UserSystemPromptEntry]:
        with Session(self.engine) as db:
            statement = (
                select(UserSystemPromptEntry)
                .where(UserSystemPromptEntry.user_id == user_id)
                .order_by(UserSystemPromptEntry.created_at.asc())
            )
            return list(db.exec(statement).all())

    # ---- 自定义长期记忆 ----

    def list_memories(self, *, user_id: str) -> list[dict]:
        """列出用户的自定义长期记忆。"""
        records = self.memory_service.list_user_memories(
            user_id=user_id, memory_type="user_custom"
        )
        return [
            {
                "memory_id": r.memory_id,
                "content": r.content,
                "importance": r.importance,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]

    def add_memory(self, *, user_id: str, content: str, importance: float = 0.5) -> dict:
        """添加一条用户自定义长期记忆,生成向量并写入向量库。"""
        from agent_service.services.memory.rag.embedding import _get_shared_provider

        provider = _get_shared_provider(self.config)
        vectors = provider.embed_texts([content])
        vector = vectors[0] if vectors else []

        memory_create = LongTermMemorySpecCreate(
            user_id=user_id,
            tag=self.config.constants.memory_tag,
            memory_type="user_custom",
            content=content,
            source_type="user_input",
            source_id=str(uuid4()),
            importance=importance,
            confidence=1.0,
            authority=0.8,
            embedding_model=self.config.model.embedding_model_name,
            embedding_vector_json=vector,
        )
        record = self.memory_service.create_memory(memory_create)
        return {
            "memory_id": record.memory_id,
            "content": record.content,
            "importance": record.importance,
            "created_at": record.created_at.isoformat(),
        }

    # ---- 用户 LLM 配置 ----

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str:
        """Return a stripped string for optional model configuration fields."""

        return str(value or "").strip()

    def _effective_llm_fields(
        self,
        *,
        large_api_key: str,
        large_base_url: str,
        large_model_name: str,
        small_api_key: str,
        small_base_url: str,
        small_model_name: str,
    ) -> dict[str, str]:
        """Resolve the documented remote/remote/local model fallback matrix."""

        local_model_name = self._normalize_optional_text(self.config.model.local_model_name)
        large_is_remote = bool(large_model_name and large_api_key)
        effective_model_name = large_model_name if large_is_remote else local_model_name
        effective_small_model_name = (
            (small_model_name or large_model_name)
            if large_is_remote
            else local_model_name
        )
        small_uses_remote = large_is_remote
        return {
            "effective_api_key": large_api_key if large_is_remote else "",
            "effective_base_url": large_base_url if large_is_remote else "",
            "effective_model_name": effective_model_name,
            "effective_model_source": "remote" if large_is_remote else "local",
            "effective_small_api_key": (small_api_key or large_api_key) if small_uses_remote else "",
            "effective_small_base_url": (small_base_url or large_base_url) if small_uses_remote else "",
            "effective_small_model_name": effective_small_model_name,
            "effective_small_model_source": "remote" if small_uses_remote else "local",
        }

    def _serialize_llm_config(self, config: UserLLMConfig) -> dict:
        """Serialize current LLM settings and expose effective small-model fallback fields."""

        large_api_key = self._normalize_optional_text(config.api_key)
        large_base_url = self._normalize_optional_text(config.base_url)
        large_model_name = self._normalize_optional_text(config.model_name)
        small_api_key = self._normalize_optional_text(config.small_api_key)
        small_base_url = self._normalize_optional_text(config.small_base_url)
        small_model_name = self._normalize_optional_text(config.small_model_name)
        large_context_tokens, small_context_tokens = self._resolve_context_window_defaults(
            large_value=config.model_context_window_tokens,
            small_value=config.small_model_context_window_tokens,
            small_model_name=small_model_name,
        )
        effective = self._effective_llm_fields(
            large_api_key=large_api_key,
            large_base_url=large_base_url,
            large_model_name=large_model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
        )
        return {
            "user_id": config.user_id,
            "api_key": large_api_key,
            "base_url": large_base_url,
            "model_name": large_model_name,
            "small_api_key": small_api_key,
            "small_base_url": small_base_url,
            "small_model_name": small_model_name,
            "model_context_window_tokens": large_context_tokens,
            "model_max_output_tokens": int(config.model_max_output_tokens or 0),
            "small_model_context_window_tokens": small_context_tokens,
            "small_model_max_output_tokens": int(config.small_model_max_output_tokens or 0),
            **effective,
            "summary_trigger_tokens": self.config.memory.summary_trigger_tokens,
            "context_window_tokens": self.config.memory.context_window_tokens,
            "context_output_reserve_tokens": self.config.memory.context_output_reserve_tokens,
            "context_compression_trigger_ratio": self.config.memory.context_compression_trigger_ratio,
            "context_compression_target_ratio": self.config.memory.context_compression_target_ratio,
            "updated_at": config.updated_at.isoformat(),
        }

    def _build_default_llm_config(self, user_id: str) -> dict:
        """从 AgentConfig 构造服务级默认 LLM 配置响应，DB 无用户记录时作为回退。"""

        m = self.config.model
        mm = self.config.memory
        large_api_key = self._normalize_optional_text(m.api_key)
        large_base_url = self._normalize_optional_text(m.base_url)
        large_model_name = self._normalize_optional_text(m.model_name)
        small_api_key = self._normalize_optional_text(m.small_model_api_key)
        small_base_url = self._normalize_optional_text(m.small_model_base_url)
        small_model_name = self._normalize_optional_text(m.small_model_name)
        large_context_tokens, small_context_tokens = self._resolve_context_window_defaults(
            large_value=m.model_context_window_tokens,
            small_value=m.small_model_context_window_tokens,
            small_model_name=small_model_name,
        )
        effective = self._effective_llm_fields(
            large_api_key=large_api_key,
            large_base_url=large_base_url,
            large_model_name=large_model_name,
            small_api_key=small_api_key,
            small_base_url=small_base_url,
            small_model_name=small_model_name,
        )
        return {
            "user_id": user_id,
            "api_key": large_api_key,
            "base_url": large_base_url,
            "model_name": large_model_name,
            "small_api_key": small_api_key,
            "small_base_url": small_base_url,
            "small_model_name": small_model_name,
            "model_context_window_tokens": large_context_tokens,
            "model_max_output_tokens": int(m.model_max_output_tokens or 0),
            "small_model_context_window_tokens": small_context_tokens,
            "small_model_max_output_tokens": int(m.small_model_max_output_tokens or 0),
            **effective,
            "summary_trigger_tokens": mm.summary_trigger_tokens,
            "context_window_tokens": mm.context_window_tokens,
            "context_output_reserve_tokens": mm.context_output_reserve_tokens,
            "context_compression_trigger_ratio": mm.context_compression_trigger_ratio,
            "context_compression_target_ratio": mm.context_compression_target_ratio,
            "updated_at": self._utc_now().isoformat(),
        }

    def _resolve_context_window_defaults(
        self,
        *,
        large_value: Any,
        small_value: Any,
        small_model_name: str,
    ) -> tuple[int, int]:
        """把未填写的模型窗口解析为 100 万服务默认值，并保留小模型继承关系。"""

        service_default = max(int(self.config.memory.context_window_tokens), 1)
        large_context = max(int(large_value or 0), 0) or service_default
        small_context = max(int(small_value or 0), 0) or (
            service_default if small_model_name else large_context
        )
        return large_context, small_context

    def get_llm_config(self, *, user_id: str) -> dict:
        """获取用户自定义 LLM 配置，包含大模型和小模型两套；DB 无记录时回退到 AgentConfig 服务级默认值。"""

        with Session(self.engine) as db:
            config = db.get(UserLLMConfig, user_id.strip())
            if config is None:
                return self._build_default_llm_config(user_id.strip())
            return self._serialize_llm_config(config)

    def save_llm_config(
        self,
        *,
        user_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        small_api_key: str | None = None,
        small_base_url: str | None = None,
        small_model_name: str | None = None,
        model_context_window_tokens: int | None = None,
        model_max_output_tokens: int | None = None,
        small_model_context_window_tokens: int | None = None,
        small_model_max_output_tokens: int | None = None,
    ) -> dict:
        """保存用户自定义 LLM 配置，包含大模型和小模型两套。"""
        normalized_user_id = user_id.strip()
        now = self._utc_now()
        with Session(self.engine) as db:
            config = db.get(UserLLMConfig, normalized_user_id)
            if config is None:
                config = UserLLMConfig(
                    user_id=normalized_user_id,
                    api_key=api_key or "",
                    base_url=base_url or "",
                    model_name=model_name or "",
                    small_api_key=small_api_key or "",
                    small_base_url=small_base_url or "",
                    small_model_name=small_model_name or "",
                    model_context_window_tokens=max(int(model_context_window_tokens or 0), 0),
                    model_max_output_tokens=max(int(model_max_output_tokens or 0), 0),
                    small_model_context_window_tokens=max(int(small_model_context_window_tokens or 0), 0),
                    small_model_max_output_tokens=max(int(small_model_max_output_tokens or 0), 0),
                    updated_at=now,
                )
            else:
                if api_key is not None:
                    config.api_key = api_key
                if base_url is not None:
                    config.base_url = base_url
                if model_name is not None:
                    config.model_name = model_name
                if small_api_key is not None:
                    config.small_api_key = small_api_key
                if small_base_url is not None:
                    config.small_base_url = small_base_url
                if small_model_name is not None:
                    config.small_model_name = small_model_name
                if model_context_window_tokens is not None:
                    config.model_context_window_tokens = max(int(model_context_window_tokens), 0)
                if model_max_output_tokens is not None:
                    config.model_max_output_tokens = max(int(model_max_output_tokens), 0)
                if small_model_context_window_tokens is not None:
                    config.small_model_context_window_tokens = max(int(small_model_context_window_tokens), 0)
                if small_model_max_output_tokens is not None:
                    config.small_model_max_output_tokens = max(int(small_model_max_output_tokens), 0)
                config.updated_at = now
            db.add(config)
            db.commit()
            db.refresh(config)
            return self._serialize_llm_config(config)

    def list_llm_config_presets(self, *, user_id: str) -> list[dict]:
        """列出用户保存的单模型 LLM 配置。"""

        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            statement = (
                select(UserLLMConfigPreset)
                .where(UserLLMConfigPreset.user_id == normalized_user_id)
                .order_by(UserLLMConfigPreset.updated_at.desc())
            )
            return [self._serialize_llm_config_preset(record) for record in db.exec(statement).all()]

    def save_llm_config_preset(
        self,
        *,
        user_id: str,
        label: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> dict:
        """保存一条可复用的单模型 LLM 配置。"""

        normalized_user_id = user_id.strip()
        normalized_model_name = self._normalize_optional_text(model_name)
        normalized_base_url = self._normalize_optional_text(base_url)
        normalized_api_key = self._normalize_optional_text(api_key)
        if not normalized_user_id:
            raise ValueError("user_id is required")
        if not normalized_model_name and not normalized_base_url and not normalized_api_key:
            raise ValueError("model config is empty")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = UserLLMConfigPreset(
                config_id=f"llm_cfg_{uuid4().hex[:self.config.limits.generated_long_id_suffix_chars]}",
                user_id=normalized_user_id,
                label=self._normalize_optional_text(label) or normalized_model_name or normalized_base_url,
                api_key=normalized_api_key,
                base_url=normalized_base_url,
                model_name=normalized_model_name,
                created_at=now,
                updated_at=now,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._serialize_llm_config_preset(record)

    def delete_llm_config_preset(self, *, config_id: str) -> bool:
        """删除一条已保存的 LLM 配置。"""

        normalized_config_id = config_id.strip()
        with Session(self.engine) as db:
            record = db.get(UserLLMConfigPreset, normalized_config_id)
            if record is None:
                return False
            db.delete(record)
            db.commit()
            return True

    @staticmethod
    def _serialize_llm_config_preset(record: UserLLMConfigPreset) -> dict:
        """将已保存的 LLM 配置转换为 API 响应。"""

        return {
            "config_id": record.config_id,
            "user_id": record.user_id,
            "label": record.label,
            "api_key": record.api_key,
            "base_url": record.base_url,
            "model_name": record.model_name,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def remove_memory(self, *, memory_id: str) -> bool:
        """删除一条自定义长期记忆。"""
        return self.memory_service.delete_memory(memory_id=memory_id)

    # ---- 联网搜索配置 ----

    def get_web_search_config(self, *, user_id: str) -> dict:
        """获取用户的联网搜索配置（代理地址 + 开关状态 + 最大结果数）。"""
        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                return {
                    "user_id": normalized_user_id,
                    "proxy_url": "",
                    "browser_proxy_url": "",
                    "browser_home_url": "https://www.google.com",
                    "web_search_enabled": False,
                    "web_search_max_results": self.config.limits.default_web_search_max_results,
                }
            return {
                "user_id": normalized_user_id,
                "proxy_url": record.proxy_url,
                "browser_proxy_url": getattr(record, "browser_proxy_url", ""),
                "browser_home_url": getattr(record, "browser_home_url", "https://www.google.com") or "https://www.google.com",
                "web_search_enabled": record.web_search_enabled,
                "web_search_max_results": (
                    getattr(record, "web_search_max_results", self.config.limits.default_web_search_max_results)
                    or self.config.limits.default_web_search_max_results
                ),
            }

    def save_web_search_config(
        self,
        *,
        user_id: str,
        proxy_url: str | None = None,
        browser_proxy_url: str | None = None,
        browser_home_url: str | None = None,
        web_search_enabled: bool | None = None,
        web_search_max_results: int | None = None,
    ) -> dict:
        """保存用户的联网搜索配置。"""
        normalized_user_id = user_id.strip()
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    proxy_url=proxy_url or "",
                    browser_proxy_url=browser_proxy_url or "",
                    browser_home_url=browser_home_url or "https://www.google.com",
                    web_search_enabled=web_search_enabled or False,
                    web_search_max_results=(
                        web_search_max_results or self.config.limits.default_web_search_max_results
                    ),
                    created_at=now,
                    updated_at=now,
                )
            else:
                if proxy_url is not None:
                    record.proxy_url = proxy_url
                if browser_proxy_url is not None:
                    record.browser_proxy_url = browser_proxy_url
                if browser_home_url is not None:
                    record.browser_home_url = browser_home_url or "https://www.google.com"
                if web_search_enabled is not None:
                    record.web_search_enabled = web_search_enabled
                if web_search_max_results is not None:
                    record.web_search_max_results = web_search_max_results
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "proxy_url": record.proxy_url,
                "browser_proxy_url": record.browser_proxy_url,
                "browser_home_url": record.browser_home_url,
                "web_search_enabled": record.web_search_enabled,
                "web_search_max_results": (
                    getattr(record, "web_search_max_results", self.config.limits.default_web_search_max_results)
                    or self.config.limits.default_web_search_max_results
                ),
            }

    # ---- 长期记忆配置 ----

    def get_memory_config(self, *, user_id: str) -> dict:
        """获取用户的长期记忆总开关。"""

        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            return {"long_term_memory_enabled": bool(record.long_term_memory_enabled) if record else True}

    def save_memory_config(self, *, user_id: str, long_term_memory_enabled: bool) -> dict:
        """保存用户的长期记忆总开关。"""

        normalized_user_id = user_id.strip()
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    long_term_memory_enabled=bool(long_term_memory_enabled),
                    created_at=now,
                    updated_at=now,
                )
            else:
                record.long_term_memory_enabled = bool(long_term_memory_enabled)
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"long_term_memory_enabled": bool(record.long_term_memory_enabled)}

    # ---- 可开关工具 ----

    def get_disabled_tools(self, *, user_id: str) -> list[str]:
        """获取用户关闭的工具列表。"""
        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None or not record.disabled_tools:
                return []
            try:
                return json.loads(record.disabled_tools)
            except (json.JSONDecodeError, TypeError):
                return []

    def save_disabled_tools(self, *, user_id: str, tool_names: list[str]) -> list[str]:
        """保存用户关闭的工具列表。"""
        normalized_user_id = user_id.strip()
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    disabled_tools=json.dumps(tool_names, ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
            else:
                record.disabled_tools = json.dumps(tool_names, ensure_ascii=False)
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return json.loads(record.disabled_tools)

    def list_available_tools(self, *, user_id: str) -> list[dict]:
        """列出全部可用的内置工具及每项在当前用户的开关状态,按类别分组返回。"""
        from agent_service.tools.definitions import (
            CHILD_AGENT_TOOL_DEFINITIONS,
            FILE_TOOL_DEFINITIONS,
            GIT_TOOL_DEFINITIONS,
            KNOWLEDGE_TOOL_DEFINITIONS,
            LIBRARY_TOOL_DEFINITIONS,
            MEMORY_TOOL_DEFINITIONS,
            SKILL_TOOL_DEFINITIONS,
            TASK_LIST_TOOL_DEFINITIONS,
            TODO_TOOL_DEFINITIONS,
            UTILITY_TOOL_DEFINITIONS,
            WEB_SEARCH_TOOL_DEFINITIONS,
        )

        CATEGORIES: list[tuple[str, str, list]] = [
            ("UTILITY", "通用工具", UTILITY_TOOL_DEFINITIONS),
            ("GIT", "Git 工具", GIT_TOOL_DEFINITIONS),
            ("SKILL", "技能工具", SKILL_TOOL_DEFINITIONS),
            ("MEMORY", "记忆工具", MEMORY_TOOL_DEFINITIONS),
            ("KNOWLEDGE", "知识库工具", KNOWLEDGE_TOOL_DEFINITIONS),
            ("LIBRARY", "图书馆工具", LIBRARY_TOOL_DEFINITIONS),
            ("FILE", "文件管理工具", FILE_TOOL_DEFINITIONS),
            ("TASK_LIST", "任务列表工具", TASK_LIST_TOOL_DEFINITIONS),
            ("CHILD_AGENT", "子 Agent 工具", CHILD_AGENT_TOOL_DEFINITIONS),
            ("TODO", "待办工具", TODO_TOOL_DEFINITIONS),
            ("WEB_SEARCH", "联网搜索工具", WEB_SEARCH_TOOL_DEFINITIONS),
        ]

        disabled = set(self.get_disabled_tools(user_id=user_id))
        memory_enabled = self.get_memory_config(user_id=user_id)["long_term_memory_enabled"]
        memory_tool_names = {item.name for item in MEMORY_TOOL_DEFINITIONS}
        groups: list[dict] = []
        for category_key, display_name, definitions in CATEGORIES:
            tools = []
            for definition in definitions:
                tools.append({
                    "name": definition.name,
                    "display_name": getattr(definition, "display_name", "") or definition.name,
                    "description": definition.description,
                    "enabled": definition.name not in disabled and (
                        definition.name not in memory_tool_names or memory_enabled
                    ),
                })
            groups.append({
                "category": category_key,
                "display_name": display_name,
                "tools": tools,
            })
        return {"groups": groups}

    # ---- 终端沙盒配置 ----

    def get_terminal_sandbox_config(self, *, user_id: str) -> dict:
        """获取用户的 Agent 终端沙盒配置和三类终端支持的指令段目录；异常时回退服务级最小默认配置。"""

        from agent_service.services.terminal.command_sandbox import (
            TerminalSandboxSettings,
            build_default_terminal_sandbox_payload,
            build_terminal_segment_catalog,
        )

        normalized_user_id = user_id.strip()
        try:
            with Session(self.engine) as db:
                record = db.get(UserSettingsRecord, normalized_user_id)
                if record is None:
                    now = self._utc_now()
                    record = UserSettingsRecord(
                        user_id=normalized_user_id,
                        knowledge_dir=str(self.config.storage.knowledge_dir),
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(record)
                    db.flush()
                raw_payload = self._load_terminal_sandbox_payload(record.terminal_sandbox_config) if record else {}
                active_library = self._ensure_active_library(db=db, record=record)
            raw_payload = self._with_active_terminal_workspace_root(
                payload=raw_payload,
                active_knowledge_dir=active_library.knowledge_dir if active_library else "",
            )
            if not raw_payload:
                raw_payload = build_default_terminal_sandbox_payload(self.config)
            settings = TerminalSandboxSettings.from_config_payload(config=self.config, payload=raw_payload)
            return {
                "user_id": normalized_user_id,
                "config": settings.to_dict(),
                "segment_catalog": build_terminal_segment_catalog(settings),
            }
        except Exception:
            logger.warning("加载终端沙盒配置失败，回退到默认配置", exc_info=True)
            fallback = build_default_terminal_sandbox_payload(self.config)
            return {
                "user_id": normalized_user_id,
                "config": fallback,
                "segment_catalog": {"cmd": [], "powershell": [], "bash": []},
            }

    def save_terminal_sandbox_config(self, *, user_id: str, config_payload: dict[str, Any]) -> dict:
        """保存用户的 Agent 终端沙盒配置。"""

        from agent_service.services.terminal.command_sandbox import (
            TerminalSandboxSettings,
            build_terminal_segment_catalog,
        )

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
                db.flush()
            active_library = self._ensure_active_library(db=db, record=record)
            config_payload = self._with_active_terminal_workspace_root(
                payload=config_payload,
                active_knowledge_dir=active_library.knowledge_dir,
            )
            settings = TerminalSandboxSettings.from_config_payload(config=self.config, payload=config_payload)
            record.terminal_sandbox_config = json.dumps(settings.to_dict(), ensure_ascii=False)
            record.updated_at = now
            db.add(record)
            db.commit()
        return {
            "user_id": normalized_user_id,
            "config": settings.to_dict(),
            "segment_catalog": build_terminal_segment_catalog(settings),
        }

    @staticmethod
    def _load_terminal_sandbox_payload(raw_value: str | None) -> dict[str, Any]:
        """从数据库 JSON 字段中读取终端沙盒配置。"""

        if not raw_value:
            return {}
        try:
            payload = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _with_active_terminal_workspace_root(
        self,
        *,
        payload: dict[str, Any],
        active_knowledge_dir: str,
    ) -> dict[str, Any]:
        """把空白或旧项目根终端沙盒工作区迁移为 active 知识库目录。"""

        resolved_active_dir = Path(active_knowledge_dir or str(self.config.storage.knowledge_dir)).expanduser().resolve()
        result = dict(payload or {})
        raw_workspace_root = str(result.get("workspace_root") or "").strip()
        if not raw_workspace_root:
            result["workspace_root"] = str(resolved_active_dir)
            return result
        workspace_root = Path(raw_workspace_root).expanduser()
        if not workspace_root.is_absolute():
            workspace_root = (self.config.storage.project_root / workspace_root).resolve()
        else:
            workspace_root = workspace_root.resolve()
        legacy_roots = {
            self.config.storage.project_root.resolve(),
            self.config.storage.knowledge_dir.resolve(),
        }
        if workspace_root in legacy_roots:
            result["workspace_root"] = str(resolved_active_dir)
        return result

    # ---- 知识库灌库配置 ----

    def get_knowledge_ingestion_config(self, *, user_id: str) -> dict:
        """获取用户知识库灌库配置。默认上传不自动灌库。"""

        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                return {
                    "user_id": normalized_user_id,
                    "auto_ingest_on_upload": False,
                    "ocr_enabled": self.config.ocr.enabled,
                    "vlm_enabled": self.config.vlm.enabled,
                    "vision_understanding_enabled": False,
                    "dsh_coding_agent_enabled": False,
                    "knowledge_ignore_patterns": DEFAULT_VIDEO_IGNORE_PATTERNS,
                }
            return {
                "auto_ingest_on_upload": bool(record.auto_ingest_on_upload),
                "ocr_enabled": bool(record.ocr_enabled),
                "vlm_enabled": bool(record.vlm_enabled),
                "vision_understanding_enabled": bool(record.vision_understanding_enabled),
                "dsh_coding_agent_enabled": bool(record.dsh_coding_agent_enabled),
                "knowledge_ignore_patterns": _with_default_video_ignore_patterns(record.knowledge_ignore_patterns),
            }

    def save_knowledge_ingestion_config(
        self,
        *,
        user_id: str,
        auto_ingest_on_upload: bool | None = None,
        ocr_enabled: bool | None = None,
        vlm_enabled: bool | None = None,
        vision_understanding_enabled: bool | None = None,
        dsh_coding_agent_enabled: bool | None = None,
        knowledge_ignore_patterns: str | None = None,
    ) -> dict:
        """保存用户知识库灌库配置。"""

        normalized_user_id = user_id.strip()
        now = self._utc_now()
        restart_required = False
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    auto_ingest_on_upload=bool(auto_ingest_on_upload),
                    ocr_enabled=bool(ocr_enabled),
                    vlm_enabled=bool(vlm_enabled),
                    vision_understanding_enabled=bool(vision_understanding_enabled),
                    dsh_coding_agent_enabled=bool(dsh_coding_agent_enabled),
                    knowledge_ignore_patterns=_with_default_video_ignore_patterns(knowledge_ignore_patterns),
                    created_at=now,
                    updated_at=now,
                )
                restart_required = bool(ocr_enabled)
            else:
                if auto_ingest_on_upload is not None:
                    record.auto_ingest_on_upload = bool(auto_ingest_on_upload)
                if ocr_enabled is not None:
                    next_ocr_enabled = bool(ocr_enabled)
                    restart_required = bool(record.ocr_enabled) != next_ocr_enabled
                    record.ocr_enabled = next_ocr_enabled
                if vlm_enabled is not None:
                    record.vlm_enabled = bool(vlm_enabled)
                if vision_understanding_enabled is not None:
                    record.vision_understanding_enabled = bool(vision_understanding_enabled)
                if dsh_coding_agent_enabled is not None:
                    record.dsh_coding_agent_enabled = bool(dsh_coding_agent_enabled)
                if knowledge_ignore_patterns is not None:
                    record.knowledge_ignore_patterns = _with_default_video_ignore_patterns(knowledge_ignore_patterns)
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "auto_ingest_on_upload": bool(record.auto_ingest_on_upload),
                "ocr_enabled": bool(record.ocr_enabled),
                "vlm_enabled": bool(record.vlm_enabled),
                "vision_understanding_enabled": bool(record.vision_understanding_enabled),
                "dsh_coding_agent_enabled": bool(record.dsh_coding_agent_enabled),
                "knowledge_ignore_patterns": _with_default_video_ignore_patterns(record.knowledge_ignore_patterns),
                "restart_required": restart_required,
            }

    def save_graph_config(
        self,
        *,
        user_id: str,
        graph_node_limit: int | None = None,
    ) -> dict:
        """保存用户图谱配置。"""

        normalized_user_id = user_id.strip()
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    graph_node_limit=graph_node_limit or self.config.limits.graph_default_node_limit,
                    created_at=now,
                    updated_at=now,
                )
            else:
                if graph_node_limit is not None:
                    record.graph_node_limit = max(
                        self.config.limits.graph_min_node_limit,
                        min(int(graph_node_limit), self.config.limits.graph_max_node_limit),
                    )
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "graph_node_limit": record.graph_node_limit,
            }

    def get_vlm_config(self, *, user_id: str) -> dict[str, object]:
        """返回用户覆盖与服务默认合并后的 MinerU 精准 API 配置。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
        service = self.config.vlm
        api_key = (record.vlm_api_key if record else "") or service.api_key
        enabled = bool(record.vlm_enabled if record else service.enabled)
        return {
            "user_id": normalized_user_id,
            "enabled": enabled,
            "api_key": api_key,
            "configured": bool(api_key),
            "base_url": service.base_url,
            "model": (record.vlm_model if record else "") or service.model,
            "max_concurrency": (record.vlm_max_concurrency if record else 0) or service.max_concurrency,
            "max_file_bytes": (record.vlm_max_file_bytes if record else 0) or service.max_file_bytes,
            "max_pages": (record.vlm_max_pages if record else 0) or service.max_pages,
            "submit_rate_per_minute": (
                (record.vlm_submit_rate_per_minute if record else 0) or service.submit_rate_per_minute
            ),
            "result_rate_per_minute": (
                (record.vlm_result_rate_per_minute if record else 0) or service.result_rate_per_minute
            ),
            "batch_max_files": service.batch_max_files,
            "poll_interval_seconds": service.poll_interval_seconds,
            "timeout_seconds": service.timeout_seconds,
            "slot_dir": str(self.config.storage.base_data_dir / "locks" / "mineru"),
            "ocr_enabled": bool(record.ocr_enabled if record else self.config.ocr.enabled),
        }

    def save_vlm_config(
        self,
        *,
        user_id: str,
        enabled: bool | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_concurrency: int | None = None,
        max_file_bytes: int | None = None,
        max_pages: int | None = None,
        submit_rate_per_minute: int | None = None,
        result_rate_per_minute: int | None = None,
        ocr_enabled: bool | None = None,
    ) -> dict[str, object]:
        """持久化用户 MinerU 覆盖；开启 VLM 时必须存在有效形态的 Key。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        if model is not None and model not in {"pipeline", "vlm"}:
            raise ValueError("model 必须是 pipeline / vlm")
        numeric = {
            "max_concurrency": max_concurrency,
            "max_file_bytes": max_file_bytes,
            "max_pages": max_pages,
            "submit_rate_per_minute": submit_rate_per_minute,
            "result_rate_per_minute": result_rate_per_minute,
        }
        if any(value is not None and int(value) <= 0 for value in numeric.values()):
            raise ValueError("MinerU 限制参数必须为正整数")
        maxima = {
            "max_concurrency": self.config.vlm.batch_max_files,
            "max_file_bytes": self.config.vlm.max_file_bytes,
            "max_pages": self.config.vlm.max_pages,
            "submit_rate_per_minute": self.config.vlm.submit_rate_per_minute,
            "result_rate_per_minute": self.config.vlm.result_rate_per_minute,
        }
        if any(value is not None and int(value) > maxima[name] for name, value in numeric.items()):
            raise ValueError("MinerU 参数超过精准 API 当前公开上限")
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                )
            if api_key is not None:
                record.vlm_api_key = api_key.strip()
            effective_result_rate = int(
                result_rate_per_minute
                or record.vlm_result_rate_per_minute
                or self.config.vlm.result_rate_per_minute
            )
            effective_concurrency = int(
                max_concurrency
                or record.vlm_max_concurrency
                or self.config.vlm.max_concurrency
            )
            poll_safe_concurrency = max(
                1,
                int(effective_result_rate * self.config.vlm.poll_interval_seconds / 60),
            )
            if effective_concurrency > poll_safe_concurrency:
                raise ValueError("MinerU 并发超过当前查询频控与轮询间隔允许的安全上限")
            effective_key = record.vlm_api_key or self.config.vlm.api_key
            next_enabled = bool(enabled) if enabled is not None else bool(record.vlm_enabled)
            if next_enabled and not effective_key:
                raise ValueError("开启 VLM 前必须配置 MinerU API Key")
            if enabled is not None:
                record.vlm_enabled = next_enabled
            if model is not None:
                record.vlm_model = model
            for field_name, value in numeric.items():
                if value is not None:
                    setattr(record, f"vlm_{field_name}", int(value))
            if ocr_enabled is not None:
                record.ocr_enabled = bool(ocr_enabled)
            record.updated_at = self._utc_now()
            db.add(record)
            db.commit()
        return self.get_vlm_config(user_id=normalized_user_id)

    def list_vlm_config_presets(self, *, user_id: str) -> list[dict[str, object]]:
        """列出当前用户保存的 MinerU 精准 API 配置。"""

        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            records = db.exec(
                select(UserVlmConfigPreset)
                .where(UserVlmConfigPreset.user_id == normalized_user_id)
                .order_by(UserVlmConfigPreset.updated_at.desc())
            ).all()
            return [self._serialize_vlm_config_preset(record) for record in records]

    def save_vlm_config_preset(
        self,
        *,
        user_id: str,
        label: str,
        api_key: str,
        model: str,
        max_concurrency: int,
        max_file_bytes: int,
        max_pages: int,
        submit_rate_per_minute: int,
        result_rate_per_minute: int,
    ) -> dict[str, object]:
        """保存完整 MinerU 模型与限制参数，不包含 VLM/OCR 总开关。"""

        normalized_user_id = user_id.strip()
        normalized_label = label.strip()
        normalized_key = api_key.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        if not normalized_key:
            raise ValueError("保存 VLM 配置前必须填写 MinerU API Key")
        if model not in {"pipeline", "vlm"}:
            raise ValueError("model 必须是 pipeline / vlm")
        limits = {
            "max_concurrency": int(max_concurrency),
            "max_file_bytes": int(max_file_bytes),
            "max_pages": int(max_pages),
            "submit_rate_per_minute": int(submit_rate_per_minute),
            "result_rate_per_minute": int(result_rate_per_minute),
        }
        maxima = {
            "max_concurrency": self.config.vlm.batch_max_files,
            "max_file_bytes": self.config.vlm.max_file_bytes,
            "max_pages": self.config.vlm.max_pages,
            "submit_rate_per_minute": self.config.vlm.submit_rate_per_minute,
            "result_rate_per_minute": self.config.vlm.result_rate_per_minute,
        }
        if any(value <= 0 or value > maxima[name] for name, value in limits.items()):
            raise ValueError("MinerU 预设参数超出精准 API 当前公开范围")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = UserVlmConfigPreset(
                config_id=f"vlm_cfg_{uuid4().hex[:self.config.limits.generated_long_id_suffix_chars]}",
                user_id=normalized_user_id,
                label=normalized_label or f"MinerU {model}",
                api_key=normalized_key,
                model=model,
                **limits,
                created_at=now,
                updated_at=now,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._serialize_vlm_config_preset(record)

    def delete_vlm_config_preset(self, *, config_id: str, user_id: str) -> bool:
        """仅允许配置所有者删除一条 MinerU 预设。"""

        with Session(self.engine) as db:
            record = db.get(UserVlmConfigPreset, config_id.strip())
            if record is None or record.user_id != user_id.strip():
                return False
            db.delete(record)
            db.commit()
            return True

    @staticmethod
    def _serialize_vlm_config_preset(record: UserVlmConfigPreset) -> dict[str, object]:
        """把 MinerU 预设转换为 REST/gRPC/前端共享结构。"""

        return {
            "config_id": record.config_id,
            "user_id": record.user_id,
            "label": record.label,
            "api_key": record.api_key,
            "model": record.model,
            "max_concurrency": record.max_concurrency,
            "max_file_bytes": record.max_file_bytes,
            "max_pages": record.max_pages,
            "submit_rate_per_minute": record.submit_rate_per_minute,
            "result_rate_per_minute": record.result_rate_per_minute,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def save_floating_config(
        self,
        *,
        user_id: str,
        floating_launch_enabled: bool | None = None,
    ) -> dict:
        """保存用户悬浮窗启动配置。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    floating_launch_enabled=bool(floating_launch_enabled),
                    created_at=now,
                    updated_at=now,
                )
            else:
                if floating_launch_enabled is not None:
                    record.floating_launch_enabled = bool(floating_launch_enabled)
                record.updated_at = now
            db.add(record)
            db.commit()
            db.refresh(record)
            return {
                "user_id": record.user_id,
                "floating_launch_enabled": bool(record.floating_launch_enabled),
                "updated_at": record.updated_at.isoformat(),
            }

    def is_ocr_enabled_for_user(self, *, user_id: str) -> bool:
        """返回用户保存的 OCR 开关状态。"""

        normalized_user_id = user_id.strip()
        with Session(self.engine) as db:
            value = db.exec(
                select(UserSettingsRecord.ocr_enabled).where(UserSettingsRecord.user_id == normalized_user_id)
            ).first()
            return bool(value)

    def is_vision_understanding_enabled_for_user(self, *, user_id: str) -> bool:
        """返回用户是否显式允许本地 Qwen 执行图片语义识别。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return False
        try:
            with Session(self.engine) as db:
                value = db.exec(
                    select(UserSettingsRecord.vision_understanding_enabled).where(
                        UserSettingsRecord.user_id == normalized_user_id
                    )
                ).first()
                return bool(value)
        except Exception:  # noqa: BLE001
            logger.warning("读取识图设置失败，安全回退为关闭 | user=%s", normalized_user_id, exc_info=True)
            return False

    def is_dsh_coding_agent_enabled_for_user(self, *, user_id: str) -> bool:
        """返回用户是否显式允许主 Agent调度 DSH coding agent。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return False
        try:
            with Session(self.engine) as db:
                value = db.exec(
                    select(UserSettingsRecord.dsh_coding_agent_enabled).where(
                        UserSettingsRecord.user_id == normalized_user_id
                    )
                ).first()
                return bool(value)
        except Exception:  # noqa: BLE001
            logger.warning("读取 DSH coding agent设置失败，安全回退为关闭 | user=%s", normalized_user_id, exc_info=True)
            return False
    def get_model_preferences(self, *, user_id: str) -> dict[str, object]:
        """返回模型下载偏好；未创建用户档案时默认关闭自动下载。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            return {
                "user_id": normalized_user_id,
                "auto_download_enabled": bool(record and record.model_auto_download_enabled),
            }

    def save_model_preferences(self, *, user_id: str, auto_download_enabled: bool) -> dict[str, object]:
        """持久化用户显式选择的模型自动下载开关。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = self._utc_now()
        with Session(self.engine) as db:
            record = db.get(UserSettingsRecord, normalized_user_id)
            if record is None:
                record = UserSettingsRecord(
                    user_id=normalized_user_id,
                    knowledge_dir=str(self.config.storage.knowledge_dir),
                    created_at=now,
                    updated_at=now,
                )
            record.model_auto_download_enabled = bool(auto_download_enabled)
            record.updated_at = now
            db.add(record)
            db.commit()
        return {"user_id": normalized_user_id, "auto_download_enabled": bool(auto_download_enabled)}

    def _ensure_paddleocr_models_if_required(self) -> None:
        """当已有用户开启 OCR 时,启动阶段检查并预热 PaddleOCR 模型。"""

        try:
            with Session(self.engine) as db:
                enabled_count = db.exec(
                    select(UserSettingsRecord).where(UserSettingsRecord.ocr_enabled == True)  # noqa: E712
                ).first()
            if enabled_count is None:
                return
            from agent_service.scripts.download_model import ensure_paddleocr_models

            ensure_paddleocr_models(
                paddleocr_model_dir=self.config.storage.paddleocr_model_dir,
                language=self.config.ocr.language,
                model_names=self.config.ocr.pipeline_model_names,
                feature_flags=self.config.ocr.pipeline_feature_flags,
                device=self.config.ocr.device,
            )
            self.config.ocr.enabled = True
        except Exception as exc:
            logger.warning("PaddleOCR 结构化流水线检查失败: %s", exc)
