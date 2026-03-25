"""按文档类型选择解析器；可通过配置限制「允许转成 MD 的扩展名」。"""
from dataclasses import dataclass
from pathlib import Path

from ingestion.detection import (
    DocumentKind,
    MARKDOWN_EXTENSIONS,
    PLAIN_TEXT_EXTENSIONS,
    all_rich_document_extensions,
    detect_document_kind,
)
from ingestion.exceptions import UnsupportedDocumentError
from ingestion.parsers.base import DocumentToMarkdownParser
from ingestion.parsers.plaintext_parser import MarkdownFileParser, PlainTextParser
from ingestion.parsers.rich_document_parser import UnstructuredRichDocumentParser


def default_allowed_extensions() -> frozenset[str]:
    """默认：纯文本 + Markdown + 富文档后缀（富文档由 MinerU / langchain-mineru 解析）。"""
    return (
        PLAIN_TEXT_EXTENSIONS
        | MARKDOWN_EXTENSIONS
        | all_rich_document_extensions()
    )


@dataclass
class ParserFactoryConfig:
    """
    工厂配置。

    ``allowed_extensions``：允许进入解析管线的后缀（小写、带点），例如 ``{".pdf", ".docx"}``。
    为 ``None`` 时使用 ``default_allowed_extensions()``。
    """

    allowed_extensions: frozenset[str] | None = None


class ParserFactory:
    """根据路径后缀与 ``DocumentKind`` 选择 ``DocumentToMarkdownParser`` 实现。"""

    def __init__(self, config: ParserFactoryConfig | None = None) -> None:
        self._config = config or ParserFactoryConfig()
        self._allowed = (
            self._config.allowed_extensions
            if self._config.allowed_extensions is not None
            else default_allowed_extensions()
        )

    @property
    def allowed_extensions(self) -> frozenset[str]:
        """当前白名单（可给 API 层展示）。"""
        return self._allowed

    def get_parser_for_path(self, path: Path) -> DocumentToMarkdownParser:
        """返回用于该文件的解析器；路径须为已存在文件。"""
        p = path.expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if not p.is_file():
            raise ValueError(f"路径不是文件: {p}")

        ext = p.suffix.lower()
        if ext not in self._allowed:
            raise UnsupportedDocumentError(
                f"扩展名 {ext!r} 未在工厂允许列表中；已配置: {sorted(self._allowed)}"
            )

        kind = detect_document_kind(p)
        if kind is DocumentKind.UNKNOWN:
            raise UnsupportedDocumentError(
                f"无法识别文档类型: {p.name}（扩展名 {ext!r}）"
            )

        if kind is DocumentKind.PLAIN_TEXT:
            return PlainTextParser()
        if kind is DocumentKind.MARKDOWN:
            return MarkdownFileParser()
        if kind is DocumentKind.RICH_DOCUMENT:
            return UnstructuredRichDocumentParser()

        raise UnsupportedDocumentError(f"未实现的文档类别: {kind}")

