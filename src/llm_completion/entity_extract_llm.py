"""基于 chat_llm 的实体抽取。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from llm_completion.chat_llm import chat_llm
from models.EntityDictionaryModel import EntityType
from utils.sql_db import async_session

logger = logging.getLogger(__name__)

_DEFAULT_FIELD_CONFIDENCE = 0.85
_MAX_INPUT_CHARS = 6000


@dataclass(frozen=True)
class RecognizedEntity:
    """模型识别出的实体。"""

    entity_type: EntityType
    text: str
    confidence: float
    start: int | None = None
    end: int | None = None
    source: str = "model.chat_llm"


_EXTRACT_SYSTEM_PROMPT = """你是中文实体抽取器。
请从输入文本中抽取以下实体：brand、product_name、category、ingredients。

输出要求：
1) 只输出一个 JSON 对象，不要输出任何解释或 markdown。
2) JSON 结构固定为：
{
  \"brand\": string | null,
  \"product_name\": string | null,
  \"category\": string | null,
  \"ingredients\": string[],
  \"confidence\": {
    \"brand\": number,
    \"product_name\": number,
    \"category\": number,
    \"ingredients\": number
  }
}
3) confidence 取值范围 [0, 1]。
4) 若某字段不存在，返回 null（ingredients 返回空数组）。
5) 不要编造，尽量从原文精确抽取。
"""


def _strip_code_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
    return s.strip()


def _parse_json_payload(raw: str) -> dict[str, object] | None:
    text = _strip_code_fence(raw)
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _coerce_confidence(value: object, fallback: float = _DEFAULT_FIELD_CONFIDENCE) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        try:
            return max(0.0, min(1.0, float(value)))
        except ValueError:
            return fallback
    return fallback


def _normalize_entity_text(text: str) -> str:
    return "".join((text or "").strip().lower().split())


def _append_entity(
    out: list[RecognizedEntity],
    dedup: set[tuple[EntityType, str]],
    *,
    entity_type: EntityType,
    text: str,
    confidence: float,
) -> None:
    t = str(text or "").strip()
    if len(t) < 2:
        return
    norm = _normalize_entity_text(t)
    if not norm:
        return
    key = (entity_type, norm)
    if key in dedup:
        return
    dedup.add(key)
    out.append(
        RecognizedEntity(
            entity_type=entity_type,
            text=t,
            confidence=confidence,
        )
    )


def _entities_from_payload(payload: dict[str, object]) -> list[RecognizedEntity]:
    out: list[RecognizedEntity] = []
    dedup: set[tuple[EntityType, str]] = set()

    confidence_map = payload.get("confidence")
    confidence = confidence_map if isinstance(confidence_map, dict) else {}

    brand = payload.get("brand")
    if isinstance(brand, str) and brand.strip():
        _append_entity(
            out,
            dedup,
            entity_type=EntityType.BRAND,
            text=brand,
            confidence=_coerce_confidence(confidence.get("brand")),
        )

    product_name = payload.get("product_name")
    if isinstance(product_name, str) and product_name.strip():
        _append_entity(
            out,
            dedup,
            entity_type=EntityType.PRODUCT,
            text=product_name,
            confidence=_coerce_confidence(confidence.get("product_name")),
        )

    category = payload.get("category")
    if isinstance(category, str) and category.strip():
        _append_entity(
            out,
            dedup,
            entity_type=EntityType.CATEGORY,
            text=category,
            confidence=_coerce_confidence(confidence.get("category")),
        )

    ingredients = payload.get("ingredients")
    if isinstance(ingredients, list):
        ingredient_conf = _coerce_confidence(confidence.get("ingredients"))
        for item in ingredients[:16]:
            if isinstance(item, str) and item.strip():
                _append_entity(
                    out,
                    dedup,
                    entity_type=EntityType.INGREDIENT,
                    text=item,
                    confidence=ingredient_conf,
                )

    return sorted(out, key=lambda x: (-x.confidence, x.text))


async def extract_entities_by_chat_llm(
    text: str,
    *,
    owner_user_id: int,
    session: AsyncSession,
    title: str | None = None,
) -> list[RecognizedEntity]:
    """使用 ``chat_llm`` 从文本提取实体。"""
    content = (text or "").strip()
    if not content:
        return []

    title_text = (title or "").strip()
    compact_content = content[:_MAX_INPUT_CHARS]
    llm_input = (
        f"标题：{title_text}\n\n正文：{compact_content}" if title_text else f"正文：{compact_content}"
    )

    try:
        llm = await chat_llm(session, owner_user_id=owner_user_id, temperature_override=0.0, max_tokens=512)
        resp = await llm.ainvoke(
            [
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=llm_input),
            ]
        )
    except Exception:
        logger.warning("chat_llm 实体抽取调用失败", exc_info=True)
        return []

    raw = getattr(resp, "content", "")
    if isinstance(raw, list):
        raw = " ".join(
            str(item.get("text", ""))
            for item in raw
            if isinstance(item, dict) and item.get("type") == "text"
        )
    parsed = _parse_json_payload(str(raw))
    if not parsed:
        logger.info("chat_llm 实体抽取无可解析 JSON 输出")
        return []

    entities = _entities_from_payload(parsed)
    logger.info("chat_llm 实体抽取完成 entities=%d", len(entities))
    return entities


def extract_entities_by_chat_llm_sync(
    text: str,
    *,
    owner_user_id: int | None,
    title: str | None = None,
) -> list[RecognizedEntity]:
    """同步入口：供入库线程调用。"""
    if owner_user_id is None:
        return []

    async def _runner() -> list[RecognizedEntity]:
        async with async_session() as session:
            return await extract_entities_by_chat_llm(
                text,
                owner_user_id=owner_user_id,
                session=session,
                title=title,
            )

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        logger.warning("chat_llm 同步抽取在运行中的 event loop 内被调用，已跳过")
        return []
    except Exception:
        logger.warning("chat_llm 同步实体抽取失败", exc_info=True)
        return []
