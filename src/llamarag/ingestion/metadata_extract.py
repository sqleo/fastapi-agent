"""入库前轻量抽取：标题、产品字段、FAQ 与关键词。"""

from __future__ import annotations

import logging
import re

from llamarag.local_model.uie_model import RecognizedEntity, extract_entities_by_uie
from models.EntityDictionaryModel import EntityType

logger = logging.getLogger(__name__)
_MODEL_ENTITY_MIN_CONFIDENCE = 0.3


def _first_heading(text: str) -> str | None:
    """提取 Markdown 文档的第一个一级标题作为文档标题。"""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def _pick_best_model_entity(
    entities: list[RecognizedEntity],
    entity_type: EntityType,
    *,
    min_confidence: float = _MODEL_ENTITY_MIN_CONFIDENCE,
) -> str | None:
    best_text: str | None = None
    best_score = -1.0
    for entity in entities:
        if entity.entity_type != entity_type:
            continue
        text = entity.text.strip()
        if not text or entity.confidence < min_confidence:
            continue
        if entity.confidence > best_score:
            best_score = entity.confidence
            best_text = text
    return best_text


def _pick_all_model_entities(
    entities: list[RecognizedEntity],
    entity_type: EntityType,
    *,
    limit: int = 8,
    min_confidence: float = _MODEL_ENTITY_MIN_CONFIDENCE,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        if entity.entity_type != entity_type:
            continue
        if entity.confidence < min_confidence:
            continue
        text = entity.text.strip()
        norm = re.sub(r"\s+", "", text.lower())
        if not text or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _serialize_model_entities(entities: list[RecognizedEntity]) -> list[dict[str, object]]:
    return [
        {
            "entity_type": entity.entity_type.value,
            "text": entity.text,
            "confidence": round(entity.confidence, 4),
            "source": entity.source,
        }
        for entity in entities
    ]


def _extract_keywords_from_model_entities(
    entities: list[RecognizedEntity],
    *,
    limit: int = 12,
    min_confidence: float = _MODEL_ENTITY_MIN_CONFIDENCE,
) -> list[str]:
    ordered = sorted(entities, key=lambda x: x.confidence, reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for entity in ordered:
        if entity.confidence < min_confidence:
            continue
        text = entity.text.strip()
        norm = re.sub(r"\s+", "", text.lower())
        if not text or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _log_model_entities(entities: list[RecognizedEntity]) -> None:
    if not entities:
        logger.info("实体抽取未识别到任何实体")
        return
    for entity in entities:
        logger.warning(
            "recognized_entity type=%s text=%s confidence=%.4f",
            entity.entity_type.value,
            entity.text.strip(),
            entity.confidence,
        )


def extract_doc_metadata(
    text: str,
    *,
    fallback_title: str,
    owner_user_id: int | None = None,
    knowledge_base_id: int | None = None,
    biz_code: str | None = None,
) -> dict[str, object]:
    """纯模型实体抽取：实体字段仅由 UIE 模型提供。"""
    _ = owner_user_id, knowledge_base_id, biz_code

    title = _first_heading(text) or fallback_title
    faq_questions = re.findall(r"\*\*Q\d+[:：](.+?)\*\*", text)

    logger.warning("uie_input title=%s text_len=%d", title, len(text))
    model_entities = extract_entities_by_uie(text, title=title)
    logger.warning("uie_output_count=%d", len(model_entities))
    _log_model_entities(model_entities)
    product_name = _pick_best_model_entity(model_entities, EntityType.PRODUCT)
    brand = _pick_best_model_entity(model_entities, EntityType.BRAND)
    category = _pick_best_model_entity(model_entities, EntityType.CATEGORY)
    model_ingredients = _pick_all_model_entities(model_entities, EntityType.INGREDIENT, limit=8)
    doc_type = (
        "product_doc"
        if any(entity.entity_type in {EntityType.PRODUCT, EntityType.BRAND, EntityType.CATEGORY} for entity in model_entities)
        else "general_md"
    )

    metadata: dict[str, object] = {
        "doc_title": title,
        "doc_type": doc_type,
        "product_name": product_name,
        "brand": brand,
        "category": category,
        "ingredients": "、".join(model_ingredients) if model_ingredients else None,
        "faq_questions": [q.strip() for q in faq_questions[:12]],
        "keywords": _extract_keywords_from_model_entities(model_entities),
        "model_entities": _serialize_model_entities(model_entities),
    }
    return {k: v for k, v in metadata.items() if v not in (None, "", [], {})}


def build_ingest_text(text: str, metadata: dict[str, object]) -> str:
    """把关键字段前置到文本前，提升召回与重排稳定性。"""
    prefix_lines: list[str] = []
    preferred_keys = ["doc_title", "product_name", "brand", "category", "shelf_life", "storage", "specification"]
    handled_keys: set[str] = set()
    for key in preferred_keys:
        value = metadata.get(key)
        if value:
            prefix_lines.append(f"{key}: {value}")
            handled_keys.add(key)
    for key, value in metadata.items():
        if key in handled_keys or key in {"faq_questions", "keywords"}:
            continue
        if isinstance(value, str) and value.strip():
            prefix_lines.append(f"{key}: {value}")
    keywords = metadata.get("keywords")
    if isinstance(keywords, list) and keywords:
        prefix_lines.append(f"keywords: {'、'.join(str(x) for x in keywords[:10])}")
    if not prefix_lines:
        return text
    return "\n".join(prefix_lines) + "\n\n" + text


def build_vector_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """给向量切块使用的精简 metadata，避免超过 chunk 限制。"""
    compact: dict[str, object] = {}
    for key, value in metadata.items():
        if not value or key in {"faq_questions", "keywords"}:
            continue
        if isinstance(value, str):
            compact[key] = value[:120]
        elif isinstance(value, (int, float, bool)):
            compact[key] = value
    return compact