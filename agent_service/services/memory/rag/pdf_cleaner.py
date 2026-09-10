"""
PDF text-layer extraction helpers.

The cleaner intentionally does not run OCR. For PDFs with embedded images it
keeps lightweight image references so downstream frontmatter can preserve the
page-relative structure without treating images as semantic text.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS


@dataclass(slots=True)
class PdfExtractionResult:
    """Result produced by text-layer PDF extraction."""

    content: str
    page_count: int
    image_count: int
    table_count: int
    is_scanned: bool
    image_refs: list[dict[str, Any]] = field(default_factory=list)


def extract_pdf_text(
    source_path: Path,
    *,
    scanned_text_threshold: int = DEFAULT_BUSINESS_LIMITS.scanned_pdf_text_threshold,
    image_output_dir: Path | None = None,
    image_public_prefix: str = "",
    progress_callback: Callable[[int, int], None] | None = None,
) -> PdfExtractionResult:
    """Extract text, simple tables, and image references from a PDF."""

    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("缺少 PyMuPDF 依赖,无法解析 PDF 文本层。") from exc

    if image_output_dir is not None:
        shutil.rmtree(image_output_dir, ignore_errors=True)
        image_output_dir.mkdir(parents=True, exist_ok=True)

    page_chunks: list[str] = []
    semantic_text_parts: list[str] = []
    image_refs: list[dict[str, Any]] = []
    table_count = 0
    with fitz.open(source_path) as document:
        page_count = int(document.page_count)
        for page_index, page in enumerate(document, start=1):
            lines: list[str] = []
            table_lines, page_table_count, table_regions = _extract_page_tables(page)
            page_text = _extract_page_text(page, table_regions)
            if page_text:
                lines.append(page_text)
                semantic_text_parts.append(page_text)
            if table_lines:
                table_count += page_table_count
                table_text = "\n".join(table_lines)
                lines.append(table_text)
                semantic_text_parts.append(table_text)
            page_image_refs = _extract_page_image_refs(
                document=document,
                page=page,
                page_index=page_index,
                start_index=len(image_refs),
                image_output_dir=image_output_dir,
                image_public_prefix=image_public_prefix,
            )
            image_refs.extend(page_image_refs)
            if page_image_refs:
                lines.append(_format_image_refs(page_image_refs))
            if lines:
                page_chunks.append(f"## Page {page_index}\n\n" + "\n\n".join(lines))
            if progress_callback:
                progress_callback(page_index, page_count)
    content = "\n\n".join(page_chunks).strip()
    text_size = len("".join("\n".join(semantic_text_parts).split()))
    return PdfExtractionResult(
        content=content,
        page_count=page_count,
        image_count=len(image_refs),
        table_count=table_count,
        is_scanned=text_size < scanned_text_threshold,
        image_refs=image_refs,
    )


def _extract_page_tables(page: Any) -> tuple[list[str], int, list[tuple[float, float, float, float]]]:
    """Extract renderable Markdown tables and their page regions."""

    if not hasattr(page, "find_tables"):
        return [], 0, []
    try:
        table_finder = page.find_tables()
    except Exception:
        return [], 0, []
    tables = list(getattr(table_finder, "tables", []) or [])
    lines: list[str] = []
    regions: list[tuple[float, float, float, float]] = []
    for table_index, table in enumerate(tables, start=1):
        try:
            rows = table.extract()
        except Exception:
            continue
        formatted_table = _format_markdown_table(rows)
        if not formatted_table:
            continue
        lines.append(f"表格 {table_index}:\n\n{formatted_table}")
        bbox = getattr(table, "bbox", None)
        if bbox is not None:
            try:
                regions.append(tuple(float(value) for value in bbox))
            except (TypeError, ValueError):
                pass
    return lines, len(lines), regions


def _format_markdown_table(rows: list[list[Any]]) -> str:
    """Convert extracted cells into a rectangular GitHub-flavored Markdown table."""

    populated = [row for row in rows if any(str(cell or "").strip() for cell in row)]
    if not populated:
        return ""
    column_count = max(len(row) for row in populated)

    def format_cell(cell: Any) -> str:
        """Escape Markdown delimiters while preserving wrapped cell lines."""

        return "<br>".join(part.strip() for part in str(cell or "").splitlines()).replace("|", "\\|")

    def format_row(row: list[Any]) -> str:
        """Pad one extracted row to the detected table width."""

        cells = [format_cell(cell) for cell in row]
        cells.extend([""] * (column_count - len(cells)))
        return "| " + " | ".join(cells) + " |"

    return "\n".join([
        format_row(populated[0]),
        "| " + " | ".join(["---"] * column_count) + " |",
        *(format_row(row) for row in populated[1:]),
    ])


def _extract_page_text(page: Any, table_regions: list[tuple[float, float, float, float]]) -> str:
    """Keep prose blocks while excluding text already represented by detected tables."""

    if not table_regions:
        return (page.get_text("text") or "").strip()
    try:
        blocks = page.get_text("blocks") or []
    except Exception:
        return ""
    prose: list[str] = []
    for block in blocks:
        if len(block) < 5:
            continue
        center_x = (float(block[0]) + float(block[2])) / 2
        center_y = (float(block[1]) + float(block[3])) / 2
        if any(left <= center_x <= right and top <= center_y <= bottom for left, top, right, bottom in table_regions):
            continue
        text = str(block[4] or "").strip()
        if text:
            prose.append(text)
    return "\n\n".join(prose)


def _extract_page_image_refs(
    *,
    document: Any,
    page: Any,
    page_index: int,
    start_index: int,
    image_output_dir: Path | None,
    image_public_prefix: str,
) -> list[dict[str, Any]]:
    """Register image occurrences by page order without extracting OCR text."""

    refs: list[dict[str, Any]] = []
    try:
        images = page.get_images(full=True)
    except Exception:
        return refs
    for image in images:
        try:
            xref = int(image[0])
        except (TypeError, ValueError, IndexError):
            continue
        ext = _extract_image_extension(document=document, xref=xref)
        rects = _extract_image_rects(page=page, xref=xref) or [None]
        for occurrence_index, rect in enumerate(rects, start=1):
            image_index = start_index + len(refs) + 1
            ref: dict[str, Any] = {
                "index": image_index,
                "page": page_index,
                "xref": xref,
                "occurrence": occurrence_index,
            }
            if ext:
                ref["ext"] = ext
            if rect is not None:
                ref["bbox"] = [round(float(value), 2) for value in (rect.x0, rect.y0, rect.x1, rect.y1)]
            asset = _write_image_asset(
                document=document,
                xref=xref,
                image_index=image_index,
                ext=ext,
                image_output_dir=image_output_dir,
                image_public_prefix=image_public_prefix,
            )
            if asset:
                ref.update(asset)
            refs.append(ref)
    return refs


def _extract_image_extension(*, document: Any, xref: int) -> str:
    """Read the original embedded image extension when PyMuPDF can expose it."""

    try:
        payload = document.extract_image(xref)
    except Exception:
        return ""
    return str(payload.get("ext") or "").strip()


def _write_image_asset(
    *,
    document: Any,
    xref: int,
    image_index: int,
    ext: str,
    image_output_dir: Path | None,
    image_public_prefix: str,
) -> dict[str, str]:
    """Persist an embedded PDF image and return Markdown-loadable paths."""

    if image_output_dir is None:
        return {}
    try:
        payload = document.extract_image(xref)
        image_bytes = payload.get("image")
    except Exception:
        return {}
    if not image_bytes:
        return {}
    normalized_ext = (ext or str(payload.get("ext") or "") or "png").lower().lstrip(".")
    file_name = f"image_{image_index:04d}.{normalized_ext}"
    output_path = image_output_dir / file_name
    try:
        output_path.write_bytes(image_bytes)
    except OSError:
        return {}
    public_prefix = image_public_prefix.rstrip("/")
    public_url = f"{public_prefix}/{file_name}" if public_prefix else ""
    return {"asset_path": str(output_path), "public_url": public_url}


def _extract_image_rects(*, page: Any, xref: int) -> list[Any]:
    """Read image positions on the page when supported."""

    if not hasattr(page, "get_image_rects"):
        return []
    try:
        return list(page.get_image_rects(xref) or [])
    except Exception:
        return []


def _format_image_refs(image_refs: list[dict[str, Any]]) -> str:
    """Render image references into frontmatter-friendly text."""

    lines: list[str] = []
    for ref in image_refs:
        if ref.get("public_url"):
            lines.append(f"![PDF page {ref['page']} image {ref['index']}]({ref['public_url']})")
            continue
        parts = [f"image {ref['index']}", f"page={ref['page']}", f"xref={ref['xref']}"]
        if ref.get("ext"):
            parts.append(f"ext={ref['ext']}")
        if ref.get("bbox"):
            parts.append(f"bbox={ref['bbox']}")
        lines.append("[PDF 图片引用: " + ", ".join(parts) + "]")
    return "\n".join(lines)
