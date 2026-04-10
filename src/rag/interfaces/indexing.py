"""入库流水线协议."""

from __future__ import annotations

from typing import Protocol

from rag.contracts import IngestContext, IngestResult
from shared.embedding.config import EmbeddingConfig


class IndexingPipeline(Protocol):
    """与 ``ingest_parsed_md_for_kb_file`` 对齐的可替换实现."""

    def __call__(
        self,
        ctx: IngestContext,
        *,
        embedding_config: EmbeddingConfig | None = None,
    ) -> IngestResult:
        """Run ingest for one KB-file pair."""
        ...
