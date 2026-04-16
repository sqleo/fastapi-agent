"""解析流水线异常."""


class UnsupportedDocumentFormatError(ValueError):
    """当前未为该后缀实现中间 Markdown 生成（可后续接入 PDF/DOCX 等）."""
