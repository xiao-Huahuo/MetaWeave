"""
PDF 文本层清洗回归测试。

使用说明：定向运行 ``pytest tests/test_pdf_cleaner.py -q``，验证 PDF 表格会输出为
可渲染的 Markdown 表格，且不会同时保留一份纵向展开的重复文本。
"""

from pathlib import Path

from agent_service.services.memory.rag.pdf_cleaner import extract_pdf_text


def test_pdf_table_is_markdown_and_not_duplicated_as_flat_text() -> None:
    """课程成绩表应保留行列结构，且每个学号只在表格中出现一次。"""

    source = Path("tests/测试文件/多模态转md测试/pdf/2024计算机科学与技术.pdf")

    extracted = extract_pdf_text(source)

    assert extracted.table_count >= 1
    assert "| 学号 | 专业排名组 | 课程学习成绩 | 实践创新能力 | 综合成绩 |" in extracted.content
    assert "| --- | --- | --- | --- | --- | --- |" in extracted.content
    assert extracted.content.count("2024302111169") == 1
