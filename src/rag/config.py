"""RAG 运行时配置（环境变量）；与 ``services`` 解耦."""

from __future__ import annotations

import json
import os
from typing import Any


def milvus_uri() -> str:
    """Milvus gRPC/HTTP 地址，例如 ``localhost:19530`` 或 ``http://host:19530``."""
    return os.getenv("MILVUS_URI", "http://localhost:19530").strip()


def milvus_token() -> str:
    """``MILVUS_TOKEN``，或 ``MILVUS_USER`` + ``MILVUS_PASSWORD`` 拼成 ``user:password``。"""
    token = os.getenv("MILVUS_TOKEN", "").strip()
    if token:
        return token
    user = os.getenv("MILVUS_USER", "").strip()
    password = os.getenv("MILVUS_PASSWORD", "").strip()
    if user and password:
        return f"{user}:{password}"
    return ""


def milvus_connection_kwargs() -> dict[str, Any]:
    """传给 ``MilvusVectorStore`` / ``MilvusClient`` 的额外参数（如 ``db_name``）."""
    out: dict[str, Any] = {}
    db_name = os.getenv("MILVUS_DB_NAME", "").strip()
    if db_name:
        out["db_name"] = db_name
    return out


def milvus_collection_name() -> str:
    """逻辑上的集合名前缀（默认 ``MILVUS_COLLECTION`` 环境变量）。"""
    return os.getenv("MILVUS_COLLECTION", "MILVUS_COLLECTION").strip()


def rag_milvus_collection_name() -> str:
    """LlamaIndex ``MilvusVectorStore`` 写入的集合名；默认 ``{MILVUS_COLLECTION}_rag``。

    可显式设置 ``RAG_MILVUS_COLLECTION`` 覆盖。
    """
    explicit = os.getenv("RAG_MILVUS_COLLECTION", "").strip()
    if explicit:
        return explicit
    base = milvus_collection_name()
    return f"{base}_rag"


def chunk_size() -> int:
    """默认分块大小（字符或 token 策略由 splitter 决定）."""
    return int(os.getenv("RAG_CHUNK_SIZE", "2048"))


def chunk_overlap() -> int:
    """默认分块重叠."""
    return int(os.getenv("RAG_CHUNK_OVERLAP", "128"))


def rag_milvus_hybrid_ranker() -> str:
    """混合检索融合方式：``RRFRanker``（默认）或 ``WeightedRanker``（需配 ``rag_milvus_hybrid_ranker_params``）。"""
    return os.getenv("RAG_MILVUS_HYBRID_RANKER", "RRFRanker").strip() or "RRFRanker"


def rag_milvus_hybrid_ranker_params() -> dict[str, Any]:
    """JSON，例如 RRF：``{\"k\": 60}``；加权：``{\"weights\": [0.7, 0.3]}``（稠密、稀疏）。空则使用 LlamaIndex 默认。"""
    raw = os.getenv("RAG_MILVUS_HYBRID_RANKER_PARAMS", "").strip()
    if not raw:
        return {}
    return json.loads(raw)
