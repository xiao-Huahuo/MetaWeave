"""KnowledgeLibraryService 的 preview 职责。

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

class KnowledgePreviewMixin:
    def preview_file(self, *, user_id: str, path: str) -> dict:
        """
        为 editor 多模态查看器生成只读预览数据。

        user_id: 用户 ID。
        path: 知识库根目录内的相对文件路径。
        """

        root = self._get_active_root(user_id=user_id)
        target = self._resolve_child_path(root=root, relative_path=path)
        if not target.is_file():
            raise ValueError("file not found")

        suffix = target.suffix.lower()
        base_payload = {
            "path": self._relative_path(path=target, root=root),
            "mtime": self._format_mtime(target),
            "size": target.stat().st_size,
            "extension": suffix,
        }
        if suffix in {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v"}:
            return {
                **base_payload,
                "kind": "video",
                "video_container": self._detect_video_container(path=target),
                "mime_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                "raw_url": self._raw_file_url(user_id=user_id, relative_path=str(base_payload["path"])),
                "readonly": True,
            }
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
            mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            image_preview = self._preview_image_text_from_frontmatter(
                user_id=user_id,
                relative_path=str(base_payload["path"]),
            )
            return {
                **base_payload,
                "kind": "image",
                "mime_type": mime_type,
                "raw_url": self._raw_file_url(user_id=user_id, relative_path=str(base_payload["path"])),
                **image_preview,
                "readonly": True,
            }
        if suffix == ".pdf":
            pdf_preview = self._preview_pdf(
                user_id=user_id,
                relative_path=str(base_payload["path"]),
                path=target,
            )
            return {
                **base_payload,
                **pdf_preview,
                "kind": "pdf",
                "mime_type": "application/pdf",
                "raw_url": self._raw_file_url(user_id=user_id, relative_path=str(base_payload["path"])),
                "readonly": True,
            }
        if suffix in {".csv", ".tsv"}:
            with _open_text_with_fallback(target) as handle:
                content = handle.read()
            return {
                **base_payload,
                "kind": "table",
                "sheets": [self._preview_delimited_table(path=target, delimiter="\t" if suffix == ".tsv" else ",")],
                "content": content,
                "readonly": suffix != ".csv",
            }
        if suffix in {".xls", ".xlsx"}:
            return {
                **base_payload,
                "kind": "table",
                "sheets": self._preview_xls(path=target) if suffix == ".xls" else self._preview_xlsx(path=target),
                **self._preview_text_from_frontmatter(user_id=user_id, relative_path=str(base_payload["path"])),
                "readonly": True,
            }
        if suffix == ".pptx":
            return {
                **base_payload,
                **self._preview_text_from_frontmatter(user_id=user_id, relative_path=str(base_payload["path"])),
                "kind": "presentation",
                "readonly": True,
            }
        if suffix == ".ppt":
            return {
                **base_payload,
                "kind": "unsupported",
                "message": "当前文件类型暂不支持预览。",
                "readonly": True,
            }
        if suffix == ".ppt":
            # Try to convert PPTX → PDF for native iframe preview
            if suffix == ".pptx":
                pdf_output = target.with_name(target.name + ".pdf")
                if self._can_generate_pptx_pdf():
                    if not pdf_output.exists() or pdf_output.stat().st_mtime < target.stat().st_mtime:
                        try:
                            self._generate_pdf_from_pptx(path=target, output_path=pdf_output)
                        except Exception as exc:
                            logger.warning("PPTX→PDF generation failed: %s", exc)
                    if pdf_output.exists():
                        pdf_preview = self._preview_pdf(
                            user_id=user_id,
                            relative_path=str(base_payload["path"]) + ".pdf",
                            path=pdf_output,
                        )
                        # Merge parsed PPTX text content into the PDF preview
                        # so Edit mode shows readable text, not empty scanned metadata.
                        pptx_content = self._preview_pptx(path=target).get("content", "")
                        return {
                            **base_payload,
                            **pdf_preview,
                            "content": pptx_content,
                            "kind": "pdf",
                            "mime_type": "application/pdf",
                            "raw_url": self._raw_file_url(user_id=user_id, relative_path=str(base_payload["path"]) + ".pdf"),
                            "readonly": True,
                        }
            # Fallback: HTML-based preview
            return {
                **base_payload,
                **self._preview_pptx(path=target),
                **self._preview_text_from_frontmatter(user_id=user_id, relative_path=str(base_payload["path"])),
                "kind": "document",
                "readonly": True,
            }
        if suffix == ".docx":
            return {
                **base_payload,
                "kind": "document",
                "html": self._preview_docx_html(path=target),
                **self._preview_text_from_frontmatter(user_id=user_id, relative_path=str(base_payload["path"])),
                "readonly": True,
            }
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                **base_payload,
                "kind": "unsupported",
                "message": "当前文件不是 UTF-8 文本,也没有可用的多模态预览器。",
                "readonly": True,
            }
        return {
            **base_payload,
            "kind": "text",
            "content": content,
            "readonly": False,
        }
    @staticmethod
    def _resolve_raw_mime_type(path: Path) -> str:
        """解析原始文件正确的 MIME 类型,特别处理 Office 格式。"""
        OFFICE_MIME_TYPES: dict[str, str] = {
            ".pdf": "application/pdf",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        suffix = path.suffix.lower()
        if suffix in OFFICE_MIME_TYPES:
            return OFFICE_MIME_TYPES[suffix]
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    @staticmethod
    def _detect_video_container(*, path: Path) -> str:
        """识别扩展名伪装的 MPEG-TS，避免把它交给浏览器原生 MP4 解复用器。"""

        with path.open("rb") as handle:
            header = handle.read(204 * 4)
        for packet_size in (188, 192, 204):
            max_offset = min(packet_size, len(header))
            for offset in range(max_offset):
                sync_positions = (offset, offset + packet_size, offset + (packet_size * 2))
                if sync_positions[-1] < len(header) and all(header[position] == 0x47 for position in sync_positions):
                    return "mpegts"
        return "native"
    def resolve_file_for_raw_response(self, *, user_id: str, path: str) -> tuple[Path, str]:
        """
        解析可供浏览器预览的原始文件响应路径。

        user_id: 用户 ID。
        path: 知识库根目录内的相对文件路径。
        """

        root = self._get_active_root(user_id=user_id)
        target = self._resolve_child_path(root=root, relative_path=path)
        if not target.is_file():
            raise ValueError("file not found")
        mime_type = self._resolve_raw_mime_type(target)
        return target, mime_type
    def resolve_knowledge_asset_for_response(self, *, user_id: str, path: str) -> tuple[Path, str]:
        """
        解析知识库预览导出的临时 asset 路径。

        path: assets/knowledge 下的相对路径,例如 pdf_preview/<hash>/image.png。
        """

        prefix = user_id + "/"
        if not path.startswith(prefix):
            raise ValueError("asset not found")
        root = (self.config.storage.assets_dir / "knowledge" / user_id).resolve()
        target = self._resolve_child_path(root=root, relative_path=path[len(prefix):])
        if not target.is_file():
            raise ValueError("asset not found")
        mime_type = self._resolve_raw_mime_type(target)
        return target, mime_type
    @staticmethod
    def _file_data_url(*, path: Path, mime_type: str) -> str:
        """把图片/PDF 文件编码为浏览器可直接使用的 data URL。"""

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
    @staticmethod
    def _raw_file_url(*, user_id: str, relative_path: str) -> str:
        """构造同源 raw 文件预览 URL,由前端按 API origin 补全。"""

        return f"/knowledge/files/raw?user_id={quote(user_id)}&path={quote(relative_path)}"
    @staticmethod
    def _preview_delimited_table(*, path: Path, delimiter: str) -> dict:
        """读取 CSV/TSV 的前若干行用于表格预览。"""

        rows: list[list[str]] = []
        with _open_text_with_fallback(path) as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for index, row in enumerate(reader):
                if index >= DEFAULT_BUSINESS_LIMITS.knowledge_table_preview_rows:
                    break
                rows.append([cell.strip() for cell in row])
        return {"name": path.stem, "rows": rows}
    @classmethod
    def _preview_xlsx(cls, *, path: Path) -> list[dict]:
        """从 XLSX OOXML 中读取工作表前若干行用于表格预览。"""

        sheets: list[dict] = []
        with zipfile.ZipFile(path) as archive:
            shared_strings = cls._read_xlsx_shared_strings(archive)
            sheet_paths = sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            for index, sheet_path in enumerate(sheet_paths, start=1):
                rows = cls._extract_xlsx_rows(archive=archive, sheet_path=sheet_path, shared_strings=shared_strings)
                sheets.append({"name": f"Sheet {index}", "rows": rows})
        return sheets
    @staticmethod
    def _preview_xls(*, path: Path) -> list[dict]:
        """Read legacy XLS workbooks for the Forms-only editor pipeline."""

        import xlrd  # type: ignore[import-untyped]

        workbook = xlrd.open_workbook(path)
        sheets: list[dict] = []
        for sheet in workbook.sheets():
            rows = [
                [str(sheet.cell_value(row_index, column_index)) for column_index in range(sheet.ncols)]
                for row_index in range(min(sheet.nrows, 200))
            ]
            sheets.append({"name": sheet.name, "rows": rows})
        return sheets
    @staticmethod
    def _preview_docx_html(*, path: Path) -> str:
        """优先使用 mammoth 转换 DOCX,依赖缺失时回退到 OOXML 段落抽取。"""

        try:
            import mammoth  # type: ignore[import-untyped]

            with path.open("rb") as docx_file:
                result = mammoth.convert_to_html(docx_file)
            return str(result.value or "")
        except Exception:
            paragraphs: list[str] = []
            with zipfile.ZipFile(path) as archive:
                try:
                    xml_text = archive.read("word/document.xml").decode("utf-8", errors="ignore")
                except KeyError:
                    return "<p>无法读取 DOCX 正文。</p>"
            root = ElementTree.fromstring(xml_text)
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "p":
                    continue
                text = " ".join(part.strip() for part in node.itertext() if part.strip())
                if text:
                    paragraphs.append(f"<p>{html.escape(text)}</p>")
            return "\n".join(paragraphs) or "<p>DOCX 中没有可预览文本。</p>"
    @staticmethod
    def _can_generate_pptx_pdf() -> bool:
        """检查是否可用内建渲染引擎生成 PPTX PDF 预览。需要 Pillow 和可用中文字体。"""
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        except ImportError:
            return False
        return not not KnowledgePreviewMixin._find_cjk_font_path()
    @staticmethod
    def _find_cjk_font_path() -> str | None:
        """查找系统中可用的中文字体路径。"""
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/simsunb.ttf",
            "C:/Windows/Fonts/SimsunExtG.ttf",
            "C:/Windows/Fonts/yahei.ttf",
            str(Path.home() / "Library/Fonts/PingFang.ttc"),
            str(Path.home() / "Library/Fonts/Hiragino Sans GB.ttc"),
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None
    @staticmethod
    def _generate_pdf_from_pptx(*, path: Path, output_path: Path) -> None:
        """用 Pillow 渲染每个幻灯片为图像页并生成多页 PDF,无需外部依赖。"""
        from PIL import Image, ImageDraw, ImageFont

        ns = {
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        }

        slides: list[dict] = []
        with zipfile.ZipFile(path) as archive:
            slide_paths = sorted(
                name for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            if not slide_paths:
                raise ValueError("no slides found")

            for slide_index, slide_path in enumerate(slide_paths, start=1):
                xml_text = archive.read(slide_path).decode("utf-8", errors="ignore")
                slide_root = ElementTree.fromstring(xml_text)

                text_parts: list[str] = []
                for text_elem in slide_root.iter(f"{{{ns['a']}}}t"):
                    if text_elem.text:
                        text_parts.append(text_elem.text.strip())
                slide_text = "\n".join(part for part in text_parts if part)

                rels_path = f"ppt/slides/_rels/{Path(slide_path).name}.rels"
                rels_map: dict[str, str] = {}
                try:
                    rels_xml = archive.read(rels_path).decode("utf-8", errors="ignore")
                    rels_root = ElementTree.fromstring(rels_xml)
                    for rel in rels_root:
                        rid = rel.get("Id", "")
                        target = rel.get("Target", "")
                        if rid and target and "image" in str(rel.get("Type", "")):
                            media_path = str(Path("ppt/slides") / target).replace("\\", "/")
                            rels_map[rid] = media_path
                except KeyError:
                    pass

                slide_images: list[bytes] = []
                for blip in slide_root.iter(f"{{{ns['a']}}}blip"):
                    rid = blip.get(f"{{{ns['r']}}}embed") or blip.get(f"{{{ns['r']}}}link") or ""
                    media_path = rels_map.get(rid)
                    if media_path and media_path in archive.namelist():
                        slide_images.append(archive.read(media_path))

                slides.append({"text": slide_text, "images": slide_images, "index": slide_index})

        # Render each slide as a Pillow image page
        font_path = KnowledgePreviewMixin._find_cjk_font_path()
        page_w, page_h = 1280, 720  # 16:9
        margin = 48
        title_size, body_size = 36, 22
        title_font = ImageFont.truetype(font_path, title_size) if font_path else ImageFont.load_default()
        body_font = ImageFont.truetype(font_path, body_size) if font_path else ImageFont.load_default()

        pages: list[Image.Image] = []
        for slide in slides:
            img = Image.new("RGB", (page_w, page_h), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            y = margin

            # Slide title
            draw.text((margin, y), f"Slide {slide['index']}", font=title_font, fill=(80, 80, 80))
            y += 60

            # Text lines
            if slide["text"]:
                for line in slide["text"].split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # Manual line wrapping for long text
                    while len(line) > 0:
                        bbox = draw.textbbox((0, 0), line[:100], font=body_font)
                        avail_w = page_w - 2 * margin
                        # Binary search for the longest substring that fits
                        if bbox[2] - bbox[0] > avail_w:
                            lo, hi = 1, min(len(line), 80)
                            while lo < hi:
                                mid = (lo + hi + 1) // 2
                                b = draw.textbbox((0, 0), line[:mid], font=body_font)
                                if b[2] - b[0] <= avail_w:
                                    lo = mid
                                else:
                                    hi = mid - 1
                            wrapped = line[:lo]
                            line = line[lo:]
                        else:
                            wrapped = line
                            line = ""
                        draw.text((margin, y), wrapped, font=body_font, fill=(30, 30, 30))
                        y += body_size + 6
                        if y > page_h - margin:
                            y = margin
                            pages.append(img)
                            img = Image.new("RGB", (page_w, page_h), (255, 255, 255))
                            draw = ImageDraw.Draw(img)

            # Embedded images
            for img_bytes in slide["images"]:
                if y > page_h - 200:
                    pages.append(img)
                    img = Image.new("RGB", (page_w, page_h), (255, 255, 255))
                    draw = ImageDraw.Draw(img)
                    y = margin
                try:
                    slide_img = Image.open(io.BytesIO(img_bytes))
                    max_img_w = page_w - 2 * margin
                    max_img_h = 400
                    if slide_img.width > max_img_w or slide_img.height > max_img_h:
                        ratio = min(max_img_w / slide_img.width, max_img_h / slide_img.height)
                        slide_img = slide_img.resize(
                            (int(slide_img.width * ratio), int(slide_img.height * ratio))
                        )
                    img.paste(slide_img, (margin, y))
                    y += slide_img.height + 16
                except Exception:
                    pass

            pages.append(img)

        if pages:
            from fpdf import FPDF
            pdf = FPDF(unit='pt', format=(page_w, page_h))
            for page_img in pages:
                buf = io.BytesIO()
                page_img.save(buf, format='PNG')
                pdf.add_page()
                pdf.image(buf, x=0, y=0, w=page_w, h=page_h)
            pdf.output(str(output_path))
        else:
            raise ValueError("no pages to render")
    @staticmethod
    def _preview_pptx(*, path: Path) -> dict:
        """提取 PPTX 按幻灯片文本内容供 Edit 模式展示,同时生成 HTML 预览。"""

        if path.suffix.lower() == ".ppt":
            return {
                "content": "",
                "html": "<p>旧版 .ppt 暂不支持预览,请转换为 .pptx 格式。</p>",
                "image_count": 0,
                "slide_count": 0,
            }

        try:
            import xml.etree.ElementTree as ET

            ns = {
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
            }

            slides: list[dict] = []
            with zipfile.ZipFile(path) as archive:
                slide_paths = sorted(
                    name for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
                if not slide_paths:
                    return {
                        "content": "",
                        "html": "<p>PPTX 中没有找到幻灯片。</p>",
                        "image_count": 0,
                        "slide_count": 0,
                    }

                # Build an image cache: rId -> base64 data URL per slide
                for slide_index, slide_path in enumerate(slide_paths, start=1):
                    xml_text = archive.read(slide_path).decode("utf-8", errors="ignore")
                    slide_root = ET.fromstring(xml_text)

                    # Extract text
                    text_parts: list[str] = []
                    for text_elem in slide_root.iter(f"{{{ns['a']}}}t"):
                        if text_elem.text:
                            text_parts.append(text_elem.text.strip())
                    slide_text = "\n".join(part for part in text_parts if part)

                    # Extract images via relationships
                    rels_path = f"ppt/slides/_rels/{Path(slide_path).name}.rels"
                    rels_map: dict[str, str] = {}
                    try:
                        rels_xml = archive.read(rels_path).decode("utf-8", errors="ignore")
                        rels_root = ET.fromstring(rels_xml)
                        for rel in rels_root:
                            rid = rel.get("Id", "")
                            target = rel.get("Target", "")
                            if rid and target and "image" in str(rel.get("Type", "")):
                                # Resolve relative to ppt/slides/
                                media_path = str(Path("ppt/slides") / target).replace("\\", "/")
                                rels_map[rid] = media_path
                    except KeyError:
                        pass

                    # Find blip references in the slide
                    slide_images: list[str] = []
                    for blip in slide_root.iter(f"{{{ns['a']}}}blip"):
                        rid = blip.get(f"{{{ns['r']}}}embed") or blip.get(f"{{{ns['r']}}}link") or ""
                        media_path = rels_map.get(rid)
                        if media_path and media_path in archive.namelist():
                            img_bytes = archive.read(media_path)
                            ext = Path(media_path).suffix.lstrip(".") or "png"
                            if ext.lower() == "jpg":
                                ext = "jpeg"
                            b64 = base64.b64encode(img_bytes).decode("ascii")
                            slide_images.append(
                                f'<p><img src="data:image/{ext};base64,{b64}" style="max-width:100%" /></p>'
                            )

                    slides.append({
                        "text": slide_text,
                        "images": slide_images,
                        "index": slide_index,
                    })

            if not slides:
                return {
                    "content": "",
                    "html": "<p>PPTX 中没有可预览内容。</p>",
                    "image_count": 0,
                    "slide_count": 0,
                }

            # Build content (for Edit mode - plain text)
            content_parts: list[str] = []
            for slide in slides:
                content_parts.append(f"## Slide {slide['index']}\n\n{slide['text']}")
            content = "\n\n".join(content_parts).strip()

            # Build HTML (for Preview mode - rendered)
            html_parts: list[str] = []
            for slide in slides:
                html_parts.append(f"<h2>第 {slide['index']} 页</h2>")
                if slide["text"]:
                    for line in slide["text"].split("\n"):
                        line = line.strip()
                        if line:
                            html_parts.append(f"<p>{html.escape(line)}</p>")
                html_parts.extend(slide["images"])
            final_html = "\n".join(html_parts) or "<p>PPTX 中没有可预览内容。</p>"

            image_count = sum(len(s["images"]) for s in slides)
            return {
                "content": content,
                "html": final_html,
                "image_count": image_count,
                "slide_count": len(slides),
            }
        except Exception as exc:
            logger.warning("PPTX preview failed for %s: %s: %s", path, type(exc).__name__, exc)
            return {
                "content": "",
                "html": "<p>PPTX 解析失败。</p>",
                "image_count": 0,
                "slide_count": 0,
            }
    def _render_pdf_first_page(
        self,
        *,
        path: Path,
        image_output_dir: Path,
        image_public_prefix: str,
    ) -> str:
        """将 PDF 首页栅格化为紧凑预览图。

        path: PDF 原文件路径。
        image_output_dir: 预览资产输出目录。
        image_public_prefix: 与输出目录对应的静态资产 URL 前缀。
        """

        image_output_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = image_output_dir / "page-1.png"
        self._render_pdf_page_image(path=path, page_index=0, output_path=thumbnail_path, scale=1.5)
        return f"{image_public_prefix}/{thumbnail_path.name}"
    @staticmethod
    def _render_pdf_page_image(*, path: Path, page_index: int, output_path: Path, scale: float = 2.0) -> None:
        """将指定 PDF 页栅格化为 PNG，供首页封面和连续预览共同复用。"""

        import fitz

        with fitz.open(path) as document:
            if page_index < 0 or page_index >= document.page_count:
                raise ValueError("PDF page is out of range")
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(output_path)
    def render_pdf_page(self, *, user_id: str, path: str, page: int) -> tuple[Path, str]:
        """按需生成并缓存一页 PDF PNG，页面编号从 1 开始。"""

        root = self._get_active_root(user_id=user_id)
        target = self._resolve_child_path(root=root, relative_path=path)
        if not target.is_file() or target.suffix.lower() != ".pdf":
            raise ValueError("PDF file not found")
        if page < 1:
            raise ValueError("PDF page is out of range")

        relative_path = self._relative_path(path=target, root=root)
        asset_key = hashlib.sha256(f"{user_id}:{relative_path}".encode("utf-8")).hexdigest()[:24]
        # Continuous pages use a separate cache because PDF text extraction refreshes pdf_preview.
        output_dir = self.config.storage.assets_dir / "knowledge" / user_id / "pdf_pages" / asset_key
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"preview-page-{page}.png"
        if not output_path.is_file() or output_path.stat().st_mtime_ns < target.stat().st_mtime_ns:
            self._render_pdf_page_image(path=target, page_index=page - 1, output_path=output_path)
        return output_path, "image/png"
    @staticmethod
    def _pdf_pages(*, user_id: str, relative_path: str, path: Path) -> list[dict[str, Any]]:
        """读取 PDF 页面尺寸并返回不会提前触发栅格化的懒加载 URL。"""

        import fitz

        pages: list[dict[str, Any]] = []
        with fitz.open(path) as document:
            for page_index, page in enumerate(document):
                rect = page.rect
                query = urlencode({"user_id": user_id, "path": relative_path, "page": page_index + 1})
                pages.append({
                    "width": rect.width,
                    "height": rect.height,
                    "url": f"/knowledge/files/pdf-page?{query}",
                })
        return pages
    def _preview_pdf(self, *, user_id: str, relative_path: str, path: Path) -> dict:
        """提取 PDF 渲染 Markdown,并从已灌库 frontmatter 读取文本模式正文。"""

        asset_key = hashlib.sha256(f"{user_id}:{relative_path}".encode("utf-8")).hexdigest()[:24]
        image_output_dir = self.config.storage.assets_dir / "knowledge" / user_id / "pdf_preview" / asset_key
        image_public_prefix = f"/knowledge/assets/{user_id}/pdf_preview/{asset_key}"
        try:
            pdf_pages = self._pdf_pages(user_id=user_id, relative_path=relative_path, path=path)
        except Exception as exc:
            logger.warning("PDF page inspection failed for %s: %s", path, exc)
            pdf_pages = []
        try:
            extracted = extract_pdf_text(
                path,
                image_output_dir=image_output_dir,
                image_public_prefix=image_public_prefix,
            )
        except Exception:
            try:
                thumbnail_url = self._render_pdf_first_page(
                    path=path,
                    image_output_dir=image_output_dir,
                    image_public_prefix=image_public_prefix,
                )
            except Exception as exc:
                logger.warning("PDF first-page preview failed for %s: %s", path, exc)
                thumbnail_url = ""
            return {
                "content": "",
                "render_content": "",
                "text_status": "not_ingested",
                "pdf_scanned": True,
                "page_count": len(pdf_pages),
                "pdf_pages": pdf_pages,
                "image_count": 0,
                "table_count": 0,
                "thumbnail_url": thumbnail_url,
            }
        try:
            # PDF extraction refreshes this asset directory, so render the card image afterwards.
            thumbnail_url = self._render_pdf_first_page(
                path=path,
                image_output_dir=image_output_dir,
                image_public_prefix=image_public_prefix,
            )
        except Exception as exc:
            logger.warning("PDF first-page preview failed for %s: %s", path, exc)
            thumbnail_url = ""
        text_preview = self._preview_text_from_frontmatter(user_id=user_id, relative_path=relative_path)
        return {
            **text_preview,
            "render_content": extracted.content,
            "pdf_scanned": extracted.is_scanned,
            "page_count": extracted.page_count,
            "pdf_pages": pdf_pages,
            "image_count": extracted.image_count,
            "table_count": extracted.table_count,
            "thumbnail_url": thumbnail_url,
        }
    def _preview_image_text_from_frontmatter(self, *, user_id: str, relative_path: str) -> dict:
        """
        从已有 frontmatter 读取图片 OCR 文本,避免点击预览时现场执行慢速 OCR。

        user_id: 当前用户 ID。
        relative_path: 图片相对 active 知识库根目录的路径。
        """

        preview = self._preview_text_from_frontmatter(user_id=user_id, relative_path=relative_path)
        payload = self._read_frontmatter_payload_for_relative_path(user_id=user_id, relative_path=relative_path)
        if not payload:
            return {**preview, "ocr_status": "not_ingested", "ocr_word_count": 0}
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        return {
            **preview,
            "ocr_status": str(metadata.get("ocr_status") or ("completed" if preview.get("content") else "no_text")),
            "ocr_engine_available": bool(metadata.get("ocr_engine_available", False)),
            "ocr_word_count": int(metadata.get("ocr_word_count") or 0),
            "ocr_average_confidence": float(metadata.get("ocr_average_confidence") or 0.0),
        }
    def _preview_text_from_frontmatter(self, *, user_id: str, relative_path: str) -> dict:
        """从已灌库 frontmatter 拼接章节正文;未灌库时不开放文本 Edit。"""

        payload = self._read_frontmatter_payload_for_relative_path(user_id=user_id, relative_path=relative_path)
        if not payload:
            return {
                "content": "",
                "semantic_markdown": "",
                "text_status": "not_ingested",
                "schema_version": 0,
                "projection_hash": "",
            }
        markdown = str(payload.get("markdown") or "").strip()
        sections = payload.get("sections", [])
        section_texts = [
            str(section.get("content") or "").strip()
            for section in sections
            if isinstance(section, dict) and str(section.get("content") or "").strip()
        ] if isinstance(sections, list) else []
        content = "\n\n".join(section_texts).strip()
        semantic_markdown = markdown or content
        return {
            "content": content,
            "semantic_markdown": semantic_markdown,
            "text_status": "ready" if semantic_markdown else "empty",
            "schema_version": int(payload.get("schema_version") or 1),
            "projection_hash": str(payload.get("projection_hash") or ""),
        }
    def read_frontmatter_payload_for_file(self, *, user_id: str, path: str) -> dict[str, Any]:
        """
        读取 active 知识库内文件对应的完整 frontmatter JSON。

        user_id: 当前用户 ID。
        path: 文件相对 active 知识库根目录的路径。
        """

        payload = self._read_frontmatter_payload_for_relative_path(user_id=user_id, relative_path=path)
        if payload is None:
            raise ValueError("frontmatter json not found; refresh or ingest this file first")
        return payload
    def _read_frontmatter_payload_for_relative_path(self, *, user_id: str, relative_path: str) -> dict[str, Any] | None:
        """按用户 active library 和相对路径读取 frontmatter JSON,不存在时返回 None。"""

        if not hasattr(self.settings_service, "ensure_user_profile"):
            return None
        profile = self.settings_service.ensure_user_profile(user_id=user_id)
        active_library = dict(profile["active_knowledge_library"])
        normalized_user_id = str(profile["user_id"])
        library_id = str(active_library["library_id"])
        frontmatter_root = self._resolve_user_frontmatter_dir(normalized_user_id, library_id).resolve()
        normalized_path = relative_path.replace("\\", "/").strip("/")
        if not normalized_path:
            return None
        frontmatter_path = (frontmatter_root / normalized_path).with_suffix(".json").resolve()
        if not self._is_relative_to(frontmatter_path, frontmatter_root) or not frontmatter_path.is_file():
            return None
        return json.loads(frontmatter_path.read_text(encoding="utf-8"))
    @staticmethod
    def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
        """读取 XLSX sharedStrings 表。"""

        try:
            xml_text = archive.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
        except KeyError:
            return []
        root = ElementTree.fromstring(xml_text)
        return [" ".join(part.strip() for part in item.itertext() if part.strip()) for item in root]
    @classmethod
    def _extract_xlsx_rows(
        cls,
        *,
        archive: zipfile.ZipFile,
        sheet_path: str,
        shared_strings: list[str],
    ) -> list[list[str]]:
        """从 XLSX 工作表 XML 中读取前 200 行。"""

        root = ElementTree.fromstring(archive.read(sheet_path).decode("utf-8", errors="ignore"))
        rows: list[list[str]] = []
        for row in root.iter():
            if row.tag.rsplit("}", 1)[-1] != "row":
                continue
            values: list[str] = []
            for cell in row:
                if cell.tag.rsplit("}", 1)[-1] != "c":
                    continue
                values.append(cls._xlsx_cell_value(cell=cell, shared_strings=shared_strings))
            if any(values):
                rows.append(values)
            if len(rows) >= DEFAULT_BUSINESS_LIMITS.knowledge_table_preview_rows:
                break
        return rows
    @staticmethod
    def _xlsx_cell_value(*, cell: ElementTree.Element, shared_strings: list[str]) -> str:
        """解析 XLSX 单元格文本值。"""

        cell_type = cell.attrib.get("t")
        value = ""
        for child in cell:
            local_name = child.tag.rsplit("}", 1)[-1]
            if local_name == "v":
                value = child.text or ""
                break
            if local_name == "is":
                value = " ".join(part.strip() for part in child.itertext() if part.strip())
                break
        if cell_type == "s":
            try:
                return shared_strings[int(value)]
            except (ValueError, IndexError):
                return value
        return value
