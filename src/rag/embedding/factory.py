"""LlamaIndex ``BaseEmbedding``：仅由数据库解析的 ``EmbeddingConfig`` 构造（不经环境变量、不经 LangChain）."""

from __future__ import annotations

import asyncio
from typing import Any

from rag.embedding.http_openai import HttpOpenAIEmbeddings
from shared.embedding.config import EmbeddingConfig


def build_llama_embedding_from_config(config: EmbeddingConfig) -> Any:
    """构造 LlamaIndex 嵌入模型（底层为 OpenAI 兼容 ``/embeddings`` HTTP）；未安装 llama-index-core 时返回 None."""
    try:
        from llama_index.core.embeddings import BaseEmbedding
    except ImportError:
        return None

    backend = HttpOpenAIEmbeddings.from_config(config)

    class _HttpBackendEmbedding(BaseEmbedding):
        def _get_query_embedding(self, query: str) -> list[float]:
            return backend.embed_query(query)

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return await asyncio.to_thread(backend.embed_query, query)

        def _get_text_embedding(self, text: str) -> list[float]:
            return backend.embed_documents([text])[0]

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return backend.embed_documents(texts)

    return _HttpBackendEmbedding(model_name=backend.model)
