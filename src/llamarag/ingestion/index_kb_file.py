"""将解析后的 Markdown 经 IngestionPipeline 分块、嵌入并写入向量库."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llama_index.core import Document

from llamarag.ingestion.metadata_extract import (
    build_ingest_text,
    build_vector_metadata,
    extract_doc_metadata,
)
from utils.content_semver import format_semver

logger = logging.getLogger(__name__)


@dataclass
class PurgeResult:
    """索引清理结果（强一致校验用）。"""

    milvus_ok: bool
    docstore_ok: bool
    docstore_enabled: bool
    error: str | None = None


def _ref_doc_id_for_kb_file(kb_id: int, file_id: int) -> str:
    """同一知识库内同一文件的稳定 id，便于覆盖入库前删除旧向量."""
    return f"kb_{kb_id}_file_{file_id}"


def _delete_ref_doc_from_docstore(docstore: Any, ref_doc_id: str) -> None:
    """兼容不同 LlamaIndex 版本的 docstore 删除接口。"""
    if docstore is None:
        return
    # 新旧版本接口兼容：优先按 ref_doc 删除
    if hasattr(docstore, "delete_ref_doc"):
        docstore.delete_ref_doc(ref_doc_id, raise_error=False)
        return
    if hasattr(docstore, "adelete_ref_doc"):
        import asyncio

        asyncio.run(docstore.adelete_ref_doc(ref_doc_id, raise_error=False))
        return
    # 兜底：部分实现可能仅支持按 document id 删除
    if hasattr(docstore, "delete_document"):
        docstore.delete_document(ref_doc_id, raise_error=False)
        return
    if hasattr(docstore, "adelete_document"):
        import asyncio

        asyncio.run(docstore.adelete_document(ref_doc_id, raise_error=False))


def purge_indexed_kb_file_sync(*, kb_id: int, file_id: int) -> PurgeResult:
    """清理知识库文件索引数据：Milvus + LlamaIndex Postgres(docstore)。"""
    ref_doc_id = _ref_doc_id_for_kb_file(kb_id, file_id)

    from llamarag.storage.postgres_llamaindex import get_llamaindex_docstore
    from llamarag.storage.vector_store import vector_store

    milvus_ok = False
    docstore_ok = False
    docstore = get_llamaindex_docstore()
    docstore_enabled = docstore is not None

    try:
        vector_store.delete(ref_doc_id)
        milvus_ok = True
    except Exception as exc:
        return PurgeResult(
            milvus_ok=False,
            docstore_ok=False,
            docstore_enabled=docstore_enabled,
            error=f"milvus_delete_failed: {exc}",
        )

    if not docstore_enabled:
        return PurgeResult(
            milvus_ok=True,
            docstore_ok=True,
            docstore_enabled=False,
            error=None,
        )

    try:
        _delete_ref_doc_from_docstore(docstore, ref_doc_id)
        docstore_ok = True
    except Exception as exc:
        return PurgeResult(
            milvus_ok=milvus_ok,
            docstore_ok=False,
            docstore_enabled=True,
            error=f"docstore_delete_failed: {exc}",
        )

    return PurgeResult(
        milvus_ok=milvus_ok,
        docstore_ok=docstore_ok,
        docstore_enabled=True,
        error=None,
    )


def index_parsed_md_for_kb_file_sync(
    *,
    owner_user_id: int,
    kb_id: int,
    file_id: int,
    kb_file_id: int,
    parsed_md_storage_key: str,
    semver_major: int,
    semver_minor: int,
    semver_patch: int,
) -> tuple[int, dict[str, object]]:
    """同步执行：读 parsed_md → ``create_node`` → Milvus；返回 chunk 数与抽取结果。

    调用方应在异步路由中通过 ``asyncio.to_thread`` 执行，避免阻塞事件循环。
    """
    key = (parsed_md_storage_key or "").strip()
    if not key:
        raise ValueError("parsed_md_storage_key 为空")

    abs_path = Path("static") / key.lstrip("/")
    if not abs_path.is_file():
        raise FileNotFoundError(f"中间 Markdown 不存在: {abs_path}")

    text = abs_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("parsed_md 内容为空，无法入库")

    ref_doc_id = _ref_doc_id_for_kb_file(kb_id, file_id)
    semver_str = format_semver(semver_major, semver_minor, semver_patch)
    extracted = extract_doc_metadata(text, fallback_title=abs_path.stem)
    vector_metadata = build_vector_metadata(extracted)
    ingest_text = build_ingest_text(text, extracted)
    logger.info(
        "vector metadata length=%s ref_doc_id=%s",
        len(str(vector_metadata)),
        ref_doc_id,
    )

    from llamarag.create_node.create_node import create_node
    from llamarag.storage.vector_store import vector_store

    try:
        vector_store.delete(ref_doc_id)
    except Exception:
        logger.exception("删除旧向量失败（可能无历史数据） ref_doc_id=%s", ref_doc_id)

    doc = Document(
        text=ingest_text,
        doc_id=ref_doc_id,
        metadata={
            "owner_user_id": owner_user_id,
            "knowledge_base_id": kb_id,
            "file_id": file_id,
            "kb_file_id": kb_file_id,
            "content_semver": semver_str,
            "parsed_md_storage_key": key,
            **vector_metadata,
        },
    )

    nodes = create_node([doc])
    if not nodes:
        raise RuntimeError("IngestionPipeline 未生成任何节点")

    return len(nodes), extracted
