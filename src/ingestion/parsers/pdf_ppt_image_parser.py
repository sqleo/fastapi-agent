from pathlib import Path
from ingestion.parsers.base import DocumentToMarkdownParser


class PDF_PPT_ImageParser(DocumentToMarkdownParser):
    """``.pdf``, ``.pptx``, ``.png``, ``.jpg``, ``.jpeg``, ``.jpe``, ``.webp``, ``.bmp``：原样读入；可视为后续清洗步骤的输入。"""

    async def to_markdown(self, path: Path) -> str:
        return "PDF_PPT_ImageParser"