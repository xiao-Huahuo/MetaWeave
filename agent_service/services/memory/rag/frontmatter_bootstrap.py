"""
知识源结构化预处理服务。
功能说明:
本文件负责把知识库原始文件先转换为统一 Markdown,再派生结构化知识 JSON,
分别输出到知识库 `.mw/md` 和 `.mw/frontmatter`。它只做文档理解、元数据拆分和章节结构化,不负责切块、Embedding
或入库。后续 `knowledge_bootstrap` 只消费这里生成的 JSON。
使用说明:
service = FrontmatterBootstrapService(config=config)
result = service.build_frontmatter_dir()
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS

logger = logging.getLogger(__name__)
from agent_service.services.memory.rag.frontmatter_document import (
    StructuredKnowledgeDocument,
    StructuredKnowledgeSection,
)
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.services.memory.rag.multimodal_cleaner import MultimodalDocumentCleaner

TEXT_FALLBACK_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030")
DOCX_IMAGE_REFERENCE_RE = re.compile(r"\[DOCX 图片引用:\s*([^\]]+)\]")


@dataclass(slots=True)
class FrontmatterBootstrapResult:
    """
    结构化预处理结果。
    files_seen: 扫描到的原始知识文件数量。
    files_written: 实际写出的结构化 JSON 数量。
    files_skipped: 因内容未变化而跳过覆写的结构化 JSON 数量。
    """

    files_seen: int = 0
    files_written: int = 0
    files_skipped: int = 0


class FrontmatterBootstrapService:
    """
    原始知识源结构化服务。
    config: 全局配置对象,用于读取原始知识目录和结构化输出目录。
    """

    def __init__(self, *, config: AgentConfig, ocr_enabled: bool | None = None, ocr_inline: bool = False) -> None:
        """初始化原始知识源结构化服务。"""

        self.config = config
        self.ocr_enabled = config.ocr.enabled if ocr_enabled is None else bool(ocr_enabled)
        self.multimodal_cleaner = MultimodalDocumentCleaner(
            config=config,
            ocr_enabled=self.ocr_enabled,
            image_ocr_service=ImageOcrService(config=config, enabled=self.ocr_enabled, run_inline=ocr_inline) if self.ocr_enabled else None,
        )

    def build_frontmatter_dir(
        self,
        *,
        knowledge_dir: Path | None = None,
        frontmatter_dir: Path | None = None,
        markdown_dir: Path | None = None,
        supported_suffixes: set[str] | None = None,
        exclude_path: Callable[[Path], bool] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> FrontmatterBootstrapResult:
        """
        扫描原始知识目录并输出结构化 JSON。
        knowledge_dir: 可选原始知识库目录;为空时使用全局配置。
        frontmatter_dir: 可选结构化输出目录;为空时使用全局配置。
        supported_suffixes: 可选文件后缀白名单;为 None 时使用 {".md", ".txt"}。
        返回值仅描述结构化阶段,不包含后续灌库统计。
        """

        source_root = knowledge_dir or self.config.storage.knowledge_dir
        output_root = frontmatter_dir or source_root / ".mw" / "frontmatter"
        markdown_root = markdown_dir or source_root / ".mw" / "md"
        suffixes = supported_suffixes or set(self.config.constants.knowledge_supported_suffixes)
        result = FrontmatterBootstrapResult()
        source_files = [
            path for path in self._iter_source_files(source_root, suffixes)
            if not (exclude_path and exclude_path(path))
        ]
        logger.info("Frontmatter 结构化开始 | 扫描到 %d 个文件", len(source_files))
        total = len(source_files)
        for source_path in source_files:
            result.files_seen += 1
            rel_path = source_path.relative_to(source_root)
            self._emit_progress(
                progress_callback,
                status="started",
                source_path=source_path,
                relative_path=rel_path,
                processed=result.files_seen - 1,
                total=total,
                result=result,
            )
            try:
                source_hash = self._hash_file(source_path)
                document = self._build_document(
                    source_path=source_path,
                    source_hash=source_hash,
                    knowledge_dir=source_root,
                )
                output_path = self._resolve_output_path(
                    source_path=source_path,
                    knowledge_dir=source_root,
                    frontmatter_dir=output_root,
                )
                markdown_path = self._resolve_markdown_path(
                    source_path=source_path,
                    knowledge_dir=source_root,
                    markdown_dir=markdown_root,
                )
                markdown_path.parent.mkdir(parents=True, exist_ok=True)
                markdown_path.write_text(document.markdown, encoding="utf-8")
                output_payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if output_path.exists() and output_path.read_text(encoding="utf-8") == output_payload:
                    result.files_skipped += 1
                    self._emit_progress(
                        progress_callback,
                        status="skipped",
                        source_path=source_path,
                        relative_path=rel_path,
                        processed=result.files_seen,
                        total=total,
                        result=result,
                        message="frontmatter unchanged",
                    )
                    logger.debug("  [跳过] %s (未变更)", rel_path)
                    continue
                output_path.write_text(output_payload, encoding="utf-8")
                result.files_written += 1
                self._emit_progress(
                    progress_callback,
                    status="written",
                    source_path=source_path,
                    relative_path=rel_path,
                    processed=result.files_seen,
                    total=total,
                    result=result,
                    sections=len(document.sections),
                )
                logger.info("  [写入] %s → %d sections", rel_path, len(document.sections))
            except Exception as exc:
                result.files_skipped += 1
                self._emit_progress(
                    progress_callback,
                    status="failed",
                    source_path=source_path,
                    relative_path=rel_path,
                    processed=result.files_seen,
                    total=total,
                    result=result,
                    message=str(exc),
                )
                logger.warning("  [跳过] %s (结构化失败: %s)", rel_path, exc)
        logger.info(
            "Frontmatter 结构化完成 | %d 文件: %d 写入, %d 跳过",
            result.files_seen,
            result.files_written,
            result.files_skipped,
        )
        return result

    def build_frontmatter_file(
        self,
        *,
        source_path: Path,
        knowledge_dir: Path | None = None,
        frontmatter_dir: Path | None = None,
        markdown_dir: Path | None = None,
        supported_suffixes: set[str] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[FrontmatterBootstrapResult, Path]:
        """
        只结构化单个源文件。

        source_path: 原始知识文件绝对路径或相对路径。
        knowledge_dir: 当前知识库根目录。
        frontmatter_dir: 结构化 JSON 输出根目录。
        supported_suffixes: 可灌库后缀白名单。
        """

        source_root = (knowledge_dir or self.config.storage.knowledge_dir).resolve()
        output_root = frontmatter_dir or source_root / ".mw" / "frontmatter"
        markdown_root = markdown_dir or source_root / ".mw" / "md"
        suffixes = supported_suffixes or set(self.config.constants.knowledge_supported_suffixes)
        resolved_source = source_path.expanduser().resolve()
        result = FrontmatterBootstrapResult(files_seen=1)
        if not resolved_source.is_file():
            raise ValueError("source file not found")
        if not self._can_structure_source_file(resolved_source, suffixes):
            raise ValueError(f"unsupported binary knowledge file suffix: {resolved_source.suffix.lower()}")
        try:
            relative_path = resolved_source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("source file escapes knowledge_dir") from exc
        self._emit_progress(
            progress_callback,
            status="started",
            source_path=resolved_source,
            relative_path=relative_path,
            processed=0,
            total=1,
            result=result,
        )

        self._emit_stage_progress(
            progress_callback,
            relative_path=relative_path,
            stage="hash",
            stage_label="正在计算文件指纹",
            overall_progress=2,
        )
        source_hash = self._hash_file(resolved_source)
        document = self._build_document(
            source_path=resolved_source,
            source_hash=source_hash,
            knowledge_dir=source_root,
            progress_callback=progress_callback,
        )
        output_path = self._resolve_output_path(
            source_path=resolved_source,
            knowledge_dir=source_root,
            frontmatter_dir=output_root,
        )
        markdown_path = self._resolve_markdown_path(
            source_path=resolved_source,
            knowledge_dir=source_root,
            markdown_dir=markdown_root,
        )
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(document.markdown, encoding="utf-8")
        output_payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._emit_stage_progress(
            progress_callback,
            relative_path=relative_path,
            stage="frontmatter",
            stage_label=f"正在写入结构化正文，共 {len(document.sections)} 个章节",
            overall_progress=50,
            current=len(document.sections),
            total=len(document.sections),
        )
        if output_path.exists() and output_path.read_text(encoding="utf-8") == output_payload:
            result.files_skipped = 1
            self._emit_progress(
                progress_callback,
                status="skipped",
                source_path=resolved_source,
                relative_path=relative_path,
                processed=1,
                total=1,
                result=result,
                message="frontmatter unchanged",
            )
            return result, output_path
        output_path.write_text(output_payload, encoding="utf-8")
        result.files_written = 1
        self._emit_progress(
            progress_callback,
            status="written",
            source_path=resolved_source,
            relative_path=relative_path,
            processed=1,
            total=1,
            result=result,
            sections=len(document.sections),
        )
        return result, output_path

    def build_markdown_projection(
        self,
        *,
        source_path: Path,
        knowledge_dir: Path,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> StructuredKnowledgeDocument:
        """Build the reusable pre-embedding Markdown projection for one source.

        Scanner and ingestion callers share the same parsing implementation;
        scanner callers may select a task-local asset directory and stop before
        frontmatter persistence, chunking, and embedding.
        """

        resolved_source = source_path.expanduser().resolve()
        resolved_root = knowledge_dir.expanduser().resolve()
        try:
            relative_path = resolved_source.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("source file escapes knowledge_dir") from exc
        if not resolved_source.is_file():
            raise ValueError("source file not found")
        return self._build_document(
            source_path=resolved_source,
            source_hash=self._hash_file(resolved_source),
            knowledge_dir=resolved_root,
            progress_callback=progress_callback,
            asset_output_dir=asset_output_dir,
            asset_public_prefix=asset_public_prefix,
        )

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        status: str,
        source_path: Path,
        relative_path: Path,
        processed: int,
        total: int,
        result: FrontmatterBootstrapResult,
        message: str = "",
        sections: int | None = None,
    ) -> None:
        if not progress_callback:
            return
        payload: dict[str, Any] = {
            "phase": "frontmatter",
            "status": status,
            "path": relative_path.as_posix(),
            "name": source_path.name,
            "processed": processed,
            "total": total,
            "files_written": result.files_written,
            "files_skipped": result.files_skipped,
        }
        if message:
            payload["message"] = message
        if sections is not None:
            payload["sections"] = sections
        progress_callback(payload)

    @staticmethod
    def _emit_stage_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        relative_path: Path,
        stage: str,
        stage_label: str,
        overall_progress: int,
        current: int = 0,
        total: int = 0,
    ) -> None:
        """发送单文件结构化阶段的可读细节与总进度。"""

        if not progress_callback:
            return
        progress_callback({
            "phase": "frontmatter",
            "status": "processing",
            "path": relative_path.as_posix(),
            "name": relative_path.name,
            "stage": stage,
            "stage_label": stage_label,
            "stage_current": current,
            "stage_total": total,
            "overall_progress": overall_progress,
        })

    def _build_document(
        self,
        *,
        source_path: Path,
        source_hash: str,
        knowledge_dir: Path,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> StructuredKnowledgeDocument:
        """
        将单个原始知识文件转换为统一结构化文档。
        source_path: 原始知识文件路径。
        source_hash: 原始知识文件内容哈希。
        knowledge_dir: 当前知识库根目录。
        """

        metadata: dict[str, Any] = {}
        relative_path = source_path.relative_to(knowledge_dir)
        title = self._resolve_title(source_path=source_path, metadata=metadata)
        if source_path.suffix.lower() == ".md":
            raw_text = self._read_text_with_fallback(source_path)
            self._emit_stage_progress(
                progress_callback,
                relative_path=relative_path,
                stage="read_text",
                stage_label="Markdown 正文读取完成",
                overall_progress=18,
                current=source_path.stat().st_size,
                total=source_path.stat().st_size,
            )
            metadata, body_text = self._extract_frontmatter(raw_text)
            title = self._resolve_title(source_path=source_path, metadata=metadata)
            sections = self._build_sections(source_path=source_path, title=title, body_text=body_text)
            self._emit_stage_progress(
                progress_callback,
                relative_path=relative_path,
                stage="parse_sections",
                stage_label=f"Markdown 标题解析完成，共 {len(sections)} 个章节",
                overall_progress=42,
                current=len(sections),
                total=len(sections),
            )
            source_type = self._resolve_source_type(source_path)
            extra_metadata: dict[str, Any] = {"modality": "document"}
            summary = str(metadata.get("summary") or "")
        elif source_path.suffix.lower() in {".txt", ".tex"} or source_path.suffix.lower() not in self.config.constants.knowledge_supported_suffixes:
            body_text = self._read_text_with_fallback(source_path)
            self._emit_stage_progress(
                progress_callback,
                relative_path=relative_path,
                stage="read_text",
                stage_label="文本正文读取完成",
                overall_progress=30,
                current=source_path.stat().st_size,
                total=source_path.stat().st_size,
            )
            sections = self._build_sections(source_path=source_path, title=title, body_text=body_text)
            source_type = self._resolve_source_type(source_path)
            extra_metadata = {"modality": "text"}
            summary = ""
        else:
            asset_relative_dir = Path(".mw") / "assets" / relative_path
            effective_asset_output_dir = asset_output_dir or knowledge_dir / asset_relative_dir
            effective_asset_public_prefix = asset_public_prefix or "/" + asset_relative_dir.as_posix()
            cleaned = self.multimodal_cleaner.clean(
                source_path=source_path,
                title=self._resolve_title(source_path=source_path, metadata=metadata),
                asset_output_dir=effective_asset_output_dir,
                asset_public_prefix=effective_asset_public_prefix,
                progress_callback=lambda payload: progress_callback({
                    **payload,
                    "path": relative_path.as_posix(),
                    "name": source_path.name,
                }) if progress_callback else None,
            )
            sections = cleaned.sections
            source_type = cleaned.source_type
            extra_metadata = cleaned.metadata
            embedded_assets = self._extract_embedded_assets(
                source_path=source_path,
                output_dir=effective_asset_output_dir,
                public_prefix=effective_asset_public_prefix,
            )
            if embedded_assets:
                extra_metadata["embedded_assets"] = embedded_assets
                inlined_asset_urls = (
                    self._inline_docx_images(sections, embedded_assets)
                    if source_path.suffix.lower() == ".docx"
                    else set()
                )
                links = "\n".join(
                    f"![{asset['name']}]({asset['public_url']})"
                    for asset in embedded_assets
                    if asset["public_url"] not in inlined_asset_urls
                )
                if links:
                    sections.append(
                        StructuredKnowledgeSection(
                            section_id=f"sec_{len(sections):04d}",
                            heading="内置图片",
                            title_path=[title, "内置图片"],
                            content=links,
                            start_char=0,
                            end_char=len(links),
                        )
                    )
            summary = cleaned.summary
        markdown = self._build_canonical_markdown(title=title, source_type=source_type, sections=sections)
        sections = self._build_markdown_sections(title=title, body_text=markdown)
        document_metadata = {
            "file_suffix": source_path.suffix.lower(),
            "relative_path": relative_path.as_posix(),
            "frontmatter": metadata,
            **extra_metadata,
            "ocr_enabled": self.ocr_enabled,
        }
        assets = [
            dict(item)
            for key in ("image_refs", "embedded_assets")
            for item in document_metadata.get(key, [])
            if isinstance(item, dict)
        ]
        projection_payload = {
            "schema_version": 2,
            "source_type": source_type,
            "markdown": markdown,
            "metadata": document_metadata,
            "assets": assets,
        }
        projection_hash = hashlib.sha256(
            json.dumps(projection_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return StructuredKnowledgeDocument(
            document_id=self._build_document_id(relative_path),
            source_type=source_type,
            source_path=str(source_path),
            source_uri=str(metadata.get("source_uri") or source_path),
            source_hash=source_hash,
            title=title,
            summary=summary,
            tags=self._normalize_tags(metadata.get("tags")),
            authority=self._parse_float(metadata.get("authority"), default=0.7),
            valid_from=self._normalize_optional_string(metadata.get("valid_from")),
            valid_until=self._normalize_optional_string(metadata.get("valid_until")),
            metadata=document_metadata,
            sections=sections,
            schema_version=2,
            markdown=markdown,
            projection_hash=projection_hash,
            assets=assets,
            source_map=[
                {
                    "section_id": section.section_id,
                    "source_path": relative_path.as_posix(),
                    "start_char": section.start_char,
                    "end_char": section.end_char,
                }
                for section in sections
            ],
        )

    @staticmethod
    def _build_canonical_markdown(
        *,
        title: str,
        source_type: str,
        sections: list[StructuredKnowledgeSection],
    ) -> str:
        """Serialize every cleaned modality into the canonical Markdown projection."""

        parts = [f"# {title}"]
        for section in sections:
            content = section.content.strip()
            if source_type == "table" or " 表格 " in section.heading:
                rows = [line.split(" | ") for line in content.splitlines() if line.strip()]
                if rows:
                    width = max(len(row) for row in rows)
                    padded = [row + [""] * (width - len(row)) for row in rows]
                    table_lines = ["| " + " | ".join(row) + " |" for row in padded]
                    table_lines.insert(1, "| " + " | ".join("---" for _ in range(width)) + " |")
                    content = "\n".join(table_lines)
            if not content:
                continue
            heading = section.heading.strip()
            if heading and heading != title:
                depth = max(2, min(6, len(section.title_path) + 1))
                parts.append(f"{'#' * depth} {heading}")
            parts.append(content)
        return "\n\n".join(parts).strip() + "\n"

    @staticmethod
    def _extract_embedded_assets(
        *,
        source_path: Path,
        output_dir: Path,
        public_prefix: str,
    ) -> list[dict[str, Any]]:
        """Persist OOXML embedded images beside the Markdown/JSON projections."""

        media_prefix = {
            ".docx": "word/media/",
            ".pptx": "ppt/media/",
            ".xlsx": "xl/media/",
        }.get(source_path.suffix.lower())
        if not media_prefix:
            return []
        assets: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(source_path) as archive:
                names = sorted(
                    name for name in archive.namelist()
                    if name.startswith(media_prefix) and not name.endswith("/")
                )
                for index, archive_name in enumerate(names, start=1):
                    filename = Path(archive_name).name
                    target = output_dir / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(archive_name))
                    assets.append(
                        {
                            "index": index,
                            "name": filename,
                            "archive_path": archive_name,
                            "asset_path": str(target),
                            "public_url": f"{public_prefix}/{filename}",
                        }
                    )
        except (OSError, zipfile.BadZipFile):
            return []
        return assets

    @staticmethod
    def _inline_docx_images(
        sections: list[StructuredKnowledgeSection],
        embedded_assets: list[dict[str, Any]],
    ) -> set[str]:
        """Replace DOCX relationship placeholders with their extracted image nodes."""

        assets_by_reference: dict[str, dict[str, Any]] = {}
        for asset in embedded_assets:
            archive_path = str(asset.get("archive_path") or "").replace("\\", "/").lstrip("/")
            assets_by_reference[archive_path] = asset
            assets_by_reference[archive_path.removeprefix("word/")] = asset
        used_urls: set[str] = set()

        def replace_reference(match: re.Match[str]) -> str:
            reference = match.group(1).strip().replace("\\", "/").lstrip("/")
            asset = assets_by_reference.get(reference) or assets_by_reference.get(f"word/{reference}")
            if not asset:
                return match.group(0)
            public_url = str(asset["public_url"])
            used_urls.add(public_url)
            return f"![{asset['name']}]({public_url})"

        for section in sections:
            section.content = DOCX_IMAGE_REFERENCE_RE.sub(replace_reference, section.content)
            section.end_char = section.start_char + len(section.content)
        return used_urls

    def _build_sections(
        self,
        *,
        source_path: Path,
        title: str,
        body_text: str,
    ) -> list[StructuredKnowledgeSection]:
        """
        根据原始文件类型提取结构化章节。
        source_path: 原始知识文件路径。
        title: 文档标题。
        body_text: frontmatter 剥离后的正文。
        """

        if source_path.suffix.lower() == ".md":
            return self._build_markdown_sections(title=title, body_text=body_text)
        return self._build_text_sections(title=title, body_text=body_text)

    @staticmethod
    def _build_markdown_sections(*, title: str, body_text: str) -> list[StructuredKnowledgeSection]:
        """
        从 Markdown 正文中提取标题层级和章节内容。
        title: 文档标题。
        body_text: 已去除 frontmatter 的 Markdown 正文。
        """

        sections: list[StructuredKnowledgeSection] = []
        heading_stack: list[tuple[int, str]] = []
        current_heading = title
        current_title_path = [title]
        current_start = 0
        current_content_lines: list[str] = []
        current_cursor = 0

        def flush_section(end_char: int) -> None:
            content = "".join(current_content_lines).strip()
            if not content:
                return
            section_index = len(sections)
            sections.append(
                StructuredKnowledgeSection(
                    section_id=f"sec_{section_index:04d}",
                    heading=current_heading,
                    title_path=list(current_title_path),
                    content=content,
                    start_char=current_start,
                    end_char=end_char,
                )
            )

        for raw_line in body_text.splitlines(keepends=True):
            heading_match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", raw_line.strip("\n"))
            if heading_match:
                flush_section(current_cursor)
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                heading_stack = [(stack_level, stack_heading) for stack_level, stack_heading in heading_stack if stack_level < level]
                heading_stack.append((level, heading_text))
                current_heading = heading_text
                current_title_path = [title, *[stack_heading for _, stack_heading in heading_stack]]
                current_content_lines = []
                current_start = current_cursor + len(raw_line)
                current_cursor += len(raw_line)
                continue
            current_content_lines.append(raw_line)
            current_cursor += len(raw_line)

        flush_section(current_cursor)
        if sections:
            return sections
        content = body_text.strip()
        if not content:
            return []
        return [
            StructuredKnowledgeSection(
                section_id="sec_0000",
                heading=title,
                title_path=[title],
                content=content,
                start_char=0,
                end_char=len(body_text),
            )
        ]

    @staticmethod
    def _build_text_sections(*, title: str, body_text: str) -> list[StructuredKnowledgeSection]:
        """
        从 TXT 正文中提取结构化章节。
        title: 文档标题。
        body_text: TXT 正文。
        """

        content = body_text.strip()
        if not content:
            return []
        return [
            StructuredKnowledgeSection(
                section_id="sec_0000",
                heading=title,
                title_path=[title],
                content=content,
                start_char=0,
                end_char=len(body_text),
            )
        ]

    @staticmethod
    def _extract_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
        """
        从 Markdown 中提取最前部 frontmatter。
        raw_text: 原始 Markdown 文本。
        """

        if not raw_text.startswith("---\n"):
            return {}, raw_text
        lines = raw_text.splitlines()
        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            return {}, raw_text
        frontmatter_lines = lines[1:end_index]
        body_text = "\n".join(lines[end_index + 1 :])
        return FrontmatterBootstrapService._parse_frontmatter_lines(frontmatter_lines), body_text

    @staticmethod
    def _parse_frontmatter_lines(lines: list[str]) -> dict[str, Any]:
        """
        解析简单 YAML 风格 frontmatter。
        lines: frontmatter 正文行列表。
        """

        payload: dict[str, Any] = {}
        current_list_key: str | None = None
        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- ") and current_list_key:
                payload.setdefault(current_list_key, []).append(stripped[2:].strip())
                continue
            if ":" not in line:
                current_list_key = None
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_value:
                payload[normalized_key] = []
                current_list_key = normalized_key
                continue
            payload[normalized_key] = normalized_value
            current_list_key = None
        return payload

    @staticmethod
    def _resolve_title(*, source_path: Path, metadata: dict[str, Any]) -> str:
        """
        解析文档标题。
        source_path: 原始知识文件路径。
        metadata: frontmatter 元数据。
        """

        return str(metadata.get("title") or source_path.stem.replace("_", " ").strip())

    @staticmethod
    def _resolve_source_type(source_path: Path) -> str:
        """
        推断原始知识源类型。
        source_path: 原始知识文件路径。
        """

        if source_path.suffix.lower() == ".md":
            return "markdown"
        return "text"

    @staticmethod
    def _read_text_with_fallback(source_path: Path) -> str:
        """Read a likely-text source with common local encodings before replacing invalid bytes."""

        for encoding in TEXT_FALLBACK_ENCODINGS:
            try:
                return source_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return source_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _normalize_tags(raw_tags: Any) -> list[str]:
        """
        归一化 tags 字段。
        raw_tags: frontmatter 中的 tags 原始值。
        """

        if raw_tags is None:
            return []
        if isinstance(raw_tags, list):
            return [str(item).strip() for item in raw_tags if str(item).strip()]
        if isinstance(raw_tags, str):
            return [item.strip() for item in raw_tags.split(",") if item.strip()]
        return [str(raw_tags).strip()]

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        """
        将可选值归一化为字符串或 None。
        value: 原始 frontmatter 值。
        """

        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _parse_float(value: Any, *, default: float) -> float:
        """
        解析浮点数字段。
        value: 原始 frontmatter 值。
        default: 解析失败时返回的默认值。
        """

        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _resolve_output_path(
        self,
        *,
        source_path: Path,
        knowledge_dir: Path,
        frontmatter_dir: Path,
    ) -> Path:
        """
        根据原始知识源路径计算结构化 JSON 输出路径。
        source_path: 原始知识文件路径。
        knowledge_dir: 当前知识库根目录。
        frontmatter_dir: 当前结构化输出目录。
        """

        relative_path = source_path.relative_to(knowledge_dir)
        return (frontmatter_dir / relative_path).with_suffix(".json")

    @staticmethod
    def _resolve_markdown_path(*, source_path: Path, knowledge_dir: Path, markdown_dir: Path) -> Path:
        """Resolve the mirrored Markdown projection path for a source file."""

        relative_path = source_path.relative_to(knowledge_dir)
        return (markdown_dir / relative_path).with_suffix(".md")

    @staticmethod
    def _build_document_id(relative_path: Path) -> str:
        """
        根据相对路径构建稳定文档 ID。
        relative_path: 原始知识文件相对知识库根目录的路径。
        """

        normalized_path = relative_path.as_posix()
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalized_path).strip("_").lower()
        path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:DEFAULT_BUSINESS_LIMITS.generated_id_suffix_chars]
        if not slug:
            slug = "file"
        return f"doc_{slug}_{path_hash}"

    def _iter_source_files(self, knowledge_dir: Path, suffixes: set[str]) -> list[Path]:
        """
        扫描可结构化的原始知识文件。
        knowledge_dir: 原始知识库根目录。
        suffixes: 文件后缀白名单,例如 {".md", ".txt"}。
                  请确保与 AgentConfig.constants.knowledge_supported_suffixes 保持一致;
                  添加新格式(如 .pdf)时需在此处加入对应的文档解析分支。
        """

        if not knowledge_dir.exists():
            return []
        return sorted(
            path
            for path in knowledge_dir.rglob("*")
            if path.is_file() and self._can_structure_source_file(
                path,
                suffixes,
                sample_size=self.config.limits.frontmatter_binary_sample_bytes,
                control_char_ratio=self.config.limits.frontmatter_control_char_ratio,
            )
        )

    @staticmethod
    def _can_structure_source_file(
        path: Path,
        suffixes: set[str],
        *,
        sample_size: int = DEFAULT_BUSINESS_LIMITS.frontmatter_binary_sample_bytes,
        control_char_ratio: float = DEFAULT_BUSINESS_LIMITS.frontmatter_control_char_ratio,
    ) -> bool:
        """Supported files are handled by parsers; unsupported files must be plain text."""

        # Videos are preview-only workspace assets. Never guess them as text from a small sample.
        if path.suffix.lower() in {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v"}:
            return False
        if path.suffix.lower() in suffixes:
            return True
        return not FrontmatterBootstrapService._is_binary_file(
            path,
            sample_size=sample_size,
            control_char_ratio=control_char_ratio,
        )

    @staticmethod
    def _is_binary_file(
        path: Path,
        *,
        sample_size: int = DEFAULT_BUSINESS_LIMITS.frontmatter_binary_sample_bytes,
        control_char_ratio: float = DEFAULT_BUSINESS_LIMITS.frontmatter_control_char_ratio,
    ) -> bool:
        """Detect likely binary files from a small sample."""

        try:
            data = path.read_bytes()[:sample_size]
        except OSError:
            return True
        if not data:
            return False
        if b"\0" in data:
            return True
        for encoding in TEXT_FALLBACK_ENCODINGS:
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                text = ""
        else:
            return True
        control_chars = sum(
            1 for char in text
            if ord(char) < 32 and char not in "\n\r\t\f\b"
        )
        return control_chars / max(len(text), 1) > control_char_ratio

    @staticmethod
    def _hash_file(source_path: Path) -> str:
        """
        计算原始知识文件内容哈希。
        source_path: 原始知识文件路径。
        """

        digest = hashlib.sha256()
        digest.update(source_path.read_bytes())
        return digest.hexdigest()
