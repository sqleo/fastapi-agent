"""LlamaIndex 全局嵌入：优先使用项目内已下载的 BGE，避免重复走 Hub。"""

from __future__ import annotations

import logging
from pathlib import Path

from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from configs.env import env_config

logger = logging.getLogger(__name__)

# 与 scripts/download_model.py、Docker 挂卷约定一致：项目根下 model/BAAI/bge-small-zh-v1.5/
_RELATIVE_BGE = Path("model") / "BAAI" / "bge-small-zh-v1.5"
_HUB_MODEL_ID = "BAAI/bge-small-zh-v1.5"


def _candidate_local_bge_dirs() -> list[Path]:
    """按优先级列出本地模型目录候选（第一个存在的目录将被采用）。"""
    cands: list[Path] = []
    direct = (env_config.bge_local_model_path or "").strip()
    if direct:
        cands.append(Path(direct).resolve())
    root = (env_config.llamarag_project_root or "").strip()
    if root:
        cands.append(Path(root).resolve() / _RELATIVE_BGE)
    cands.append(Path(__file__).resolve().parents[3] / _RELATIVE_BGE)
    return cands


def _resolve_embed_model_name() -> str:
    for p in _candidate_local_bge_dirs():
        if p.is_dir():
            logger.info("使用本地 BGE 目录: %s", p)
            return str(p)
    logger.info("未找到本地 BGE 目录，候选: %s；改用 Hub id %s", _candidate_local_bge_dirs(), _HUB_MODEL_ID)
    return _HUB_MODEL_ID


_EMBED_MODEL_NAME = _resolve_embed_model_name()
embed_model = Settings.embed_model = HuggingFaceEmbedding(model_name=_EMBED_MODEL_NAME)
dim = embed_model._model.get_embedding_dimension()

logger.info("嵌入模型 name=%s dim=%s", _EMBED_MODEL_NAME, dim)
