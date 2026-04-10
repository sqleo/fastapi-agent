"""RAG 领域包：解析后 Markdown → 分块 → 嵌入 → Milvus；查询侧检索.

重依赖（``llama_index``）请从子模块按需导入，例如 ``from rag.indexing.pipeline import ingest_parsed_md_for_kb_file``，
勿在本包顶层导入，以免未安装 ``rag`` optional 时影响仅使用 ``rag.contracts`` 的代码。
"""

from rag.contracts import IngestContext, IngestResult

__all__ = [
    "IngestContext",
    "IngestResult",
]
