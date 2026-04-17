"""LlamaRAG：IngestionPipeline 工厂 + 知识库文件入库."""

from __future__ import annotations

from llamarag.ingestion.index_kb_file import index_parsed_md_for_kb_file_sync
from llamarag.ingestion.pipeline import build_ingestion_pipeline, ingestion_pipeline

__all__ = [
    "build_ingestion_pipeline",
    "index_parsed_md_for_kb_file_sync",
    "ingestion_pipeline",
]
