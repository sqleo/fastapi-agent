"""将 ``Document`` 列表交给 ``IngestionPipeline``，产出 ``BaseNode`` 序列."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from llama_index.core import Document
from llama_index.core.schema import BaseNode

from llamarag.ingestion.pipeline import ingestion_pipeline

logger = logging.getLogger(__name__)


def _owner_user_id_from_documents(documents: list[Document]) -> int:
    if not documents:
        raise ValueError("文档列表为空，无法推断 owner_user_id")
    ids: list[int] = []
    for d in documents:
        raw = (d.metadata or {}).get("owner_user_id")
        if raw is None:
            raise ValueError(
                "Document.metadata 缺少 owner_user_id（索引入库须带租户 id，参见 index_parsed_md_for_kb_file_sync）",
            )
        ids.append(int(raw))
    if len(set(ids)) != 1:
        raise ValueError("同一批次 Document 的 owner_user_id 不一致，禁止混租户入库")
    return ids[0]


def create_node(documents: list[Document]) -> Sequence[BaseNode]:
    """对文档跑默认 IngestionPipeline（切块等），返回节点；空列表直接返回 ``[]``."""
    if not documents:
        logger.warning("收到空的文档列表，跳过 IngestionPipeline。")
        return []

    owner_user_id = _owner_user_id_from_documents(documents)

    try:
        pipeline = ingestion_pipeline(owner_user_id)
        nodes = pipeline.run(documents=documents)
        logger.info(
            "成功处理 %s 个文档，生成 %s 个节点。",
            len(documents),
            len(nodes),
        )
        return nodes
    except Exception:
        logger.exception("IngestionPipeline 运行失败")
        raise
