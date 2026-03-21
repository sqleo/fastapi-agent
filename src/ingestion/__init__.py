"""文档解析流水线：检测类型 → 可配置工厂 → 转 Markdown。"""

from ingestion.async_parse import (
    describe_file_for_pipeline,
    parse_local_file_to_markdown_file,
)
from ingestion.detection import DocumentKind, detect_document_kind
from ingestion.exceptions import IngestionError, UnsupportedDocumentError
from ingestion.factory import ParserFactory, ParserFactoryConfig, default_allowed_extensions

__all__ = [
    "DocumentKind",
    "ParserFactory",
    "ParserFactoryConfig",
    "UnsupportedDocumentError",
    "IngestionError",
    "default_allowed_extensions",
    "detect_document_kind",
    "parse_local_file_to_markdown_file",
    "describe_file_for_pipeline",
]
