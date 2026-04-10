"""嵌入配置抽象：数据库主路径 + 降级策略子类占位."""

from shared.embedding.config import FIXED_EMBEDDING_DIMENSION, EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.provider import (
    DatabaseEmbeddingSettingsProvider,
    EmbeddingFallbackProvider,
    EmbeddingSettingsProvider,
)
from shared.embedding.sync_resolve import sync_resolve_embedding_config

__all__ = [
    "FIXED_EMBEDDING_DIMENSION",
    "DatabaseEmbeddingSettingsProvider",
    "EmbeddingConfig",
    "EmbeddingConfigurationError",
    "EmbeddingFallbackProvider",
    "EmbeddingSettingsProvider",
    "sync_resolve_embedding_config",
]
