from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion.parsers.base import DocumentToMarkdownParser


class PDF_PPT_ImageParser(DocumentToMarkdownParser):
    """``.pdf``, ``.pptx``, ``.png``, …：占位实现。"""

    async def to_markdown(
        self,
        path: Path,
        *,
        markdown_out_path: Path | None = None,
        **kwargs: Any,
    ) -> str:
        return "PDF_PPT_ImageParser"