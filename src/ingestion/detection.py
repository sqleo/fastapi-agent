"""根据路径与可选 MIME 判断文档类别，供工厂选择解析器。"""

from __future__ import annotations

import mimetypes
from enum import Enum
from pathlib import Path


class DocumentKind(str, Enum):
    """粗粒度文档类型（与解析实现对应，非 MIME 全集）。"""

    PLAIN_TEXT = "plain_text" # .txt
    MARKDOWN = "markdown" # .md, .markdown
    # PDF / Office / 常见图片等：需单独接入解析实现（本仓库默认仅占位）
    RICH_DOCUMENT = "rich_document" 
    PDF_PPT_IMAGE = "pdf_image" # .pdf, .png, .jpg, .jpeg, .jpe, .webp, .bmp, .gif, .tiff, .tif
    DOCX = "docx" # .docx
    UNKNOWN = "unknown"


# 常见「富文档」后缀（与具体解析引擎无关，仅用于分类）
RICH_FLASH_STYLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".jpe",
        ".webp",
        ".bmp",
        ".xls",
        ".xlsx",
        ".tiff",
        ".tif",
        ".doc",
        ".docx",
    }
)

RICH_EXTRA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".doc",
        ".ppt",
        ".html",
        ".htm",
    }
)

PLAIN_TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt"})
MARKDOWN_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown"})


def all_rich_document_extensions() -> frozenset[str]:
    """工程内归类为「富文档」的全部扩展名。"""
    return RICH_FLASH_STYLE_EXTENSIONS | RICH_EXTRA_EXTENSIONS


def detect_document_kind(path: Path) -> DocumentKind:
    """根据后缀判断文档类别（优先扩展名）。"""
    ext = path.suffix.lower()
    if ext in MARKDOWN_EXTENSIONS:
        return DocumentKind.MARKDOWN
    if ext in PLAIN_TEXT_EXTENSIONS:
        return DocumentKind.PLAIN_TEXT
    if ext in all_rich_document_extensions():
        return DocumentKind.RICH_DOCUMENT
    return DocumentKind.UNKNOWN


def guess_mime_type(path: Path) -> str | None:
    """辅助信息：``mimetypes`` 推测 MIME，可能为 None。"""
    mime, _ = mimetypes.guess_type(str(path))
    return mime
