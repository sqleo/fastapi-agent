"""入库流水线：解析后 Markdown → 分块 → 嵌入 → Milvus."""

from rag.indexing.pipeline import ingest_parsed_md_for_kb_file

__all__ = ["ingest_parsed_md_for_kb_file"]
