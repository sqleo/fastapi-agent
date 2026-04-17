"""LlamaIndex ``IngestionPipeline`` 工厂：切块 → 嵌入 → 写入向量库."""

from __future__ import annotations

from typing import Any

from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.ingestion.pipeline import DocstoreStrategy
from llama_index.core.node_parser import SentenceSplitter

from llamarag.local_model.embed_model import embed_model
from llamarag.storage.postgres_llamaindex import get_llamaindex_docstore
from llamarag.storage.vector_store import vector_store


def ingestion_pipeline() -> IngestionPipeline:
    """默认管线：切块 + 嵌入 + Milvus；若配置 ``LLAMAINDEX_POSTGRES_URI`` 则同时写 Postgres docstore。"""
    docstore = get_llamaindex_docstore()
    kwargs: dict[str, Any] = {
        "transformations": [
            SentenceSplitter(chunk_size=512, chunk_overlap=20),
            embed_model,
        ],
        "vector_store": vector_store,
    }
    if docstore is not None:
        kwargs["docstore"] = docstore
        kwargs["docstore_strategy"] = DocstoreStrategy.UPSERTS
    return IngestionPipeline(**kwargs)


def build_ingestion_pipeline() -> IngestionPipeline:
    """与 ``ingestion_pipeline`` 同义，兼容旧命名."""
    return ingestion_pipeline()