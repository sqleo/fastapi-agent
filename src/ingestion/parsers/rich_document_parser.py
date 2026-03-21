"""富文档（PDF/Office/图片等）→ Markdown：默认仅占位，可在此替换为自研或第三方解析。"""

from __future__ import annotations

from pathlib import Path

from ingestion.exceptions import UnsupportedDocumentError
from ingestion.parsers.base import DocumentToMarkdownParser


class PlaceholderRichDocumentParser(DocumentToMarkdownParser):
    """
    未接入真实解析引擎时的占位实现。

    需要支持 PDF/Office 等时：继承 ``DocumentToMarkdownParser`` 实现 ``to_markdown``，
    或在工厂中把 ``DocumentKind.RICH_DOCUMENT`` 映射到你的解析类。
    """

    async def to_markdown(self, path: Path) -> str:
        raise UnsupportedDocumentError(
            f"富文档解析未实现: {path.name}（请在 ingestion.parsers 中接入解析逻辑）"
        )
