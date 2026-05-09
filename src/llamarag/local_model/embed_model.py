"""LlamaIndex 嵌入：与 ``llm_completion.embedding_llm`` 共用 LiteLLMM 嵌入，无单独 HTTP 封装。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import Field, PrivateAttr

from llm_completion.embedding_llm import sync_embedding_for_owner

logger = logging.getLogger(__name__)

# DashScope OpenAI 兼容嵌入等接口要求单次 input 条数 ≤10，超过则 400。
_EMBEDDING_API_MAX_INPUTS = 10


class LlamaIndexLiteEmbedding(BaseEmbedding):
    """将 ``LiteLLMEmbeddings`` 接入 IngestionPipeline（``TransformComponent``）。"""

    model_name: str = Field(description="embedding model id")

    _lc: Any = PrivateAttr()

    @classmethod
    def from_lite_lc(cls, lc_embeddings: Any) -> LlamaIndexLiteEmbedding:
        model_name = getattr(lc_embeddings, "model", None) or "embedding"
        inst = cls(
            model_name=str(model_name),
            embed_batch_size=_EMBEDDING_API_MAX_INPUTS,
        )
        object.__setattr__(inst, "_lc", lc_embeddings)
        return inst

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._lc.embed_query(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._lc.embed_query, query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._lc.embed_query(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        n = _EMBEDDING_API_MAX_INPUTS
        if len(texts) <= n:
            return self._lc.embed_documents(texts)
        out: list[list[float]] = []
        for i in range(0, len(texts), n):
            out.extend(self._lc.embed_documents(texts[i : i + n]))
        return out


def build_llama_embedding_for_owner(owner_user_id: int) -> LlamaIndexLiteEmbedding:
    """同步构造 LlamaIndex 嵌入组件。"""
    lc = sync_embedding_for_owner(owner_user_id)
    emb = LlamaIndexLiteEmbedding.from_lite_lc(lc)
    logger.debug("LlamaIndex LiteLLM 嵌入 model=%s", emb.model_name)
    return emb
