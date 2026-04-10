"""按文件后缀选择 ``IntermediateMdGenerator``."""

from __future__ import annotations

from parsing.base import IntermediateMdGenerator
from parsing.exceptions import UnsupportedDocumentFormatError
from parsing.markdown import MarkdownIntermediateMdGenerator


def get_intermediate_md_generator_for_ext(file_ext: str | None) -> IntermediateMdGenerator:
    """``file_ext`` 可为 ``md`` 或带点的 ``.md``（与 ``FileAssetModel.file_ext`` 一致）。"""
    ext = (file_ext or "").lower().strip().lstrip(".")
    if ext in ("md", "markdown", "mdx"):
        return MarkdownIntermediateMdGenerator()
    raise UnsupportedDocumentFormatError(
        f"暂不支持后缀 {ext!r} 的中间 Markdown 生成；当前仅 Markdown（md/markdown/mdx）"
    )
