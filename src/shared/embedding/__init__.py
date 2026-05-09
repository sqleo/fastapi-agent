"""嵌入配置抽象：维度与数据库解析（同步嵌入请用 ``llm_completion.embedding_llm``）。"""

from shared.embedding.config import EmbeddingConfig, get_embedding_dimensions
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.provider import (
    DatabaseEmbeddingSettingsProvider,
    EmbeddingFallbackProvider,
    EmbeddingSettingsProvider,
)

__all__ = [
    "get_embedding_dimensions",
    "DatabaseEmbeddingSettingsProvider",
    "EmbeddingConfig",
    "EmbeddingConfigurationError",
    "EmbeddingFallbackProvider",
    "EmbeddingSettingsProvider",
]
