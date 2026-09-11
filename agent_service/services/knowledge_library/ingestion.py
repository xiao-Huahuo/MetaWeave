"""KnowledgeLibraryService 的 ingestion 职责。

方法体由原服务机械迁移，业务行为不变。
"""

from __future__ import annotations

import base64
import csv
import fnmatch
import hashlib
import html
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

logger = logging.getLogger(__name__)



from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.memory.rag.embedding import EmbeddingService
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.knowledge_ingestion import KnowledgeIngestionService
from agent_service.services.memory.rag.pdf_cleaner import extract_pdf_text
from agent_service.services.settings.service import SettingsService
from agent_service.services.knowledge_graph import KnowledgeGraphService

from agent_service.services.knowledge_library.service import (
    KnowledgeIgnoreMatcher, KnowledgeLibraryRebuildResult, _open_text_with_fallback,
    _read_text_with_fallback, _utcnow_naive,
)

class KnowledgeIngestionMixin:
    def rebuild_user_knowledge(
        self,
        *,
        user_id: str,
        knowledge_dir: str | None = None,
        uploaded_path: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> KnowledgeLibraryRebuildResult:
        """
        重新扫描用户知识库并写入向量库。

        user_id: 用户 ID。
        knowledge_dir: 可选新知识库目录;传入时先写入用户设置。
        uploaded_path: 可选上传文件路径,仅用于 API 返回。
        """

        if knowledge_dir is not None:
            profile = self.settings_service.update_knowledge_dir(user_id=user_id, knowledge_dir=knowledge_dir)
        else:
            profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        knowledge_owner_id = self.settings_service.build_knowledge_owner_id(
            user_id=normalized_user_id,
            library_id=library_id,
        )
        source_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        source_root.mkdir(parents=True, exist_ok=True)
        frontmatter_root = self._resolve_user_frontmatter_dir(normalized_user_id, library_id)
        markdown_root = self._resolve_user_markdown_dir(normalized_user_id, library_id)
        frontmatter_root.mkdir(parents=True, exist_ok=True)
        markdown_root.mkdir(parents=True, exist_ok=True)
        ignore_matcher = self._build_ignore_matcher(user_id=normalized_user_id)

        ocr_enabled = self.settings_service.is_ocr_enabled_for_user(user_id=normalized_user_id)
        vlm_config = self.settings_service.get_vlm_config(user_id=normalized_user_id)
        frontmatter_result = FrontmatterBootstrapService(
            config=self.config,
            ocr_enabled=ocr_enabled,
            vlm_config=vlm_config,
            online_enabled=bool(vlm_config.get("enabled")),
        ).build_frontmatter_dir(
            knowledge_dir=source_root,
            frontmatter_dir=frontmatter_root,
            markdown_dir=markdown_root,
            supported_suffixes=self.supported_suffixes,
            exclude_path=lambda path: ignore_matcher.is_ignored(
                self._relative_path(path=path, root=source_root),
                is_dir=False,
            ),
            progress_callback=progress_callback,
        )
        self._delete_ignored_frontmatter_files(
            frontmatter_root=frontmatter_root,
            ignore_matcher=ignore_matcher,
        )
        ingestion_service = KnowledgeIngestionService(
            config=self.config,
            embedding_service=self.embedding_service,
            memory_service=self.memory_service,
        )
        ingestion_result = ingestion_service.ingest_frontmatter_dir(
            frontmatter_dir=frontmatter_root,
            user_id=knowledge_owner_id,
            progress_callback=progress_callback,
        )
        chunks_deleted = self.memory_service.delete_memories_except_sources(
            user_id=knowledge_owner_id,
            tag=self.config.constants.knowledge_tag,
            memory_type="knowledge_chunk",
            keep_source_ids=(ingestion_result.source_ids_seen or set()) | self._managed_ingest_source_ids(frontmatter_root),
        )
        return KnowledgeLibraryRebuildResult(
            user_id=normalized_user_id,
            library_id=library_id,
            knowledge_dir=str(source_root),
            frontmatter_dir=str(frontmatter_root),
            frontmatter_files_seen=frontmatter_result.files_seen,
            frontmatter_files_written=frontmatter_result.files_written,
            frontmatter_files_skipped=frontmatter_result.files_skipped,
            files_seen=ingestion_result.files_seen,
            files_ingested=ingestion_result.files_ingested,
            files_skipped=ingestion_result.files_skipped,
            chunks_created=ingestion_result.chunks_created,
            chunks_deleted=chunks_deleted,
            uploaded_path=uploaded_path,
        )
    def build_upload_only_result(self, *, user_id: str, uploaded_path: str) -> KnowledgeLibraryRebuildResult:
        """构造“仅上传不灌库”的统一返回。"""

        profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        source_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        frontmatter_root = self._resolve_user_frontmatter_dir(normalized_user_id, library_id)
        return KnowledgeLibraryRebuildResult(
            user_id=normalized_user_id,
            library_id=library_id,
            knowledge_dir=str(source_root),
            frontmatter_dir=str(frontmatter_root),
            frontmatter_files_seen=0,
            frontmatter_files_written=0,
            frontmatter_files_skipped=0,
            files_seen=0,
            files_ingested=0,
            files_skipped=0,
            chunks_created=0,
            chunks_deleted=0,
            uploaded_path=uploaded_path,
        )
    def should_auto_ingest_on_upload(self, *, user_id: str) -> bool:
        """返回用户上传后是否自动灌库。默认关闭。"""

        config = self.settings_service.get_knowledge_ingestion_config(user_id=user_id)
        return bool(config.get("auto_ingest_on_upload"))
    def cleanup_ignored_sources(self, *, user_id: str) -> dict[str, int]:
        """按当前屏蔽规则立即删除已入库的屏蔽文件切片和 frontmatter。"""

        profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        source_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        frontmatter_root = self._resolve_user_frontmatter_dir(normalized_user_id, library_id)
        ignore_matcher = self._build_ignore_matcher(user_id=normalized_user_id)
        ignored_paths = [
            self._relative_path(path=path, root=source_root)
            for path in source_root.rglob("*")
            if path.is_file()
            and ignore_matcher.is_ignored(self._relative_path(path=path, root=source_root), is_dir=False)
        ] if source_root.exists() else []
        chunks_deleted = self._delete_index_artifacts(user_id=normalized_user_id, relative_paths=ignored_paths)
        self._delete_ignored_frontmatter_files(
            frontmatter_root=frontmatter_root,
            ignore_matcher=ignore_matcher,
        )
        return {"files_seen": len(ignored_paths), "chunks_deleted": chunks_deleted}
    def ingest_single_file(
        self,
        *,
        user_id: str,
        path: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> KnowledgeLibraryRebuildResult:
        """
        只灌库当前 active 知识库中的单个文件。

        path: 知识库根目录内相对路径。该操作不会清理其他文件对应的向量切片。
        """

        profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        knowledge_owner_id = self.settings_service.build_knowledge_owner_id(
            user_id=normalized_user_id,
            library_id=library_id,
        )
        source_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        source_path = self._resolve_child_path(root=source_root, relative_path=path)
        if not source_path.is_file():
            raise ValueError("file not found")
        frontmatter_root = self._resolve_user_frontmatter_dir(normalized_user_id, library_id)
        markdown_root = self._resolve_user_markdown_dir(normalized_user_id, library_id)
        frontmatter_root.mkdir(parents=True, exist_ok=True)
        markdown_root.mkdir(parents=True, exist_ok=True)
        relative_path = self._relative_path(path=source_path, root=source_root)
        source_id = FrontmatterBootstrapService._build_document_id(Path(relative_path))
        ignore_matcher = self._build_ignore_matcher(user_id=normalized_user_id)
        if ignore_matcher.is_ignored(relative_path, is_dir=False) and not self._is_managed_ingest_source(relative_path):
            self._emit_manual_ingestion_progress(
                progress_callback,
                status="started",
                relative_path=relative_path,
                processed=0,
                total=1,
            )
            frontmatter_path = (frontmatter_root / relative_path).with_suffix(".json").resolve()
            if self._is_relative_to(frontmatter_path, frontmatter_root) and frontmatter_path.exists():
                frontmatter_path.unlink()
            chunks_deleted = self.memory_service.delete_memories_for_source(
                user_id=knowledge_owner_id,
                tag=self.config.constants.knowledge_tag,
                memory_type="knowledge_chunk",
                source_id=source_id,
            )
            self._emit_manual_ingestion_progress(
                progress_callback,
                status="skipped",
                relative_path=relative_path,
                processed=1,
                total=1,
                files_skipped=1,
                chunks_deleted=chunks_deleted,
                message="ignored",
            )
            return KnowledgeLibraryRebuildResult(
                user_id=normalized_user_id,
                library_id=library_id,
                knowledge_dir=str(source_root),
                frontmatter_dir=str(frontmatter_root),
                frontmatter_files_seen=1,
                frontmatter_files_written=0,
                frontmatter_files_skipped=1,
                files_seen=1,
                files_ingested=0,
                files_skipped=1,
                chunks_created=0,
                chunks_deleted=chunks_deleted,
                uploaded_path=str(source_path),
                skip_reason="ignored",
                status_message="文件命中知识库屏蔽规则,已跳过并清理旧索引。",
            )
        if not self._can_ingest_source_file(source_path):
            self._emit_manual_ingestion_progress(
                progress_callback,
                status="started",
                relative_path=relative_path,
                processed=0,
                total=1,
            )
            self._emit_manual_ingestion_progress(
                progress_callback,
                status="skipped",
                relative_path=relative_path,
                processed=1,
                total=1,
                files_skipped=1,
                message="unsupported binary",
            )
            return KnowledgeLibraryRebuildResult(
                user_id=normalized_user_id,
                library_id=library_id,
                knowledge_dir=str(source_root),
                frontmatter_dir=str(frontmatter_root),
                frontmatter_files_seen=1,
                frontmatter_files_written=0,
                frontmatter_files_skipped=1,
                files_seen=1,
                files_ingested=0,
                files_skipped=1,
                chunks_created=0,
                chunks_deleted=0,
                uploaded_path=str(source_path),
                skip_reason="unsupported_binary",
                status_message="unsupported binary file",
            )

        ocr_enabled = self.settings_service.is_ocr_enabled_for_user(user_id=normalized_user_id)
        vlm_config = self.settings_service.get_vlm_config(user_id=normalized_user_id)
        frontmatter_result, frontmatter_path = FrontmatterBootstrapService(
            config=self.config,
            ocr_enabled=ocr_enabled,
            vlm_config=vlm_config,
            online_enabled=bool(vlm_config.get("enabled")),
        ).build_frontmatter_file(
            source_path=source_path,
            knowledge_dir=source_root,
            frontmatter_dir=frontmatter_root,
            markdown_dir=markdown_root,
            supported_suffixes=self.supported_suffixes,
            progress_callback=progress_callback,
        )
        ingestion_result = KnowledgeIngestionService(
            config=self.config,
            embedding_service=self.embedding_service,
            memory_service=self.memory_service,
        ).ingest_frontmatter_file(
            frontmatter_path=frontmatter_path,
            user_id=knowledge_owner_id,
            progress_callback=progress_callback,
        )
        skip_reason, status_message = self._describe_single_file_ingestion_result(
            source_path=source_path,
            frontmatter_path=frontmatter_path,
            files_ingested=ingestion_result.files_ingested,
            chunks_created=ingestion_result.chunks_created,
        )
        if skip_reason:
            logger.warning(
                "单文件灌库未生成切片 | path=%s suffix=%s reason=%s message=%s",
                relative_path,
                source_path.suffix.lower(),
                skip_reason,
                status_message,
            )
        return KnowledgeLibraryRebuildResult(
            user_id=normalized_user_id,
            library_id=library_id,
            knowledge_dir=str(source_root),
            frontmatter_dir=str(frontmatter_root),
            frontmatter_files_seen=frontmatter_result.files_seen,
            frontmatter_files_written=frontmatter_result.files_written,
            frontmatter_files_skipped=frontmatter_result.files_skipped,
            files_seen=ingestion_result.files_seen,
            files_ingested=ingestion_result.files_ingested,
            files_skipped=ingestion_result.files_skipped,
            chunks_created=ingestion_result.chunks_created,
            chunks_deleted=ingestion_result.chunks_deleted,
            uploaded_path=str(source_path),
            skip_reason=skip_reason,
            status_message=status_message,
        )
    def ingest_path(
        self,
        *,
        user_id: str,
        path: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> KnowledgeLibraryRebuildResult:
        """
        灌库文件或文件夹。文件直接灌库,文件夹递归灌入其下所有支持的文件。

        path: 知识库根目录内相对路径。
        """

        profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        source_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        source_path = self._resolve_child_path(root=source_root, relative_path=path)
        if not source_path.exists():
            raise ValueError("path not found")
        if source_path.is_file():
            return self.ingest_single_file(user_id=user_id, path=path, progress_callback=progress_callback)
        ignore_matcher = self._build_ignore_matcher(user_id=normalized_user_id)
        file_paths = sorted(
            p
            for p in source_path.rglob("*")
            if p.is_file()
            and self._can_ingest_source_file(p)
            and not ignore_matcher.is_ignored(self._relative_path(path=p, root=source_root), is_dir=False)
        )
        if not file_paths:
            return KnowledgeLibraryRebuildResult(
                user_id=normalized_user_id,
                library_id=library_id,
                knowledge_dir=str(source_root),
                frontmatter_dir=str(self._resolve_user_frontmatter_dir(normalized_user_id, library_id)),
                frontmatter_files_seen=0,
                frontmatter_files_written=0,
                frontmatter_files_skipped=0,
                files_seen=0,
                files_ingested=0,
                files_skipped=0,
                chunks_created=0,
                chunks_deleted=0,
                uploaded_path=str(source_path),
                skip_reason="no_supported_files",
                status_message="该文件夹中没有可灌库的知识文件。",
            )
        agg = KnowledgeLibraryRebuildResult(
            user_id=normalized_user_id,
            library_id=library_id,
            knowledge_dir=str(source_root),
            frontmatter_dir=str(self._resolve_user_frontmatter_dir(normalized_user_id, library_id)),
            frontmatter_files_seen=0,
            frontmatter_files_written=0,
            frontmatter_files_skipped=0,
            files_seen=0,
            files_ingested=0,
            files_skipped=0,
            chunks_created=0,
            chunks_deleted=0,
        )
        for file_index, fp in enumerate(file_paths):
            relative = self._relative_path(path=fp, root=source_root)

            def scoped_progress(payload: dict[str, Any], *, index: int = file_index) -> None:
                if not progress_callback:
                    return
                next_payload = dict(payload)
                next_payload["total"] = len(file_paths)
                next_payload["processed"] = index + (1 if int(payload.get("processed") or 0) > 0 else 0)
                progress_callback(next_payload)

            try:
                result = self.ingest_single_file(user_id=user_id, path=relative, progress_callback=scoped_progress)
                agg.frontmatter_files_seen += result.frontmatter_files_seen
                agg.frontmatter_files_written += result.frontmatter_files_written
                agg.frontmatter_files_skipped += result.frontmatter_files_skipped
                agg.files_seen += result.files_seen
                agg.files_ingested += result.files_ingested
                agg.files_skipped += result.files_skipped
                agg.chunks_created += result.chunks_created
                agg.chunks_deleted += result.chunks_deleted
            except Exception:
                logger.exception("灌库文件失败 | path=%s", relative)
                agg.files_skipped += 1
                self._emit_manual_ingestion_progress(
                    progress_callback,
                    status="failed",
                    relative_path=relative,
                    processed=file_index + 1,
                    total=len(file_paths),
                    files_skipped=agg.files_skipped,
                    message="file ingestion failed",
                )
        agg.status_message = f"文件夹灌库完成,共 {agg.files_ingested} 个文件入库,{agg.chunks_created} 个切片。"
        return agg
    @staticmethod
    def _emit_manual_ingestion_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        status: str,
        relative_path: str,
        processed: int,
        total: int,
        files_ingested: int = 0,
        files_skipped: int = 0,
        chunks_created: int = 0,
        chunks_deleted: int = 0,
        message: str = "",
    ) -> None:
        if not progress_callback:
            return
        normalized_path = relative_path.replace("\\", "/").strip("/")
        payload: dict[str, Any] = {
            "phase": "ingestion",
            "status": status,
            "path": normalized_path,
            "name": Path(normalized_path).name,
            "processed": processed,
            "total": total,
            "files_ingested": files_ingested,
            "files_skipped": files_skipped,
            "chunks_created": chunks_created,
            "chunks_deleted": chunks_deleted,
        }
        if message:
            payload["message"] = message
        progress_callback(payload)
    def _describe_single_file_ingestion_result(
        self,
        *,
        source_path: Path,
        frontmatter_path: Path,
        files_ingested: int,
        chunks_created: int,
    ) -> tuple[str, str]:
        """根据单文件 frontmatter 和入库统计生成跳过原因。"""

        if files_ingested > 0:
            return "", ""
        try:
            payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "no_chunks", "文件已结构化,但没有生成可入库切片。"
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        sections = payload.get("sections", []) if isinstance(payload, dict) else []
        if files_ingested <= 0 and chunks_created <= 0 and isinstance(sections, list) and sections:
            return "unchanged", "文件内容未变化,已有索引已保持不变。"
        if source_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ocr_status = str(metadata.get("ocr_status") or "")
            if ocr_status == "no_text":
                return "ocr_no_text", "图片已处理,但 OCR 未识别到可入库文字。"
            if ocr_status == "engine_unavailable":
                return "ocr_engine_unavailable", "图片需要 OCR,但当前 OCR 引擎不可用。"
            if ocr_status == "disabled":
                return "ocr_disabled", "图片需要 OCR,但当前用户未启用 OCR。"
            if chunks_created <= 0:
                return "ocr_no_chunks", "图片已 OCR,但识别结果没有形成可入库切片。"
        if chunks_created <= 0:
            return "no_chunks", "文件已处理,但没有生成可入库文本切片。"
        return "", ""
    def _build_ignore_matcher(self, *, user_id: str) -> KnowledgeIgnoreMatcher:
        """从用户设置构造知识库屏蔽规则匹配器。"""

        config = self.settings_service.get_knowledge_ingestion_config(user_id=user_id)
        return KnowledgeIgnoreMatcher(str(config.get("knowledge_ignore_patterns") or ""))
    def _can_ingest_source_file(self, path: Path) -> bool:
        """Return whether a file can enter the knowledge ingestion pipeline."""

        return FrontmatterBootstrapService._can_structure_source_file(path, self.supported_suffixes)
    def _delete_ignored_frontmatter_files(
        self,
        *,
        frontmatter_root: Path,
        ignore_matcher: KnowledgeIgnoreMatcher,
    ) -> None:
        """删除已被屏蔽规则命中的旧 frontmatter JSON,确保后续入库扫描看不到它们。"""

        if not frontmatter_root.exists():
            return
        for frontmatter_path in sorted(frontmatter_root.rglob("*.json")):
            if not frontmatter_path.is_file():
                continue
            try:
                payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            relative_path = str(metadata.get("relative_path") or "")
            if (
                relative_path
                and ignore_matcher.is_ignored(relative_path, is_dir=False)
                and not self._is_managed_ingest_source(relative_path)
            ):
                frontmatter_path.unlink(missing_ok=True)
    @staticmethod
    def _is_managed_ingest_source(relative_path: str) -> bool:
        """Allow smart-form literature assets through their explicit ingestion entry only."""

        parts = relative_path.replace("\\", "/").strip("/").split("/")
        return len(parts) >= 5 and parts[:2] == [".mw", "forms"] and "assets" in parts[2:-1]
    def _managed_ingest_source_ids(self, frontmatter_root: Path) -> set[str]:
        """Collect explicitly ingested managed assets so a normal full rebuild preserves them."""

        source_ids: set[str] = set()
        if not frontmatter_root.is_dir():
            return source_ids
        for path in frontmatter_root.rglob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            relative_path = str(payload.get("metadata", {}).get("relative_path") or "")
            if self._is_managed_ingest_source(relative_path):
                source_ids.add(str(payload.get("document_id") or ""))
        return {source_id for source_id in source_ids if source_id}
    def invalidate_paths(self, *, user_id: str, relative_paths: list[str]) -> dict[str, int]:
        """
        使一组知识库来源文件的全部派生索引失效。

        relative_paths: 文件或目录相对于当前 active 知识库根目录的路径。目录已经
        被外部删除时,仍会从保留在 runtime/frontmatter 中的元数据恢复其原文件清单。

        返回值包含实际失效的来源文件数和删除的向量切片数。调用方完成文件变更后
        应刷新文件树,新内容保持 dirty 状态,等待显式重新入库与图谱抽取。
        """

        context = self._active_library_context(user_id=user_id)
        root = context["root"]
        frontmatter_root = self._resolve_user_frontmatter_dir(
            context["user_id"],
            context["library_id"],
        ).resolve()
        affected: set[str] = set()
        ignore_matcher = self._build_ignore_matcher(user_id=context["user_id"])
        for raw_path in relative_paths:
            normalized_path = str(raw_path or "").replace("\\", "/").strip("/")
            if not normalized_path:
                continue
            target = self._resolve_child_path(root=root, relative_path=normalized_path)
            if ignore_matcher.is_ignored(normalized_path, is_dir=target.is_dir()):
                continue
            if target.is_dir():
                affected.update(self._collect_relative_file_paths(target=target, root=root))
            elif target.is_file():
                affected.add(normalized_path)
            else:
                affected.update(
                    self._frontmatter_sources_under_prefix(
                        frontmatter_root=frontmatter_root,
                        relative_prefix=normalized_path,
                    )
                )
                if Path(normalized_path).suffix:
                    affected.add(normalized_path)
        normalized_affected = sorted(path for path in affected if path)
        chunks_deleted = self._delete_index_artifacts(
            user_id=user_id,
            relative_paths=normalized_affected,
        )
        return {
            "files_invalidated": len(normalized_affected),
            "chunks_deleted": chunks_deleted,
        }
    @staticmethod
    def _frontmatter_sources_under_prefix(
        *,
        frontmatter_root: Path,
        relative_prefix: str,
    ) -> set[str]:
        """
        从 frontmatter 元数据恢复已被外部删除或移动的来源路径。

        该方法只读取 runtime 内的 JSON 元数据,不会信任 JSON 提供的绝对路径。
        """

        if not frontmatter_root.is_dir():
            return set()
        prefix = relative_prefix.replace("\\", "/").strip("/")
        matched: set[str] = set()
        for frontmatter_path in frontmatter_root.rglob("*.json"):
            try:
                payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            source_path = str(metadata.get("relative_path") or "").replace("\\", "/").strip("/")
            if source_path == prefix or source_path.startswith(f"{prefix}/"):
                matched.add(source_path)
        return matched
    def _source_needs_ocr_reindex(
        self,
        *,
        source_path: Path,
        relative_path: str,
        frontmatter_root: Path,
    ) -> bool:
        """判断 OCR 开启后当前文件的旧 frontmatter 是否需要重建。"""

        if not self._source_may_contain_images(source_path):
            return False
        frontmatter_path = (frontmatter_root / relative_path).with_suffix(".json").resolve()
        if not self._is_relative_to(frontmatter_path, frontmatter_root) or not frontmatter_path.is_file():
            return True
        try:
            payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
        except Exception:
            return True
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        return not bool(metadata.get("ocr_enabled"))
    @staticmethod
    def _source_may_contain_images(source_path: Path) -> bool:
        """快速判断文件是否可能需要 OCR 重新结构化。"""

        suffix = source_path.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf"}:
            return True
        media_prefixes = {
            ".docx": "word/media/",
            ".pptx": "ppt/media/",
            ".xlsx": "xl/media/",
        }
        media_prefix = media_prefixes.get(suffix)
        if not media_prefix:
            return False
        try:
            with zipfile.ZipFile(source_path) as archive:
                return any(name.startswith(media_prefix) for name in archive.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
