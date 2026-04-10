"""RAG 流水线与检索的入参/出参约定."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IngestContext:
    """单次入库流水线上下文（由 worker 根据 DB 与 Redis 任务组装）."""

    owner_user_id: int
    knowledge_base_id: int
    file_id: int
    kb_file_link_id: int
    parsed_md_storage_key: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """入库流水线结果."""

    ok: bool
    chunk_count: int = 0
    error_message: str | None = None
