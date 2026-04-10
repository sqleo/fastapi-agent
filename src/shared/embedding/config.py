"""嵌入向量配置值对象."""

from __future__ import annotations

from dataclasses import dataclass

# 与 Milvus 集合维度一致；当前产品约定写死 1024。
FIXED_EMBEDDING_DIMENSION: int = 1024


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """一次 OpenAI 兼容 ``/embeddings`` 调用所需参数."""

    model: str
    base_url: str
    api_key: str
    dimensions: int = FIXED_EMBEDDING_DIMENSION
