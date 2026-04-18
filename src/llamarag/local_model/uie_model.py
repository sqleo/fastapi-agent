"""UIE-nano 本地实体抽取封装。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import torch
from transformers import AutoModel, AutoTokenizer

from configs.env import env_config
from models.EntityDictionaryModel import EntityType

logger = logging.getLogger(__name__)

_RELATIVE_UIE = Path("model") / "Casually" / "uie-nano"
_HUB_MODEL_ID = "Casually/uie-nano"
_ENTITY_TYPE_TO_SCHEMAS: dict[EntityType, list[str]] = {
    EntityType.PRODUCT: ["产品", "产品名称", "商品", "单品"],
    EntityType.BRAND: ["品牌", "品牌名", "品牌名称", "厂商"],
    EntityType.CATEGORY: ["品类", "类别", "类目", "产品类型"],
    EntityType.INGREDIENT: ["成分", "配料", "原料", "主要成分", "配方"],
}
_SCHEMA_TO_ENTITY_TYPE: dict[str, EntityType] = {
    schema_name: entity_type
    for entity_type, schema_names in _ENTITY_TYPE_TO_SCHEMAS.items()
    for schema_name in schema_names
}
_FALLBACK_MIN_THRESHOLD = 0.1

_MODEL = None
_TOKENIZER = None
_MODEL_LOCK = Lock()


@dataclass(frozen=True)
class RecognizedEntity:
    """模型识别出的实体。"""

    entity_type: EntityType
    text: str
    confidence: float
    start: int | None = None
    end: int | None = None
    source: str = "uie-nano"


def _candidate_local_uie_dirs() -> list[Path]:
    """按优先级列出 UIE 本地目录候选。"""
    cands: list[Path] = []
    direct = (env_config.uie_local_model_path or "").strip()
    if direct:
        cands.append(Path(direct).resolve())
    root = (env_config.llamarag_project_root or "").strip()
    if root:
        cands.append(Path(root).resolve() / _RELATIVE_UIE)
    cands.append(Path(__file__).resolve().parents[3] / _RELATIVE_UIE)
    return cands


def _resolve_uie_model_name() -> str:
    for path in _candidate_local_uie_dirs():
        if path.is_dir():
            logger.info("使用本地 UIE 目录: %s", path)
            return str(path)
    logger.info("未找到本地 UIE 目录，候选: %s；改用 Hub id %s", _candidate_local_uie_dirs(), _HUB_MODEL_ID)
    return _HUB_MODEL_ID


def _load_model() -> tuple[object, object]:
    """延迟加载 UIE 模型与 tokenizer。"""
    global _MODEL, _TOKENIZER
    if _MODEL is not None and _TOKENIZER is not None:
        return _MODEL, _TOKENIZER

    with _MODEL_LOCK:
        if _MODEL is not None and _TOKENIZER is not None:
            return _MODEL, _TOKENIZER

        model_name = _resolve_uie_model_name()
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
        model.eval()
        _MODEL = model
        _TOKENIZER = tokenizer
        logger.info("UIE 实体模型已加载: %s", model_name)
    return _MODEL, _TOKENIZER


def _normalize_entity_text(text: str) -> str:
    return "".join((text or "").strip().lower().split())


def _coerce_probability(value: object) -> float | None:
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        try:
            score = float(value)
        except ValueError:
            return None
    else:
        return None
    if score < 0:
        return None
    return min(score, 1.0)


def extract_entities_by_uie(
    text: str,
    *,
    title: str | None = None,
    max_length: int | None = None,
    confidence_threshold: float | None = None,
) -> list[RecognizedEntity]:
    """用 UIE-nano 从文档中抽取实体。"""
    content = (text or "").strip()
    title_text = (title or "").strip()
    if title_text:
        content = f"标题：{title_text}\n\n{content}" if content else f"标题：{title_text}"
    if not content:
        return []

    model, tokenizer = _load_model()
    actual_max_length = max(64, int(max_length or env_config.uie_entity_max_length))
    actual_threshold = float(confidence_threshold or env_config.uie_entity_confidence_threshold)

    def _predict_with_threshold(threshold: float) -> object:
        with torch.inference_mode():
            return model.predict(
                schema=list(_SCHEMA_TO_ENTITY_TYPE.keys()),
                input_texts=content,
                tokenizer=tokenizer,
                max_length=actual_max_length,
                position_prob=threshold,
            )

    def _collect_entities(raw_result: object, *, threshold: float) -> list[RecognizedEntity]:
        if not raw_result:
            return []
        payload = raw_result[0] if isinstance(raw_result, list) else raw_result
        if not isinstance(payload, dict):
            return []

        schema_hit_counts: dict[str, int] = {}
        dedup: dict[tuple[EntityType, str], RecognizedEntity] = {}
        for schema_name, entity_type in _SCHEMA_TO_ENTITY_TYPE.items():
            hits = payload.get(schema_name)
            if not isinstance(hits, list):
                continue
            schema_hit_counts[schema_name] = len(hits)
            for item in hits:
                if not isinstance(item, dict):
                    continue
                entity_text = str(item.get("text") or "").strip()
                if len(entity_text) < 2:
                    continue
                confidence = _coerce_probability(item.get("probability"))
                if confidence is None or confidence < threshold:
                    continue
                norm = _normalize_entity_text(entity_text)
                if not norm:
                    continue
                recognized = RecognizedEntity(
                    entity_type=entity_type,
                    text=entity_text,
                    confidence=confidence,
                    start=int(item["start"]) if isinstance(item.get("start"), int) else None,
                    end=int(item["end"]) if isinstance(item.get("end"), int) else None,
                )
                key = (entity_type, norm)
                old = dedup.get(key)
                if old is None or recognized.confidence > old.confidence:
                    dedup[key] = recognized

        logger.info(
            "uie_predict threshold=%.2f schema_hits=%s entities=%d",
            threshold,
            schema_hit_counts,
            len(dedup),
        )
        return sorted(dedup.values(), key=lambda item: (-item.confidence, item.text))

    primary_raw = _predict_with_threshold(actual_threshold)
    entities = _collect_entities(primary_raw, threshold=actual_threshold)
    if entities:
        return entities

    if actual_threshold > _FALLBACK_MIN_THRESHOLD:
        logger.info(
            "uie_predict fallback threshold from %.2f to %.2f",
            actual_threshold,
            _FALLBACK_MIN_THRESHOLD,
        )
        fallback_raw = _predict_with_threshold(_FALLBACK_MIN_THRESHOLD)
        fallback_entities = _collect_entities(fallback_raw, threshold=_FALLBACK_MIN_THRESHOLD)
        if fallback_entities:
            return fallback_entities

    return []