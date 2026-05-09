"""实体抽取兼容层：保留旧接口，内部转发到 chat_llm。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from llm_completion.entity_extract_llm import extract_entities_by_chat_llm_sync
from models.EntityDictionaryModel import EntityType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecognizedEntity:
    """模型识别出的实体（兼容旧结构）。"""

    entity_type: EntityType
    text: str
    confidence: float
    start: int | None = None
    end: int | None = None
    source: str = "model.chat_llm"


def extract_entities_by_uie(
    text: str,
    *,
    title: str | None = None,
    max_length: int | None = None,
    confidence_threshold: float | None = None,
) -> list[RecognizedEntity]:
    """兼容旧函数签名：内部转发 chat_llm 实体抽取。"""
    _ = max_length, confidence_threshold
    raw_uid = (os.getenv("LANGGRAPH_DEV_USER_ID") or "").strip()
    owner_user_id = int(raw_uid) if raw_uid.isdigit() and int(raw_uid) > 0 else None
    if owner_user_id is None:
        logger.warning("extract_entities_by_uie 兼容调用缺少 owner_user_id，返回空结果")
        return []
    extracted = extract_entities_by_chat_llm_sync(text, owner_user_id=owner_user_id, title=title)
    return [
        RecognizedEntity(
            entity_type=item.entity_type,
            text=item.text,
            confidence=item.confidence,
            start=item.start,
            end=item.end,
            source=item.source,
        )
        for item in extracted
    ]