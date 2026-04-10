"""文档 → 中间 Markdown（``static/parsed_md/``）解析策略与注册."""

from parsing.base import IntermediateMdGenerator
from parsing.exceptions import UnsupportedDocumentFormatError
from parsing.markdown import MarkdownIntermediateMdGenerator
from parsing.registry import get_intermediate_md_generator_for_ext

__all__ = [
    "IntermediateMdGenerator",
    "UnsupportedDocumentFormatError",
    "MarkdownIntermediateMdGenerator",
    "get_intermediate_md_generator_for_ext",
]
