"""将解析后的 Markdown 经 IngestionPipeline 分块、嵌入并写入向量库."""

from __future__ import annotations

import logging
from pathlib import Path

from llama_index.core import Document

from llamarag.ingestion.metadata_extract import (
    build_ingest_text,
    build_vector_metadata,
    extract_doc_metadata,
)
from utils.content_semver import format_semver

logger = logging.getLogger(__name__)


def _ref_doc_id_for_kb_file(kb_id: int, file_id: int) -> str:
    """同一知识库内同一文件的稳定 id，便于覆盖入库前删除旧向量."""
    return f"kb_{kb_id}_file_{file_id}"


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
