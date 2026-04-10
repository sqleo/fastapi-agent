"""从磁盘加载解析后的 Markdown 为 LlamaIndex Document（后续接入）."""

from rag.loaders.parsed_md import load_parsed_md_documents

__all__ = ["load_parsed_md_documents"]
