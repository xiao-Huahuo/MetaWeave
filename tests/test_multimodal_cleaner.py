"""
多模态知识源清洗测试。

功能说明:
验证多模态清洗器可以把表格、JSON 和 Office Open XML 文件转换为统一章节,
并能被 FrontmatterBootstrapService 写成结构化知识 JSON。
"""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

from agent_service.core.agent_config import AgentConfig
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.frontmatter_document import StructuredKnowledgeDocument, StructuredKnowledgeSection
from agent_service.services.memory.rag.knowledge_ingestion import KnowledgeIngestionService
from agent_service.services.memory.rag.image_ocr import ImageOcrResult
from agent_service.services.memory.rag.image_ocr import ImageOcrService
import agent_service.services.memory.rag.multimodal_cleaner as multimodal_cleaner_module
from agent_service.services.memory.rag.multimodal_cleaner import MultimodalDocumentCleaner
from agent_service.services.memory.rag.pdf_cleaner import PdfExtractionResult
from agent_service.services.knowledge_library import KnowledgeIgnoreMatcher


def test_image_ocr_parses_paddleocr_v3_nested_result() -> None:
    """PaddleOCR 3.x 的 OCRResult.json.res 结构应能进入统一文本结果。"""

    config = AgentConfig.load_config({"ocr": {"enabled": False}}, load_env=False, ensure_directories=False, ensure_models=False)
    service = ImageOcrService(config=config, enabled=True)
    items = service._collect_items({"res": {"rec_texts": ["标题", "内容"], "rec_scores": [0.99, 0.8]}})

    assert [item["text"] for item in items] == ["标题", "内容"]
    assert items[0]["confidence"] == 0.99


def test_docx_embedded_image_ocr_is_ingested(tmp_path: Path) -> None:
    """DOCX 的 word/media 图片启用 OCR 后应生成可检索章节。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="ocr.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:body>'
            '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
            '</w:body></w:document>'
        ),
        rels_xml=(
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            '</Relationships>'
        ),
    )
    with zipfile.ZipFile(docx_path, "a") as archive:
        archive.writestr("word/media/image1.png", b"fake-png")

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            assert source_path.exists()
            return ImageOcrResult(content="嵌入图片文字", has_text=True, word_count=1, average_confidence=0.9, engine_available=True)

    cleaned = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService()).clean(source_path=docx_path, title="ocr")

    assert any("嵌入图片文字" in section.content for section in cleaned.sections)


def test_scanned_pdf_embedded_image_ocr_is_ingested(tmp_path: Path) -> None:
    """扫描型 PDF 的页面图片启用 OCR 后应追加识别文本。"""

    import fitz  # type: ignore[import-untyped]

    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(0, 0, 72, 72), stream=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
    document.save(pdf_path)
    document.close()

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            assert source_path.exists()
            return ImageOcrResult(content="扫描件识别内容", has_text=True, word_count=1, average_confidence=0.95, engine_available=True)

    cleaned = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService()).clean(source_path=pdf_path, title="scan")

    assert "扫描件识别内容" in cleaned.sections[0].content
    assert cleaned.metadata["image_refs"][0]["ocr_status"] == "completed"


def test_cleaner_extracts_csv_and_json_sections(tmp_path: Path) -> None:
    """CSV 和 JSON 应清洗为可检索文本章节。"""

    csv_path = tmp_path / "people.csv"
    csv_path.write_text("name,role\nAlice,Engineer\nBob,Designer\n", encoding="utf-8")
    json_path = tmp_path / "profile.json"
    json_path.write_text(json.dumps({"project": "MetaWeave", "owner": "Alice"}), encoding="utf-8")
    cleaner = MultimodalDocumentCleaner()

    csv_doc = cleaner.clean(source_path=csv_path, title="people")
    json_doc = cleaner.clean(source_path=json_path, title="profile")

    assert csv_doc.source_type == "table"
    assert "Alice | Engineer" in csv_doc.sections[0].content
    assert json_doc.source_type == "json"
    assert '"project": "MetaWeave"' in json_doc.sections[0].content


def test_cleaner_extracts_docx_and_xlsx_sections(tmp_path: Path) -> None:
    """DOCX 段落/表格和 XLSX 工作表应被抽取为章节文本。"""

    docx_path = tmp_path / "demo.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>项目说明段落</w:t></w:r></w:p>
                <w:tbl>
                  <w:tr><w:tc><w:p><w:r><w:t>列A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>列B</w:t></w:r></w:p></w:tc></w:tr>
                  <w:tr><w:tc><w:p><w:r><w:t>值1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>值2</w:t></w:r></w:p></w:tc></w:tr>
                </w:tbl>
              </w:body>
            </w:document>
            """,
        )
    xlsx_path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(xlsx_path, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row><c t="inlineStr"><is><t>城市</t></is></c><c t="inlineStr"><is><t>分数</t></is></c></row>
                <row><c t="inlineStr"><is><t>璃月</t></is></c><c><v>95</v></c></row>
              </sheetData>
            </worksheet>
            """,
        )
    cleaner = MultimodalDocumentCleaner()
    docx_progress: list[dict[str, object]] = []

    docx_doc = cleaner.clean(source_path=docx_path, title="demo", progress_callback=docx_progress.append)
    xlsx_doc = cleaner.clean(source_path=xlsx_path, title="book")

    assert docx_doc.source_type == "docx"
    assert any("项目说明段落" in section.content for section in docx_doc.sections)
    assert any("值1 | 值2" in section.content for section in docx_doc.sections)
    assert any(event.get("stage") == "document_blocks" and event.get("stage_total") == 2 for event in docx_progress)
    assert xlsx_doc.source_type == "spreadsheet"
    assert "璃月 | 95" in xlsx_doc.sections[0].content


def _build_docx(*, directory: Path, name: str, body_xml: str, rels_xml: str | None = None) -> Path:
    """在临时目录构造一个最小 DOCX,便于清洗测试直接构造各类结构。"""

    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", body_xml)
        if rels_xml:
            archive.writestr("word/_rels/document.xml.rels", rels_xml)
    return path


def test_docx_embedded_image_ocr_preserves_document_order(tmp_path: Path) -> None:
    """DOCX 图片 OCR 文本应按原文档位置合并,不能追加到文末。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="ordered_ocr.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>图片前文本</w:t></w:r></w:p>"
            '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>'
            "<w:p><w:r><w:t>图片后文本</w:t></w:r></w:p>"
            "</w:body></w:document>"
        ),
        rels_xml=(
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            "</Relationships>"
        ),
    )
    with zipfile.ZipFile(docx_path, "a") as archive:
        archive.writestr("word/media/image1.png", b"fake-png")

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            assert source_path.name == "image1.png"
            return ImageOcrResult(content="图片内文字", has_text=True, word_count=1, average_confidence=0.9, engine_available=True)

    cleaned = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService()).clean(source_path=docx_path, title="ordered_ocr")

    assert cleaned.sections[0].content == "图片前文本\n\n图片 OCR: 图片内文字\n\n图片后文本"


def test_cleaner_docx_preserves_order_and_avoids_table_duplication(tmp_path: Path) -> None:
    """DOCX 段落-表格-段落应按原文顺序成章,且表格单元格文本不重复计入段落。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="ordered.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>表格前段落</w:t></w:r></w:p>"
            "<w:tbl><w:tr>"
            "<w:tc><w:p><w:r><w:t>单元格A</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>单元格B</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
            "<w:p><w:r><w:t>表格后段落</w:t></w:r></w:p>"
            "</w:body></w:document>"
        ),
    )
    cleaned = MultimodalDocumentCleaner().clean(source_path=docx_path, title="ordered")

    assert [section.content for section in cleaned.sections] == [
        "表格前段落",
        "单元格A | 单元格B",
        "表格后段落",
    ]


def test_cleaner_docx_splits_sections_by_heading_style(tmp_path: Path) -> None:
    """DOCX Heading1/Heading2 样式应按层级切分章节并生成 title_path。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="headed.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>概述内容</w:t></w:r></w:p>"
            '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>1.1 小节</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>小节内容</w:t></w:r></w:p>"
            "</w:body></w:document>"
        ),
    )
    cleaned = MultimodalDocumentCleaner().clean(source_path=docx_path, title="headed")

    assert [section.heading for section in cleaned.sections] == ["第一章", "1.1 小节"]
    assert [section.content for section in cleaned.sections] == ["概述内容", "小节内容"]
    assert cleaned.sections[0].title_path == ["headed", "第一章"]
    assert cleaned.sections[1].title_path == ["headed", "第一章", "1.1 小节"]


def test_cleaner_docx_resolves_image_relationship_ids(tmp_path: Path) -> None:
    """DOCX 图片引用应从裸 rId 升级为 rels 映射的真实媒体路径。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="with_image.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>带图段落</w:t></w:r><w:r>"
            '<w:drawing><a:blip r:embed="rId5"/></w:drawing>'
            "</w:r></w:p>"
            "</w:body></w:document>"
        ),
        rels_xml=(
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            "</Relationships>"
        ),
    )
    cleaned = MultimodalDocumentCleaner().clean(source_path=docx_path, title="with_image")

    assert cleaned.metadata["image_refs"] == ["[DOCX 图片引用: media/image1.png]"]
    assert any("media/image1.png" in section.content for section in cleaned.sections)
    assert not any("image relationship: rId5" in section.content for section in cleaned.sections)


def test_cleaner_docx_plain_paragraphs_single_section(tmp_path: Path) -> None:
    """无标题、无表格的 DOCX 仍应聚成单一章节,保持旧行为。"""

    docx_path = _build_docx(
        directory=tmp_path,
        name="plain.docx",
        body_xml=(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>第一段</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>第二段</w:t></w:r></w:p>"
            "</w:body></w:document>"
        ),
    )
    cleaned = MultimodalDocumentCleaner().clean(source_path=docx_path, title="plain")

    assert len(cleaned.sections) == 1
    assert cleaned.sections[0].heading == "plain"
    assert cleaned.sections[0].content == "第一段\n\n第二段"


def test_cleaner_extracts_text_layer_pdf(tmp_path: Path) -> None:
    """非扫描型 PDF 应优先提取文本层进入可检索章节。"""

    import fitz  # type: ignore[import-untyped]

    pdf_path = tmp_path / "demo.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF text layer content with enough searchable characters")
    document.save(pdf_path)
    document.close()

    cleaned = MultimodalDocumentCleaner().clean(source_path=pdf_path, title="demo")

    assert cleaned.source_type == "pdf"
    assert cleaned.metadata["pdf_scanned"] is False
    assert "PDF text layer content" in cleaned.sections[0].content


def test_cleaner_preserves_pdf_image_refs(tmp_path: Path) -> None:
    """PDF images should be kept as page-relative refs without OCR."""

    import fitz  # type: ignore[import-untyped]

    pdf_path = tmp_path / "image.pdf"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF image order")
    page.insert_image(fitz.Rect(72, 96, 120, 144), stream=png_bytes)
    document.save(pdf_path)
    document.close()

    cleaned = MultimodalDocumentCleaner().clean(source_path=pdf_path, title="image")

    assert cleaned.source_type == "pdf"
    assert cleaned.metadata["image_count"] == 1
    assert cleaned.metadata["image_refs"][0]["page"] == 1
    assert cleaned.metadata["image_refs"][0]["bbox"] == [72.0, 96.0, 120.0, 144.0]
    assert "[PDF 图片引用: image 1" in cleaned.sections[0].content


def test_pdf_image_ocr_replaces_inline_render_placeholder(tmp_path: Path, monkeypatch) -> None:
    """PDF 图片 OCR 文本应替换原图片占位,保持与文本层的页内顺序。"""

    pdf_path = tmp_path / "inline.pdf"
    image_path = tmp_path / "image-1.png"
    pdf_path.write_bytes(b"%PDF-1.4")
    image_path.write_bytes(b"fake image")

    def fake_extract_pdf_text(*args: object, **kwargs: object) -> PdfExtractionResult:
        return PdfExtractionResult(
            content="## Page 1\n\n前置文本\n\n![PDF page 1 image 1](/knowledge/assets/pdf_preview/demo/image-1.png)\n\n后置文本",
            page_count=1,
            image_count=1,
            table_count=0,
            is_scanned=False,
            image_refs=[
                {
                    "page": 1,
                    "index": 1,
                    "asset_path": str(image_path),
                    "public_url": "/knowledge/assets/pdf_preview/demo/image-1.png",
                }
            ],
        )

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            assert source_path == image_path
            return ImageOcrResult(content="图片 OCR 内容", has_text=True, word_count=3, average_confidence=0.92, engine_available=True)

    monkeypatch.setattr(multimodal_cleaner_module, "extract_pdf_text", fake_extract_pdf_text)
    cleaned = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService()).clean(source_path=pdf_path, title="inline")

    assert cleaned.sections[0].content == "## Page 1\n\n前置文本\n\nPDF 图片 OCR: 图片 OCR 内容\n\n后置文本"
    assert cleaned.metadata["image_refs"][0]["ocr_status"] == "completed"


def test_frontmatter_bootstrap_writes_pdf_image_markdown(tmp_path: Path) -> None:
    """PDF images should be exported as assets and rendered through Markdown."""

    import fitz  # type: ignore[import-untyped]

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    runtime_dir = tmp_path / "runtime"
    knowledge_dir.mkdir()
    pdf_path = knowledge_dir / "scan.pdf"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(0, 0, 72, 72), stream=png_bytes)
    document.save(pdf_path)
    document.close()
    config = AgentConfig.load_config(
        {
            "storage": {
                "base_data_dir": runtime_dir,
                "knowledge_dir": knowledge_dir,
                "frontmatter_dir": frontmatter_dir,
            }
        },
        load_env=False,
        ensure_directories=True,
        ensure_models=False,
    )
    service = FrontmatterBootstrapService(config=config)

    result, output_path = service.build_frontmatter_file(source_path=pdf_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    image_ref = payload["metadata"]["image_refs"][0]
    assert result.files_written == 1
    assert payload["metadata"]["pdf_scanned"] is True
    assert "## Page 1" in payload["markdown"]
    assert "![PDF page 1 image 1]" in payload["sections"][0]["content"]
    assert image_ref["index"] == 1
    assert image_ref["page"] == 1
    assert image_ref["xref"] == 5
    assert image_ref["ext"] == "png"


def test_cleaner_extracts_image_ocr_text(tmp_path: Path) -> None:
    """图片 OCR 命中文本时应生成可检索章节。"""

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            assert source_path.name == "table.png"
            return ImageOcrResult(
                content="姓名 | 分数\nAlice | 98",
                has_text=True,
                word_count=4,
                average_confidence=91.0,
                engine_available=True,
            )

    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"fake image bytes")
    cleaner = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService())

    cleaned = cleaner.clean(source_path=image_path, title="table")

    assert cleaned.source_type == "image"
    assert cleaned.metadata["ocr_status"] == "completed"
    assert "Alice | 98" in cleaned.sections[0].content


def test_cleaner_skips_image_without_ocr_text(tmp_path: Path) -> None:
    """图片没有 OCR 文本时不应生成语义章节。"""

    class FakeOcrService:
        def extract_image_text(self, source_path: Path, progress_callback=None) -> ImageOcrResult:
            return ImageOcrResult(has_text=False, engine_available=True)

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"fake image bytes")
    cleaner = MultimodalDocumentCleaner(ocr_enabled=True, image_ocr_service=FakeOcrService())

    cleaned = cleaner.clean(source_path=image_path, title="photo")

    assert cleaned.source_type == "image"
    assert cleaned.metadata["ocr_status"] == "no_text"
    assert cleaned.sections == []


def test_frontmatter_bootstrap_writes_multimodal_json(tmp_path: Path) -> None:
    """结构化预处理应扫描配置白名单内的多模态文件并输出 JSON。"""

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    knowledge_dir.mkdir()
    (knowledge_dir / "table.csv").write_text("k,v\nalpha,beta\n", encoding="utf-8")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = FrontmatterBootstrapService(config=config)

    result = service.build_frontmatter_dir(
        knowledge_dir=knowledge_dir,
        frontmatter_dir=frontmatter_dir,
        supported_suffixes={".csv"},
    )

    payload = json.loads((frontmatter_dir / "table.json").read_text(encoding="utf-8"))
    assert result.files_seen == 1
    assert result.files_written == 1
    assert payload["source_type"] == "table"
    assert payload["metadata"]["modality"] == "table"
    assert "alpha | beta" in payload["sections"][0]["content"]


def test_frontmatter_bootstrap_persists_markdown_before_json_under_mw(tmp_path: Path) -> None:
    """Every modality must persist a mirrored Markdown projection before JSON is derived."""

    knowledge_dir = tmp_path / "knowledge"
    source_dir = knowledge_dir / "papers" / "2026"
    source_dir.mkdir(parents=True)
    (source_dir / "table.csv").write_text("name,value\nalpha,beta\n", encoding="utf-8")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)

    result = FrontmatterBootstrapService(config=config).build_frontmatter_dir(
        knowledge_dir=knowledge_dir,
        frontmatter_dir=knowledge_dir / ".mw" / "frontmatter",
        markdown_dir=knowledge_dir / ".mw" / "md",
        supported_suffixes={".csv"},
    )

    markdown_path = knowledge_dir / ".mw" / "md" / "papers" / "2026" / "table.md"
    json_path = knowledge_dir / ".mw" / "frontmatter" / "papers" / "2026" / "table.json"
    markdown = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    reparsed = FrontmatterBootstrapService._build_markdown_sections(
        title=payload["title"],
        body_text=markdown,
    )

    assert result.files_written == 1
    assert "| name | value |" in markdown
    assert "| --- | --- |" in markdown
    assert payload["schema_version"] == 2
    assert payload["markdown"] == markdown
    assert payload["projection_hash"]
    assert [section.content for section in reparsed] == [section["content"] for section in payload["sections"]]


def test_frontmatter_bootstrap_ingests_unknown_text_suffix(tmp_path: Path) -> None:
    """Unknown suffix text files should still enter the text ingestion path."""

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    knowledge_dir.mkdir()
    (knowledge_dir / ".env").write_text("METAWEAVE_MODE=dev\n", encoding="utf-8")
    (knowledge_dir / "image.unknown").write_bytes(b"\x00\x01\x02\x03")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = FrontmatterBootstrapService(config=config)

    result = service.build_frontmatter_dir(
        knowledge_dir=knowledge_dir,
        frontmatter_dir=frontmatter_dir,
        supported_suffixes={".md"},
    )

    payload = json.loads((frontmatter_dir / ".env.json").read_text(encoding="utf-8"))
    assert result.files_seen == 1
    assert result.files_written == 1
    assert payload["source_type"] == "text"
    assert payload["metadata"]["modality"] == "text"
    assert "METAWEAVE_MODE=dev" in payload["sections"][0]["content"]
    assert not (frontmatter_dir / "image.json").exists()


def test_frontmatter_bootstrap_ingests_supported_tex_as_text(tmp_path: Path) -> None:
    """`.tex` 加入知识白名单后仍必须走文本管线，不能误入多模态清洗器。"""

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    knowledge_dir.mkdir()
    (knowledge_dir / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}Knowledge text\\end{document}\n",
        encoding="utf-8",
    )
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = FrontmatterBootstrapService(config=config)

    result = service.build_frontmatter_dir(
        knowledge_dir=knowledge_dir,
        frontmatter_dir=frontmatter_dir,
        supported_suffixes={".tex"},
    )

    payload = json.loads((frontmatter_dir / "paper.json").read_text(encoding="utf-8"))
    assert result.files_written == 1
    assert payload["metadata"]["modality"] == "text"
    assert "Knowledge text" in payload["sections"][0]["content"]


def test_frontmatter_bootstrap_rejects_unknown_binary_single_file(tmp_path: Path) -> None:
    """Single-file ingestion should skip unknown binary formats instead of parsing them."""

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    knowledge_dir.mkdir()
    binary_path = knowledge_dir / "archive.weird"
    binary_path.write_bytes(b"PK\x00\x01\x02\x03")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = FrontmatterBootstrapService(config=config)

    try:
        service.build_frontmatter_file(
            source_path=binary_path,
            knowledge_dir=knowledge_dir,
            frontmatter_dir=frontmatter_dir,
            supported_suffixes={".md"},
        )
    except ValueError as exc:
        assert "unsupported binary" in str(exc)
    else:
        raise AssertionError("unknown binary file should be rejected")


def test_global_frontmatter_bootstrap_excludes_user_library_subtree(tmp_path: Path) -> None:
    """启动全局结构化不应重复扫描 editor 用户知识库子树。"""

    knowledge_dir = tmp_path / "knowledge"
    frontmatter_dir = tmp_path / "frontmatter"
    user_library_dir = knowledge_dir / "1" / "1"
    user_library_dir.mkdir(parents=True)
    (knowledge_dir / "global.md").write_text("global content", encoding="utf-8")
    (user_library_dir / "local.md").write_text("local content", encoding="utf-8")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = FrontmatterBootstrapService(config=config)

    result = service.build_frontmatter_dir(
        knowledge_dir=knowledge_dir,
        frontmatter_dir=frontmatter_dir,
        supported_suffixes={".md"},
        exclude_path=lambda path: path.resolve().is_relative_to(user_library_dir.resolve()),
    )

    assert result.files_seen == 1
    assert result.files_written == 1
    assert (frontmatter_dir / "global.json").is_file()
    assert not (frontmatter_dir / "1" / "1" / "local.json").exists()


def test_global_ingestion_excludes_stale_user_frontmatter_subtree(tmp_path: Path) -> None:
    """历史误写入全局 frontmatter 的用户库 JSON 不应在启动入库时被消费。"""

    class FakeEmbeddingService:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    class FakeMemoryService:
        def __init__(self) -> None:
            self.created: list[object] = []

        def has_source_hash(self, **kwargs: object) -> bool:
            return False

        def delete_memories_for_source(self, **kwargs: object) -> int:
            return 0

        def create_memory(self, memory_create: object) -> None:
            self.created.append(memory_create)

    frontmatter_dir = tmp_path / "frontmatter"
    global_json = frontmatter_dir / "global.json"
    stale_user_json = frontmatter_dir / "1" / "1" / "local.json"
    global_json.parent.mkdir(parents=True)
    stale_user_json.parent.mkdir(parents=True)

    def write_doc(path: Path, document_id: str, title: str) -> None:
        doc = StructuredKnowledgeDocument(
            document_id=document_id,
            source_type="markdown",
            source_path=str(path),
            source_uri=str(path),
            source_hash=document_id,
            title=title,
            summary="",
            tags=[],
            authority=0.7,
            valid_from=None,
            valid_until=None,
            sections=[
                StructuredKnowledgeSection(
                    section_id="sec_0000",
                    heading=title,
                    title_path=[title],
                    content=f"{title} content",
                    start_char=0,
                    end_char=len(f"{title} content"),
                )
            ],
        )
        path.write_text(json.dumps(doc.to_dict(), ensure_ascii=False), encoding="utf-8")

    write_doc(global_json, "global", "global")
    write_doc(stale_user_json, "local", "local")
    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    service = KnowledgeIngestionService(
        config=config,
        embedding_service=FakeEmbeddingService(),
        memory_service=FakeMemoryService(),
    )

    result = service.ingest_frontmatter_dir(
        frontmatter_dir=frontmatter_dir,
    )

    assert result.files_seen == 2
    assert result.files_ingested == 2
    assert result.source_ids_seen == {"global", "local"}


def test_global_ingestion_scan_skips_user_frontmatter_subtree(tmp_path: Path) -> None:
    """启动全局灌库不应递归吃掉用户隔离 frontmatter 输出。"""

    frontmatter_dir = tmp_path / "frontmatter"
    global_json = frontmatter_dir / "global.json"
    user_json = frontmatter_dir / "users" / "1" / "kb_demo" / "local.json"
    global_json.parent.mkdir(parents=True)
    user_json.parent.mkdir(parents=True)
    global_json.write_text("{}", encoding="utf-8")
    user_json.write_text("{}", encoding="utf-8")

    config = AgentConfig.load_config(load_env=False, ensure_directories=False, ensure_models=False)
    config.storage.frontmatter_dir = frontmatter_dir
    service = object.__new__(KnowledgeIngestionService)
    service.config = config

    global_scan = service._iter_frontmatter_files(frontmatter_dir)
    user_scan = service._iter_frontmatter_files(user_json.parent)

    assert global_scan == [global_json.resolve()]
    assert user_scan == [user_json.resolve()]


def test_document_id_keeps_chinese_filename_paths_distinct() -> None:
    """中文文件名不能因 slug 清洗而生成相同 document_id。"""

    first = FrontmatterBootstrapService._build_document_id(Path("1/2/test/带图word.docx"))
    second = FrontmatterBootstrapService._build_document_id(Path("1/2/test/简单word.docx"))

    assert first != second
    assert first.startswith("doc_")
    assert second.startswith("doc_")


def test_knowledge_ignore_matcher_supports_gitignore_subset() -> None:
    """屏蔽规则支持目录、通配符和反向取消。"""

    matcher = KnowledgeIgnoreMatcher(
        """
        # private data
        private/
        *.tmp
        !private/keep.md
        """
    )

    assert matcher.is_ignored("private/a.pdf")
    assert matcher.is_ignored("nested/file.tmp")
    assert not matcher.is_ignored("private/keep.md")
    assert not matcher.is_ignored("docs/readme.md")


def test_knowledge_ignore_matcher_hard_ignores_every_dot_directory() -> None:
    """任意层级点目录都是不可被反向规则取消的灌库忽略目录。"""

    matcher = KnowledgeIgnoreMatcher(
        """
        !.agents/skills/demo/SKILL.md
        """
    )

    assert matcher.is_ignored(".agents", is_dir=True)
    assert matcher.is_ignored(".agents/skills/demo/SKILL.md")
    assert matcher.is_ignored("nested/.agents/skills/demo/SKILL.md")
    assert matcher.is_ignored("nested/.cache/draft.md")
