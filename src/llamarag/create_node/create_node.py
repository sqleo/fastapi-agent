"""将 ``Document`` 列表交给 ``IngestionPipeline``，产出 ``BaseNode`` 序列."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from llama_index.core import Document
from llama_index.core.schema import BaseNode

from llamarag.ingestion_pipeline.pipeline import ingestion_pipeline


logger = logging.getLogger(__name__)


def create_node(documents: list[Document]) -> Sequence[BaseNode]:
    """对文档跑默认 IngestionPipeline（切块等），返回节点；空列表直接返回 ``[]``."""
    if not documents:
        logger.warning("收到空的文档列表，跳过 IngestionPipeline。")
        return []

    try:
        pipeline = ingestion_pipeline()
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
