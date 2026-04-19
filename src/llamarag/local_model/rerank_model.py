"""BGE Reranker v2-m3 封装 — 基于 transformers cross-encoder，用 sigmoid 归一化到 0-1。

延迟加载：首次调用 ``rerank_sync()`` 才实例化模型，避免启动耗时。
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_MODEL_PATH = "BGE_RERANKER_MODEL_PATH"
_DEFAULT_LOCAL_PATH = "/app/model/BAAI/bge-reranker-v2-m3"
_QWEN_LOCAL_PATH = "/app/model/Qwen/Qwen3-Reranker-0.6B"
_MAX_LENGTH = 512

_reranker: "_BGEReranker | None" = None


class _BGEReranker:
    """Transformers cross-encoder wrapper for BAAI/bge-reranker-v2-m3."""

    def __init__(self, model_path: str) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info("正在加载 BGE Reranker from %s …", model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
        )
        self._model = AutoModelForSequenceClassification.from_pretrained(
            model_path,
            ignore_mismatched_sizes=True,
            local_files_only=True,
        )

        # 某些 Qwen reranker 权重未声明 pad_token，batch>1 可能报错
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = (
                self._tokenizer.eos_token
                or self._tokenizer.unk_token
                or self._tokenizer.sep_token
            )
        if self._model.config.pad_token_id is None and self._tokenizer.pad_token_id is not None:
            self._model.config.pad_token_id = self._tokenizer.pad_token_id

        self._model.eval()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        self._torch = torch
        logger.info("BGE Reranker 加载完毕 device=%s", self._device)

    def predict(self, pairs: list[list[str]]) -> list[float]:
        """返回 sigmoid 归一化后的 0-1 相关度分数列表（与 pairs 一一对应）。"""
        if not pairs:
            return []
        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=_MAX_LENGTH,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with self._torch.no_grad():
            logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
        # sigmoid 归一化：让分数落在 0-1，与 retrieval 相关度阈值对齐
        scores = [1.0 / (1.0 + math.exp(-float(l))) for l in logits.tolist()]
        return scores


def _has_checkpoint(path: str) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    return (p / "model.safetensors").is_file() or (p / "pytorch_model.bin").is_file()


def _find_checkpoint_dir(root: str) -> str | None:
    """在目录下递归查找包含模型权重的子目录（兼容 ModelScope 嵌套结构）。"""
    root_path = Path(root)
    if not root_path.is_dir():
        return None

    if _has_checkpoint(str(root_path)):
        return str(root_path)

    candidates: list[Path] = []
    for p in root_path.rglob("*"):
        if p.is_dir() and _has_checkpoint(str(p)):
            # 忽略临时/缓存目录，避免误命中
            parts = set(p.parts)
            if any(x in parts for x in {".cache", "._____temp", ".lock"}):
                continue
            candidates.append(p)
    if not candidates:
        return None

    # 优先精确目录名，其次路径更短
    candidates.sort(
        key=lambda x: (
            0 if x.name == "Qwen3-Reranker-0.6B" else 1,
            len(x.parts),
        )
    )
    return str(candidates[0])


def _resolve_model_path() -> str:
    env = os.environ.get(_ENV_MODEL_PATH, "").strip()
    if env:
        nested = _find_checkpoint_dir(env)
        if nested:
            return nested

    # 优先旧的 BGE 目录；不存在则回退到 Qwen 目录（兼容当前本地已下载模型）
    nested_bge = _find_checkpoint_dir(_DEFAULT_LOCAL_PATH)
    if nested_bge:
        return nested_bge

    nested_qwen = _find_checkpoint_dir(_QWEN_LOCAL_PATH)
    if nested_qwen:
        logger.warning("未找到 BGE 本地权重，已回退使用 Qwen reranker 权重目录：%s", nested_qwen)
        return nested_qwen

    raise FileNotFoundError(
        "未找到本地 reranker 权重：请下载到 /app/model/BAAI/bge-reranker-v2-m3 "
        "或 /app/model/Qwen/Qwen3-Reranker-0.6B"
    )


def _get_reranker() -> _BGEReranker:
    global _reranker
    if _reranker is None:
        resolved = _resolve_model_path()
        logger.warning("reranker 使用本地模型目录：%s", resolved)
        _reranker = _BGEReranker(resolved)
    return _reranker


def rerank_sync(
    query: str,
    passages: list[str],
    *,
    top_n: int = 5,
) -> list[tuple[float, str]]:
    """对 ``passages`` 重排序，返回 top_n 个 ``(score, text)``，score ∈ [0, 1]（降序）。

    失败时退化返回原始顺序（score 填 0.0），不抛异常。
    """
    if not passages:
        return []
    try:
        model = _get_reranker()
        pairs = [[query, p] for p in passages]
        scores = model.predict(pairs)
        ranked = sorted(zip(scores, passages), key=lambda x: x[0], reverse=True)
        return [(float(s), t) for s, t in ranked[:top_n]]
    except Exception:
        logger.exception("Reranker 执行失败，降级返回原始顺序")
        return [(0.0, p) for p in passages[:top_n]]
