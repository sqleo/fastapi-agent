"""嵌入向量配置值对象."""

from __future__ import annotations

from dataclasses import dataclass

# EmbeddingConfig 默认值；实际解析维度见 ``get_embedding_dimensions()``。
_DEFAULT_DIM = 512


def get_embedding_dimensions() -> int:
    """与 Milvus dense 维数、HTTP ``dimensions`` 对齐（来自 ``MILVUS_DIM`` / ``EMBEDDING_DIMENSIONS``）。"""
    from configs.env import env_config

    return env_config.embedding_dimensions


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """一次 OpenAI 兼容 ``/embeddings`` 调用所需参数."""

    model: str
    base_url: str
    api_key: str
    dimensions: int = _DEFAULT_DIM
