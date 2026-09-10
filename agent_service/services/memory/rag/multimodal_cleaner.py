"""
多模态知识源清洗模块。

功能说明:
本文件将 Markdown/TXT 之外的常见知识库文件清洗为统一章节文本,供
`frontmatter_bootstrap` 写入 StructuredKnowledgeDocument。第一版只使用 Python
标准库,优先保证离线可运行和灌库链路稳定;OCR、视觉描述和高级表格识别可在本模块
内替换为更强解析器,不会影响后续切块和向量入库。

使用说明:
cleaner = MultimodalDocumentCleaner()
result = cleaner.clean(source_path=Path("demo.docx"), title="demo")
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.services.memory.rag.frontmatter_document import StructuredKnowledgeSection
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.services.memory.rag.pdf_cleaner import extract_pdf_text


@dataclass(slots=True)
class CleanedDocument:
    """
    多模态清洗后的文档。

    source_type: 原始文件类型。
    sections: 可直接进入 StructuredKnowledgeDocument 的章节列表。
    metadata: 清洗阶段生成的扩展元数据。
    summary: 可选文档摘要,第一版默认为空。
    """

    source_type: str
    sections: list[StructuredKnowledgeSection]
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


class _HtmlTextExtractor(HTMLParser):
    """轻量 HTML 正文提取器,忽略 script/style 并保留块级换行。"""

    _block_tags = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        """初始化 HTML 解析状态。"""

        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录块级标签换行,并跳过脚本和样式内容。"""

        _ = attrs
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """结束块级标签时补充换行。"""

        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """追加正文文本。"""

        if self._skip_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        """返回规整后的 HTML 文本。"""

        return _normalize_text(" ".join(self.parts))


class MultimodalDocumentCleaner:
    """
    多模态文件清洗器。

    max_table_rows: 表格类文件最多写入语义索引的样例行数。
    """

    def __init__(
        self,
        *,
        max_table_rows: int | None = None,
        config: AgentConfig | None = None,
        ocr_enabled: bool = False,
        image_ocr_service: ImageOcrService | None = None,
    ) -> None:
        """保存清洗参数。"""

        self.config = config or AgentConfig()
        limits = getattr(self.config, "limits", DEFAULT_BUSINESS_LIMITS)
        self.max_table_rows = max_table_rows or limits.table_max_rows
        self.ocr_enabled = ocr_enabled
        self.image_ocr_service = image_ocr_service
        self._progress_callback: Callable[[dict[str, Any]], None] | None = None

    def clean(
        self,
        *,
        source_path: Path,
        title: str,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> CleanedDocument:
        """
        按文件后缀清洗知识源。

        source_path: 原始文件路径。
        title: 上层解析得到的文档标题。
        """

        suffix = source_path.suffix.lower()
        self._progress_callback = progress_callback
        self._emit_progress(stage="extract", label="开始解析文件内容", current=0, total=1, start=6, end=44)
        try:
            if suffix == ".json":
                result = self._clean_json(source_path=source_path, title=title)
            elif suffix == ".jsonl":
                result = self._clean_jsonl(source_path=source_path, title=title)
            elif suffix in {".csv", ".tsv"}:
                result = self._clean_delimited_table(source_path=source_path, title=title, delimiter="\t" if suffix == ".tsv" else ",")
            elif suffix in {".html", ".htm"}:
                result = self._clean_html(source_path=source_path, title=title)
            elif suffix == ".xml":
                result = self._clean_xml(source_path=source_path, title=title)
            elif suffix == ".docx":
                result = self._clean_docx(source_path=source_path, title=title)
            elif suffix in {".xlsx", ".xls"}:
                result = (
                    self._clean_xlsx(source_path=source_path, title=title)
                    if zipfile.is_zipfile(source_path)
                    else self._clean_xls(source_path=source_path, title=title)
                )
            elif suffix == ".pptx":
                result = self._clean_pptx(source_path=source_path, title=title)
            elif suffix == ".pdf":
                result = self._clean_pdf(
                    source_path=source_path,
                    title=title,
                    asset_output_dir=asset_output_dir,
                    asset_public_prefix=asset_public_prefix,
                )
            elif suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                result = self._clean_image(source_path=source_path, title=title)
            else:
                result = self._clean_binary_placeholder(source_path=source_path, title=title, source_type="asset")
            self._emit_progress(stage="normalize", label="正在生成统一正文", current=1, total=1, start=44, end=50)
            return result
        finally:
            self._progress_callback = None

    def _emit_progress(
        self,
        *,
        stage: str,
        label: str,
        current: float,
        total: float,
        start: int,
        end: int,
        message: str = "",
        stage_current: float | None = None,
        stage_total: float | None = None,
    ) -> None:
        """把类型专属工作单位映射为统一且单调的文件总进度。"""

        if not self._progress_callback:
            return
        safe_total = max(1, total)
        ratio = max(0, min(safe_total, current)) / safe_total
        self._progress_callback({
            "phase": "frontmatter",
            "status": "processing",
            "stage": stage,
            "stage_label": label,
            "stage_current": max(0, current if stage_current is None else stage_current),
            "stage_total": max(0, total if stage_total is None else stage_total),
            "overall_progress": round(start + ((end - start) * ratio), 1),
            "message": message,
        })

    def _clean_json(self, *, source_path: Path, title: str) -> CleanedDocument:
        """将 JSON 清洗为格式化文本章节。"""

        payload = json.loads(_read_text_with_fallback(source_path))
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return _single_section_document(source_type="json", title=title, content=content, metadata={"modality": "structured_data"})

    def _clean_jsonl(self, *, source_path: Path, title: str) -> CleanedDocument:
        """将 JSONL 每行对象清洗为结构化样例文本。"""

        rows: list[str] = []
        for index, line in enumerate(_read_text_with_fallback(source_path).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(f"row {index}: {json.dumps(json.loads(line), ensure_ascii=False)}")
            except json.JSONDecodeError:
                rows.append(f"row {index}: {line.strip()}")
            if len(rows) >= self.max_table_rows:
                break
            self._emit_progress(stage="rows", label=f"正在读取第 {index} 行", current=index, total=self.max_table_rows, start=8, end=40)
        return _single_section_document(
            source_type="jsonl",
            title=title,
            content="\n".join(rows),
            metadata={"modality": "structured_data", "sample_rows": len(rows)},
        )

    def _clean_delimited_table(self, *, source_path: Path, title: str, delimiter: str) -> CleanedDocument:
        """将 CSV/TSV 清洗为保留表头和样例行的表格章节。"""

        rows: list[list[str]] = []
        with _open_text_with_fallback(source_path, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for row in reader:
                rows.append([cell.strip() for cell in row])
                self._emit_progress(stage="rows", label=f"正在读取第 {len(rows)} 行", current=len(rows), total=self.max_table_rows + 1, start=8, end=40)
                if len(rows) >= self.max_table_rows + 1:
                    break
        content = _format_table_rows(rows)
        header = rows[0] if rows else []
        return _single_section_document(
            source_type="table",
            title=title,
            content=content,
            metadata={"modality": "table", "columns": header, "sample_rows": max(0, len(rows) - 1)},
        )

    def _clean_html(self, *, source_path: Path, title: str) -> CleanedDocument:
        """将 HTML 清洗为可检索正文。"""

        parser = _HtmlTextExtractor()
        parser.feed(_read_text_with_fallback(source_path))
        return _single_section_document(source_type="html", title=title, content=parser.text(), metadata={"modality": "document"})

    def _clean_xml(self, *, source_path: Path, title: str) -> CleanedDocument:
        """将 XML 清洗为节点路径和值的文本摘要。"""

        root = ElementTree.fromstring(_read_text_with_fallback(source_path))
        lines: list[str] = []

        def visit(node: ElementTree.Element, path: list[str]) -> None:
            node_path = [*path, _local_name(node.tag)]
            text = _normalize_text(node.text or "")
            if text:
                lines.append(f"{'/'.join(node_path)}: {text}")
            for child in list(node):
                visit(child, node_path)

        visit(root, [])
        return _single_section_document(source_type="xml", title=title, content="\n".join(lines), metadata={"modality": "structured_data"})

    def _clean_docx(self, *, source_path: Path, title: str) -> CleanedDocument:
        """从 DOCX 中按文档流顺序抽取段落、标题、表格文本与图片引用。

        只遍历 w:body 的直接子元素而非整棵 document.xml:表格单元格内部的
        w:p 不会被重复计入段落流,段落与表格的原文交替顺序得以保留;带
        Heading1-6 样式时按标题层级切分章节,否则段落聚成单章节。图片引用
        通过 word/_rels/document.xml.rels 解析为真实媒体路径。
        """

        sections: list[StructuredKnowledgeSection] = []
        with zipfile.ZipFile(source_path) as archive:
            document_xml = _read_zip_text(archive, "word/document.xml")
            if not document_xml:
                return _single_section_document(source_type="docx", title=title, content="", metadata={"modality": "document"})
            root = ElementTree.fromstring(document_xml)
            body = _find_body(root)
            if body is None:
                return _single_section_document(source_type="docx", title=title, content="", metadata={"modality": "document"})
            rels_map = _read_docx_relationship_map(archive)
            blocks, image_refs = _extract_docx_blocks(
                body=body,
                title=title,
                rels_map=rels_map,
                progress_callback=lambda current, total: self._emit_progress(
                    stage="document_blocks",
                    label=f"正在解析文档块 {current} / {total}",
                    current=current,
                    total=total,
                    start=8,
                    end=30,
                ),
            )
            embedded_ocr = self._ocr_zip_images_by_ref(archive=archive, image_refs=image_refs)
            if embedded_ocr:
                blocks = _merge_docx_image_ocr_blocks(blocks=blocks, ocr_by_ref=embedded_ocr)
            if any(kind == "h" for kind, *_ in blocks):
                sections = _build_docx_heading_sections(blocks=blocks, title=title)
            else:
                sections = _build_docx_flat_sections(blocks=blocks, title=title)
        return CleanedDocument(
            source_type="docx",
            sections=sections,
            metadata={"modality": "document", "image_refs": image_refs, "ocr_enabled": self.ocr_enabled},
        )

    def _clean_xlsx(self, *, source_path: Path, title: str) -> CleanedDocument:
        """从 XLSX 中抽取工作表样例行。"""

        sections: list[StructuredKnowledgeSection] = []
        with zipfile.ZipFile(source_path) as archive:
            shared_strings = _read_xlsx_shared_strings(archive)
            sheet_paths = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            for sheet_index, sheet_path in enumerate(sheet_paths, start=1):
                rows = _extract_xlsx_rows(archive=archive, sheet_path=sheet_path, shared_strings=shared_strings, max_rows=self.max_table_rows)
                if not rows:
                    continue
                heading = f"{title} Sheet {sheet_index}"
                sections.append(_make_section(index=len(sections), heading=heading, content=_format_table_rows(rows)))
                self._emit_progress(stage="sheets", label=f"正在解析工作表 {sheet_index} / {len(sheet_paths)}", current=sheet_index, total=len(sheet_paths), start=8, end=42)
        return CleanedDocument(source_type="spreadsheet", sections=sections, metadata={"modality": "table", "sheet_count": len(sections)})

    def _clean_xls(self, *, source_path: Path, title: str) -> CleanedDocument:
        """使用项目既有 xlrd 依赖读取旧版二进制 XLS 工作簿。"""

        import xlrd  # type: ignore[import-untyped]

        workbook = xlrd.open_workbook(source_path, on_demand=True)
        sections: list[StructuredKnowledgeSection] = []
        try:
            for sheet_index, sheet in enumerate(workbook.sheets(), start=1):
                rows: list[list[str]] = []
                for row_index in range(min(sheet.nrows, self.max_table_rows)):
                    row = [_format_xls_value(sheet.cell_value(row_index, column_index)) for column_index in range(sheet.ncols)]
                    if any(row):
                        rows.append(row)
                if rows:
                    heading = f"{title} Sheet {sheet_index}"
                    sections.append(_make_section(index=len(sections), heading=heading, content=_format_table_rows(rows)))
                self._emit_progress(stage="sheets", label=f"正在解析工作表 {sheet_index} / {workbook.nsheets}", current=sheet_index, total=workbook.nsheets, start=8, end=42)
        finally:
            workbook.release_resources()
        return CleanedDocument(source_type="spreadsheet", sections=sections, metadata={"modality": "table", "sheet_count": len(sections)})

    def _clean_pptx(self, *, source_path: Path, title: str) -> CleanedDocument:
        """从 PPTX 中按 slide 抽取文本。"""

        sections: list[StructuredKnowledgeSection] = []
        with zipfile.ZipFile(source_path) as archive:
            slide_paths = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            for slide_index, slide_path in enumerate(slide_paths, start=1):
                xml_text = _read_zip_text(archive, slide_path)
                if not xml_text:
                    continue
                text = _normalize_text("\n".join(ElementTree.fromstring(xml_text).itertext()))
                if text:
                    sections.append(_make_section(index=len(sections), heading=f"{title} Slide {slide_index}", content=text))
                self._emit_progress(stage="slides", label=f"正在解析幻灯片 {slide_index} / {len(slide_paths)}", current=slide_index, total=len(slide_paths), start=8, end=30)
            image_refs = [{"path": name} for name in archive.namelist() if name.startswith("ppt/media/")]
            embedded_ocr = self._ocr_zip_images(archive=archive, image_refs=image_refs)
        if embedded_ocr:
            sections.append(_make_section(index=len(sections), heading=f"{title} 嵌入图片 OCR", content="\n".join(embedded_ocr)))
        return CleanedDocument(source_type="presentation", sections=sections, metadata={"modality": "slide", "slide_count": len(sections), "image_refs": image_refs, "ocr_enabled": self.ocr_enabled})

    def _ocr_zip_images(self, *, archive: zipfile.ZipFile, image_refs: list[Any]) -> list[str]:
        """对 OOXML 容器中的媒体图片执行 OCR。"""

        results: list[str] = []
        for archive_name, result in self._iter_zip_image_ocr_results(archive=archive, image_refs=image_refs):
            if result.has_text:
                results.append(f"{archive_name}: {result.content}")
        return results

    def _ocr_zip_images_by_ref(self, *, archive: zipfile.ZipFile, image_refs: list[Any]) -> dict[str, str]:
        """按原始图片引用返回 OCR 文本,供 DOCX 按文档流位置合并。"""

        results: dict[str, str] = {}
        for _archive_name, result, original_ref in self._iter_zip_image_ocr_results(archive=archive, image_refs=image_refs, include_original=True):
            if result.has_text:
                results[str(original_ref)] = f"图片 OCR: {result.content}"
        return results

    def _iter_zip_image_ocr_results(self, *, archive: zipfile.ZipFile, image_refs: list[Any], include_original: bool = False):
        """遍历 OOXML 媒体图片 OCR 结果,并复用引用状态回填逻辑。"""

        if not self.ocr_enabled or not self.image_ocr_service:
            return
        with tempfile.TemporaryDirectory(prefix="metaweave-ocr-") as temp_dir:
            root = Path(temp_dir)
            for image_index, image_ref in enumerate(image_refs, start=1):
                original_ref = image_ref
                if isinstance(image_ref, dict):
                    archive_name = str(image_ref.get("path") or image_ref.get("target") or "")
                else:
                    archive_name = str(image_ref)
                    match = re.search(r":\s*([^\]]+)\]?$", archive_name)
                    archive_name = match.group(1).strip() if match else ""
                archive_name = archive_name.lstrip("/")
                if archive_name.startswith("media/"):
                    media_prefix = "word/" if any(name.startswith("word/media/") for name in archive.namelist()) else "ppt/"
                    archive_name = media_prefix + archive_name
                if not archive_name or archive_name not in archive.namelist():
                    continue
                image_path = root / Path(archive_name).name
                image_path.write_bytes(archive.read(archive_name))
                result = self.image_ocr_service.extract_image_text(image_path)
                self._emit_progress(stage="ocr", label=f"正在识别内嵌图片 {image_index} / {len(image_refs)}", current=image_index, total=len(image_refs), start=30, end=44)
                if isinstance(image_ref, dict):
                    image_ref["ocr_status"] = "completed" if result.has_text else ("no_text" if result.engine_available else "engine_unavailable")
                    image_ref["ocr_word_count"] = result.word_count
                    image_ref["ocr_average_confidence"] = result.average_confidence
                    image_ref.update(_ocr_result_metadata(result))
                if include_original:
                    yield archive_name, result, original_ref
                else:
                    yield archive_name, result

    def _clean_pdf(
        self,
        *,
        source_path: Path,
        title: str,
        asset_output_dir: Path | None = None,
        asset_public_prefix: str = "",
    ) -> CleanedDocument:
        """优先从非扫描型 PDF 提取文本层;扫描型 PDF 暂登记为待 OCR。"""

        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            image_output_dir = asset_output_dir
            if self.ocr_enabled and self.image_ocr_service and image_output_dir is None:
                temp_dir = tempfile.TemporaryDirectory(prefix="metaweave-pdf-ocr-")
                image_output_dir = Path(temp_dir.name)
            extracted = extract_pdf_text(
                source_path,
                scanned_text_threshold=self.config.limits.scanned_pdf_text_threshold,
                image_output_dir=image_output_dir,
                image_public_prefix=asset_public_prefix,
                progress_callback=lambda current, total: self._emit_progress(
                    stage="pages",
                    label=f"正在解析 PDF 页面 {current} / {total}",
                    current=current,
                    total=total,
                    start=8,
                    end=28,
                ),
            )
        except Exception:
            if temp_dir:
                temp_dir.cleanup()
            return self._clean_binary_placeholder(source_path=source_path, title=title, source_type="pdf")
        ocr_text: list[str] = []
        page_ocr_blocks: list[dict[str, Any]] = []
        page_table_count = 0
        page_formula_count = 0
        page_layout_labels: set[str] = set()
        if self.ocr_enabled and self.image_ocr_service:
            for image_index, image_ref in enumerate(extracted.image_refs, start=1):
                image_path = image_ref.get("asset_path")
                if not image_path:
                    continue
                result = self.image_ocr_service.extract_image_text(Path(str(image_path)))
                self._emit_progress(stage="ocr", label=f"正在识别 PDF 图片 {image_index} / {len(extracted.image_refs)}", current=image_index, total=len(extracted.image_refs), start=28, end=44)
                image_ref["ocr_status"] = "completed" if result.has_text else ("no_text" if result.engine_available else "engine_unavailable")
                image_ref["ocr_word_count"] = result.word_count
                image_ref["ocr_average_confidence"] = result.average_confidence
                image_ref.update(_ocr_result_metadata(result))
                if result.has_text:
                    image_ref["ocr_text"] = result.content
                    ocr_text.append(f"PDF 图片 OCR: {result.content}")
            if extracted.is_scanned and not extracted.image_refs:
                try:
                    import fitz  # type: ignore[import-untyped]

                    with tempfile.TemporaryDirectory(prefix="metaweave-pdf-pages-") as page_dir:
                        document = fitz.open(source_path)
                        for page_index, page in enumerate(document):
                            page_path = Path(page_dir) / f"page-{page_index + 1}.png"
                            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(page_path)
                            result = self.image_ocr_service.extract_image_text(page_path)
                            self._emit_progress(stage="ocr", label=f"正在识别扫描页 {page_index + 1} / {document.page_count}", current=page_index + 1, total=document.page_count, start=28, end=44)
                            if result.has_text:
                                ocr_text.append(f"PDF 第 {page_index + 1} 页 OCR: {result.content}")
                            page_ocr_blocks.extend({**block, "page": page_index + 1} for block in result.blocks)
                            page_table_count += result.table_count
                            page_formula_count += result.formula_count
                            page_layout_labels.update(result.layout_labels)
                        document.close()
                except Exception:
                    pass
        if temp_dir:
            temp_dir.cleanup()
        content = _merge_pdf_image_ocr_content(extracted.content, extracted.image_refs).strip()
        if ocr_text and content == extracted.content.strip():
            content = "\n\n".join(part for part in (content, *ocr_text) if part)
        metadata = {
            "modality": "document",
            "ocr_enabled": self.ocr_enabled,
            "pdf_scanned": extracted.is_scanned,
            "page_count": extracted.page_count,
            "image_count": extracted.image_count,
            "image_refs": extracted.image_refs,
            "table_count": extracted.table_count,
            "ocr_blocks": [
                block
                for image_ref in extracted.image_refs
                for block in image_ref.get("ocr_blocks", [])
                if isinstance(block, dict)
            ] + page_ocr_blocks,
            "ocr_table_count": sum(int(ref.get("ocr_table_count") or 0) for ref in extracted.image_refs) + page_table_count,
            "ocr_formula_count": sum(int(ref.get("ocr_formula_count") or 0) for ref in extracted.image_refs) + page_formula_count,
            "ocr_layout_labels": sorted({
                str(label)
                for ref in extracted.image_refs
                for label in ref.get("ocr_layout_labels", [])
            } | page_layout_labels),
            "ocr_status": "completed" if ocr_text else ("no_text" if self.ocr_enabled and extracted.is_scanned else ("pending" if extracted.is_scanned else "not_required")),
        }
        if not content:
            return _single_section_document(
                source_type="pdf",
                title=title,
                content=(
                    f"文件名: {source_path.name}\n"
                    f"文件类型: {source_path.suffix.lower()}\n"
                    f"页数: {extracted.page_count}\n"
                    "状态: 未检测到可用文本层,需要 OCR 后才能提取正文。"
                ),
                metadata=metadata,
            )
        return _single_section_document(
            source_type="pdf",
            title=title,
            content=content,
            metadata=metadata,
        )

    def _clean_image(self, *, source_path: Path, title: str) -> CleanedDocument:
        """对普通图片执行 OCR,无文本时仅登记为图片资产。"""

        if not self.image_ocr_service:
            return self._clean_binary_placeholder(source_path=source_path, title=title, source_type="image")
        result = self.image_ocr_service.extract_image_text(
            source_path,
            progress_callback=lambda payload: self._emit_progress(
                stage=str(payload["stage"]),
                label=str(payload["stage_label"]),
                current=float(payload["progress"]),
                total=100,
                start=10,
                end=44,
                stage_current=float(payload.get("completed", 0)) + float(payload.get("skipped", 0)),
                stage_total=float(payload.get("total", 0)),
            ),
        )
        self._emit_progress(stage="ocr_result", label="结构化 OCR 完成", current=10, total=10, start=10, end=44)
        metadata = {
            "modality": "image",
            "ocr_enabled": self.ocr_enabled,
            "ocr_status": "completed" if result.has_text else ("no_text" if result.engine_available else "engine_unavailable"),
            "ocr_engine_available": result.engine_available,
            "ocr_word_count": result.word_count,
            "ocr_average_confidence": result.average_confidence,
            "file_size": source_path.stat().st_size,
            **_ocr_result_metadata(result),
        }
        if not result.has_text:
            return CleanedDocument(source_type="image", sections=[], metadata=metadata)
        return _single_section_document(
            source_type="image",
            title=title,
            content=result.content,
            metadata=metadata,
        )

    def _clean_binary_placeholder(self, *, source_path: Path, title: str, source_type: str) -> CleanedDocument:
        """为 PDF/图片等待 OCR 的二进制文件生成轻量元信息章节。"""

        stat = source_path.stat()
        content = (
            f"文件名: {source_path.name}\n"
            f"文件类型: {source_path.suffix.lower()}\n"
            f"文件大小: {stat.st_size} bytes\n"
            "状态: 已登记为多模态资产,当前版本尚未启用 OCR/视觉描述。"
        )
        return _single_section_document(
            source_type=source_type,
            title=title,
            content=content,
            metadata={
                "modality": source_type,
                "ocr_enabled": self.ocr_enabled,
                "ocr_status": "pending",
                "file_size": stat.st_size,
            },
        )


def _single_section_document(*, source_type: str, title: str, content: str, metadata: dict[str, Any]) -> CleanedDocument:
    """构建单章节清洗结果。"""

    section = _make_section(index=0, heading=title, content=content)
    return CleanedDocument(source_type=source_type, sections=[section] if content.strip() else [], metadata=metadata)


def _ocr_result_metadata(result: Any) -> dict[str, Any]:
    """返回扫描器、灌库与文档内嵌图片共用的结构化 OCR metadata。"""

    return {
        "ocr_blocks": [dict(block) for block in result.blocks],
        "ocr_page_count": result.page_count,
        "ocr_table_count": result.table_count,
        "ocr_formula_count": result.formula_count,
        "ocr_layout_labels": list(result.layout_labels),
    }


def _read_text_with_fallback(path: Path) -> str:
    """按常见编码读取文本文件,避免 GBK/UTF-8-SIG CSV 阻断整轮灌库。"""

    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _open_text_with_fallback(path: Path, *, newline: str | None = None) -> io.StringIO:
    """以 fallback 编码打开文本文件,用于 csv.reader 这类需要 file object 的解析器。"""

    _ = newline
    return io.StringIO(_read_text_with_fallback(path))


def _make_section(*, index: int, heading: str, content: str) -> StructuredKnowledgeSection:
    """构建一个结构化章节。"""

    normalized = content.strip()
    return StructuredKnowledgeSection(
        section_id=f"sec_{index:04d}",
        heading=heading,
        title_path=[heading],
        content=normalized,
        start_char=0,
        end_char=len(normalized),
    )


def _renumber_sections(sections: list[StructuredKnowledgeSection]) -> list[StructuredKnowledgeSection]:
    """按当前位置重写 section_id,避免插入段落后 ID 重复。"""

    return [
        StructuredKnowledgeSection(
            section_id=f"sec_{index:04d}",
            heading=section.heading,
            title_path=section.title_path,
            content=section.content,
            start_char=section.start_char,
            end_char=section.end_char,
        )
        for index, section in enumerate(sections)
    ]


def _format_table_rows(rows: list[list[str]]) -> str:
    """将表格行转换为可渲染的 GitHub Flavored Markdown 表格。"""

    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def format_row(row: list[str]) -> str:
        """转义单元格并为一行补齐 Markdown 外围管道。"""

        cells = ["<br>".join(cell.splitlines()).replace("|", "\\|") for cell in row]
        return "| " + " | ".join(cells) + " |"

    return "\n".join([
        format_row(padded[0]),
        "| " + " | ".join(["---"] * width) + " |",
        *(format_row(row) for row in padded[1:]),
    ])


def _format_xls_value(value: Any) -> str:
    """把 xlrd 标量转换为稳定文本，避免整数被展示为带 `.0` 的浮点数。"""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_zip_text(archive: zipfile.ZipFile, name: str) -> str:
    """从 zip 容器读取 UTF-8 XML 文本,不存在时返回空字符串。"""

    try:
        return archive.read(name).decode("utf-8", errors="ignore")
    except KeyError:
        return ""


def _local_name(tag: str) -> str:
    """去掉 XML namespace,返回本地标签名。"""

    return tag.rsplit("}", 1)[-1]


def _normalize_text(text: str) -> str:
    """压缩多余空白并保留段落换行。"""

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _join_text_nodes(element: ElementTree.Element) -> str:
    """连接一个 OOXML 节点下的文本内容。"""

    return _normalize_text("".join(element.itertext()))


def _find_body(root: ElementTree.Element) -> ElementTree.Element | None:
    """定位 w:document 下的 w:body 节点,用于按文档流顺序遍历块级元素。"""

    for child in root:
        if _local_name(child.tag) == "body":
            return child
    return None


def _attr_text(element: ElementTree.Element, local_name: str) -> str:
    """按本地名读取 XML 属性值,兼容带/不带命名空间前缀的属性。"""

    for key, value in element.attrib.items():
        if _local_name(key) == local_name and value:
            return value
    return ""


def _extract_docx_blocks(
    *,
    body: ElementTree.Element,
    title: str,
    rels_map: dict[str, str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    """把 w:body 直接子元素拆成带类型标签的块列表。

    块类型:
      ("h", level, text)      标题段落
      ("p", text)             普通段落
      ("table", heading, text) 表格
      ("img", line)           图片引用行
    返回 (blocks, image_refs):image_refs 为全部解析后的图片引用行。
    只遍历 body 的直接子元素,表格内部的单元格段落不会重复计入段落流,
    同时段落/表格的原文交替顺序得以保留。
    """

    blocks: list[tuple[Any, ...]] = []
    image_refs: list[str] = []
    table_index = 0
    elements = list(body)
    for element_index, element in enumerate(elements, start=1):
        if progress_callback:
            progress_callback(element_index, len(elements))
        name = _local_name(element.tag)
        if name == "tbl":
            rows = _extract_docx_table(element)
            if rows:
                table_index += 1
                blocks.append(("table", f"{title} 表格 {table_index}", _format_table_rows(rows)))
            continue
        if name != "p":
            continue
        heading_level = _docx_heading_level(element)
        if heading_level is not None:
            heading_text = _join_text_nodes(element)
            if heading_text:
                blocks.append(("h", heading_level, heading_text))
            continue
        text = _join_text_nodes(element)
        if text:
            blocks.append(("p", text))
        for ref in _resolve_docx_image_refs(element, rels_map):
            image_refs.append(ref)
            blocks.append(("img", ref))
    return blocks, image_refs


def _build_docx_flat_sections(*, blocks: list[tuple[Any, ...]], title: str) -> list[StructuredKnowledgeSection]:
    """无标题样式的 DOCX:按文档顺序把段落/图片聚成章节,表格独立成章。

    段落块和图片块累积进同一章节,遇到表格先冲刷当前章节再开启新章节,
    从而保留"段落-表格-段落"的原文顺序。
    """

    sections: list[StructuredKnowledgeSection] = []
    paragraph_lines: list[str] = []

    def flush_paragraphs() -> None:
        if paragraph_lines:
            sections.append(_make_section(index=len(sections), heading=title, content="\n\n".join(paragraph_lines)))
            paragraph_lines.clear()

    for block in blocks:
        kind = block[0]
        if kind in {"p", "img"}:
            paragraph_lines.append(block[1])
        elif kind == "table":
            flush_paragraphs()
            sections.append(_make_section(index=len(sections), heading=block[1], content=block[2]))
    flush_paragraphs()
    return _renumber_sections(sections)


def _merge_docx_image_ocr_blocks(*, blocks: list[tuple[Any, ...]], ocr_by_ref: dict[str, str]) -> list[tuple[Any, ...]]:
    """把 DOCX 图片 OCR 文本替换到原图片块位置,保留文档流顺序。"""

    merged: list[tuple[Any, ...]] = []
    for block in blocks:
        if block[0] == "img":
            ocr_text = ocr_by_ref.get(str(block[1]))
            if ocr_text:
                merged.append(("img", ocr_text))
                continue
        merged.append(block)
    return merged


def _build_docx_heading_sections(*, blocks: list[tuple[Any, ...]], title: str) -> list[StructuredKnowledgeSection]:
    """按标题层级把 DOCX 块流切分为章节。

    命中 Heading1-6 时开启新章节,并依据标题层级堆栈生成 title_path
    ([title, h1, h2, ...]),与 Markdown 章节结构对齐;标题以下的段落、
    表格与图片并入该章节,直到下一个同级或更高级标题出现。
    """

    sections: list[StructuredKnowledgeSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading = title
    current_title_path = [title]
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            content = "\n\n".join(current_lines).strip()
            sections.append(
                StructuredKnowledgeSection(
                    section_id=f"sec_{len(sections):04d}",
                    heading=current_heading,
                    title_path=list(current_title_path),
                    content=content,
                    start_char=0,
                    end_char=len(content),
                )
            )
            current_lines.clear()

    for block in blocks:
        kind = block[0]
        if kind == "h":
            level, heading_text = block[1], block[2]
            flush()
            heading_stack = [(stack_level, stack_heading) for stack_level, stack_heading in heading_stack if stack_level < level]
            heading_stack.append((level, heading_text))
            current_heading = heading_text
            current_title_path = [title, *[stack_heading for _, stack_heading in heading_stack]]
        elif kind in {"p", "img"}:
            current_lines.append(block[1])
        elif kind == "table":
            current_lines.append(f"{block[1]}\n{block[2]}")
    flush()
    return _renumber_sections(sections)


def _merge_pdf_image_ocr_content(content: str, image_refs: list[dict[str, Any]]) -> str:
    """把 PDF 渲染 Markdown 中的图片占位替换为同位置 OCR 文本。"""

    merged = content
    for image_ref in image_refs:
        ocr_text = str(image_ref.get("ocr_text") or "").strip()
        public_url = str(image_ref.get("public_url") or "").strip()
        if not ocr_text or not public_url:
            continue
        page = image_ref.get("page")
        index = image_ref.get("index")
        placeholder = f"![PDF page {page} image {index}]({public_url})"
        replacement = f"PDF 图片 OCR: {ocr_text}"
        if placeholder in merged:
            merged = merged.replace(placeholder, replacement, 1)
    return merged


def _docx_heading_level(element: ElementTree.Element) -> int | None:
    """识别 w:p 的标题样式,命中 Heading1-6 时返回对应层级。

    兼容 "Heading1"/"Heading 1"/"1"/"标题 1" 等常见样式 ID 写法,
    未命中时返回 None。
    """

    for node in element.iter():
        if _local_name(node.tag) != "pPr":
            continue
        for child in node:
            if _local_name(child.tag) != "pStyle":
                continue
            value = _attr_text(child, "val")
            if not value:
                continue
            match = re.search(r"(?i)(?:heading|标题)?\s*([1-6])\b", value)
            if match:
                return int(match.group(1))
    return None


def _read_docx_relationship_map(archive: zipfile.ZipFile) -> dict[str, str]:
    """读取 DOCX 文档级关系表,返回 rId -> 图片资源路径 的映射。

    只保留图片类关系(media/imageN.png),Target 中多余的 ../ 前缀会被
    归一化,使图片引用可从裸 rId 升级为真实资源路径。
    """

    rels_xml = _read_zip_text(archive, "word/_rels/document.xml.rels")
    if not rels_xml:
        return {}
    try:
        rels_root = ElementTree.fromstring(rels_xml)
    except ElementTree.ParseError:
        return {}
    rels_map: dict[str, str] = {}
    for rel in rels_root:
        rel_id = _attr_text(rel, "Id")
        target = _attr_text(rel, "Target")
        rel_type = _attr_text(rel, "Type")
        if not rel_id or not target or "image" not in rel_type:
            continue
        normalized = target.replace("\\", "/")
        while normalized.startswith("../"):
            normalized = normalized[3:]
        rels_map[rel_id] = normalized
    return rels_map


def _resolve_docx_image_refs(element: ElementTree.Element, rels_map: dict[str, str]) -> list[str]:
    """解析 w:p 中嵌入的图片引用,把 rId 升级为可读的媒体资源路径。

    rels_map: _read_docx_relationship_map 解析出的 rId -> 路径 映射。
    映射未命中时回退为原来的裸 rId 表示,保证缺 rels 文件的 DOCX 仍可解析。
    """

    refs: list[str] = []
    for node in element.iter():
        for key, value in node.attrib.items():
            if _local_name(key) not in {"embed", "link"} or not value:
                continue
            target = rels_map.get(value)
            refs.append(f"[DOCX 图片引用: {target}]" if target else f"image relationship: {value}")
    return refs


def _extract_docx_table(table: ElementTree.Element) -> list[list[str]]:
    """从 DOCX 表格节点抽取行列文本。"""

    rows: list[list[str]] = []
    for row in table:
        if _local_name(row.tag) != "tr":
            continue
        cells: list[str] = []
        for cell in row:
            if _local_name(cell.tag) == "tc":
                cells.append(_join_text_nodes(cell))
                cells.extend([""] * (_docx_grid_span(cell) - 1))
        if any(cells):
            rows.append(cells)
    return rows


def _docx_grid_span(cell: ElementTree.Element) -> int:
    """读取 DOCX `w:gridSpan`，返回单元格实际横跨的列数。"""

    for node in cell.iter():
        if _local_name(node.tag) != "gridSpan":
            continue
        try:
            return max(1, int(_attr_text(node, "val")))
        except ValueError:
            return 1
    return 1


def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """读取 XLSX sharedStrings 表。"""

    xml_text = _read_zip_text(archive, "xl/sharedStrings.xml")
    if not xml_text:
        return []
    root = ElementTree.fromstring(xml_text)
    return [_normalize_text("".join(item.itertext())) for item in root if _local_name(item.tag) == "si"]


def _extract_xlsx_rows(
    *,
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    max_rows: int,
) -> list[list[str]]:
    """从 XLSX 工作表 XML 抽取样例行。"""

    root = ElementTree.fromstring(_read_zip_text(archive, sheet_path))
    rows: list[list[str]] = []
    for row in root.iter():
        if _local_name(row.tag) != "row":
            continue
        values: list[str] = []
        for cell in row:
            if _local_name(cell.tag) != "c":
                continue
            reference = str(cell.attrib.get("r") or "")
            match = re.match(r"([A-Z]+)", reference, flags=re.IGNORECASE)
            column_index = _xlsx_column_index(match.group(1)) if match else len(values)
            if column_index >= len(values):
                values.extend([""] * (column_index - len(values) + 1))
            values[column_index] = _xlsx_cell_value(cell=cell, shared_strings=shared_strings)
        if any(values):
            rows.append(values)
        if len(rows) >= max_rows:
            break
    return rows


def _xlsx_cell_value(*, cell: ElementTree.Element, shared_strings: list[str]) -> str:
    """解析 XLSX 单元格文本。"""

    cell_type = cell.attrib.get("t")
    value = ""
    for child in cell:
        if _local_name(child.tag) == "v":
            value = child.text or ""
            break
        if _local_name(child.tag) == "is":
            value = "".join(child.itertext())
            break
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    return value


def _xlsx_column_index(column_name: str) -> int:
    """把 XLSX 的 A/AA 列引用转换为从零开始的列索引。"""

    index = 0
    for character in column_name.upper():
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1
