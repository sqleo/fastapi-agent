"""LlamaIndex ``MilvusVectorStore``；Milvus 连接来自环境变量，向量维度须与 ``EmbeddingConfig.dimensions`` 一致."""

from __future__ import annotations

from typing import Any

from pymilvus import DataType

from shared.embedding.config import FIXED_EMBEDDING_DIMENSION

# 与入库时写入的 node.metadata 键一致，便于 Milvus 标量过滤（检索侧）
RAG_SCALAR_FIELD_NAMES: tuple[str, ...] = (
    "kb_file_id",
    "knowledge_base_id",
    "file_id",
    "owner_user_id",
)
RAG_SCALAR_FIELD_TYPES: tuple[Any, ...] = (
    DataType.VARCHAR,
    DataType.INT64,
    DataType.INT64,
    DataType.INT64,
)


def build_milvus_vector_store(*, dim: int | None = None) -> Any:
    """构造 ``MilvusVectorStore``；``dim`` 默认与全局嵌入维度一致，入库/检索时应传入 ``EmbeddingConfig.dimensions``."""
    from llama_index.vector_stores.milvus import MilvusVectorStore

    from rag.config import (
        milvus_connection_kwargs,
        milvus_token,
        milvus_uri,
        rag_milvus_collection_name,
    )

    d = int(dim) if dim is not None else FIXED_EMBEDDING_DIMENSION
    extra = milvus_connection_kwargs()
    return MilvusVectorStore(
        uri=milvus_uri(),
        token=milvus_token(),
        collection_name=rag_milvus_collection_name(),
        dim=d,
        overwrite=False,
        upsert_mode=False,
        consistency_level="Strong",
        similarity_metric="IP",
        enable_sparse=False,
        scalar_field_names=list(RAG_SCALAR_FIELD_NAMES),
        scalar_field_types=list(RAG_SCALAR_FIELD_TYPES),
        **extra,
    )
