"""纯文本 / Markdown 源文件：直接读入为字符串。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion.parsers.base import DocumentToMarkdownParser


class PlainTextParser(DocumentToMarkdownParser):
    """``.txt``：原样读入；可视为后续清洗步骤的输入。"""

    async def to_markdown(
        self,
        path: Path,
        *,
        markdown_out_path: Path | None = None,
        **kwargs: Any,
    ) -> str:
        return path.read_text(encoding="utf-8")


class MarkdownFileParser(DocumentToMarkdownParser):
    """``.md``：已是 Markdown，直接读入供后续清洗 / 切块。"""

    async def to_markdown(
        self,
        path: Path,
        *,
        markdown_out_path: Path | None = None,
        **kwargs: Any,
    ) -> str:
        return path.read_text(encoding="utf-8")
