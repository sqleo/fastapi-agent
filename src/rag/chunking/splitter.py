"""将 Document 列表切分为节点。

1. ``MarkdownNodeParser``：按 Markdown 标题切块，并带上标题路径等 metadata。
2. ``SentenceSplitter``：仅当某一节正文长度超过 ``chunk_size`` 时，对该节做二次切分。

过长节只保留子块，不保留整段父块，避免同一正文在向量库里被嵌入多次。
"""

from __future__ import annotations

from typing import Any


def split_documents(documents: list[Any]) -> list[Any]:
    """对文档分块，返回节点列表；未安装 LlamaIndex 时原样返回 ``documents``。"""
    try:
        from llama_index.core.node_parser import MarkdownNodeParser
        from llama_index.core.node_parser.text.sentence import SentenceSplitter
    except ImportError:
        return documents

    from rag.config import chunk_overlap as overlap_cfg
    from rag.config import chunk_size as size_cfg

    size = int(size_cfg())
    overlap = int(overlap_cfg())

    md_parser = MarkdownNodeParser(
        include_metadata=True, # 是否包含元数据
        include_prev_next_rel=True, # 是否包含前一个和后一个节点
    )
    section_nodes = md_parser.get_nodes_from_documents(documents)

    splitter = SentenceSplitter(chunk_size=size, chunk_overlap=overlap)

    final: list[Any] = []
    for node in section_nodes:
        text = (getattr(node, "text", None) or "") if node is not None else ""
        if len(text) <= size:
            final.append(node)
            continue
        final.extend(splitter([node]))

    return final
