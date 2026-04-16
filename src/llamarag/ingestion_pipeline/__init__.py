"""LlamaRAG：IngestionPipeline 封装（切块 → ``BaseNode``）."""

from __future__ import annotations

from llamarag.ingestion.pipeline import build_ingestion_pipeline, ingestion_pipeline

__all__ = [
    "build_ingestion_pipeline",
    "ingestion_pipeline",
]
