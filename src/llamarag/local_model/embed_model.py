"""LlamaIndex 全局嵌入：优先使用项目内已下载的 BGE，避免重复走 Hub。"""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# 与 scripts/download_model.py 输出目录一致：项目根 model/bge-small-zh-v1.5/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_BGE = _PROJECT_ROOT / "model" / "bge-small-zh-v1.5"

_EMBED_MODEL_NAME = str(_LOCAL_BGE) if _LOCAL_BGE.is_dir() else "BAAI/bge-small-zh-v1.5"
embed_model = Settings.embed_model = HuggingFaceEmbedding(model_name=_EMBED_MODEL_NAME)
dim = embed_model._model.get_embedding_dimension()

print(f"当前嵌入模型: {_EMBED_MODEL_NAME}")
print(f"向量维度 dim = {dim}")
