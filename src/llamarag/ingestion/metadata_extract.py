"""入库前轻量抽取：标题、产品字段、FAQ 与关键词。"""

from __future__ import annotations

import re
from collections import Counter

from llamarag.ingestion.metadata_field_config import load_metadata_field_config_sync

_STOP_WORDS = {
    "的",
    "了",
    "和",
    "与",
    "及",
    "或",
    "在",
    "是",
    "为",
    "可",
    "有",
    "后",
    "前",
    "将",
    "对",
    "按",
    "请",
    "该",
    "这",
    "一个",
    "一种",
    "进行",
    "相关",
    "使用",
    "产品",
    "文档",
}


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def _section_body(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else ""


def _field_value(text: str, label: str) -> str | None:
    m = re.search(rf"[\-*]\s*\*\*{re.escape(label)}\*\*[:：]\s*(.+)", text)
    if m:
        return m.group(1).strip().rstrip("。")
    m = re.search(rf"{re.escape(label)}[:：]\s*(.+)", text)
    return m.group(1).strip().rstrip("。") if m else None


def _extract_by_aliases(text: str, aliases: list[str], *, extract_mode: str) -> str | None:
    if extract_mode == "section":
        for alias in aliases:
            value = _section_body(text, alias)
            if value:
                return value
        return None
    for alias in aliases:
        value = _field_value(text, alias)
        if value:
            return value
    return None


def _extract_keywords(text: str, limit: int = 12) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9\-]{2,}", text)
    counter: Counter[str] = Counter()
    for token in tokens:
        if token in _STOP_WORDS:
            continue
        if token.isdigit():
            continue
        counter[token] += 1
    return [word for word, _ in counter.most_common(limit)]


def extract_doc_metadata(
    text: str,
    *,
    fallback_title: str,
    owner_user_id: int | None = None,
    knowledge_base_id: int | None = None,
    biz_code: str | None = None,
) -> dict[str, object]:
    """从 Markdown 文本中提取适合检索过滤的轻量元数据。"""
    title = _first_heading(text) or fallback_title
    faq_questions = re.findall(r"\*\*Q\d+[:：](.+?)\*\*", text)
    product_name = title.replace("产品文档", "").replace("：", " ").strip()
    category = None
    for candidate in ("能量棒", "奶昔", "饮料", "饮品", "零食"):
        if candidate in text or candidate in title:
            category = candidate
            break
    brand = None
    if "：" in title:
        brand = title.split("：", 1)[0].strip()

    field_config = load_metadata_field_config_sync(
        owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        biz_code=biz_code,
    )
    if not field_config:
        raise ValueError("未配置 metadata 抽取规则，请先配置字段与字段别名")

    extracted_values: dict[str, object] = {}
    for field_key, cfg in field_config.items():
        aliases = cfg.get("aliases") or []
        extract_mode = str(cfg.get("extract_mode") or "field")
        if not isinstance(aliases, list) or not aliases:
            continue
        value = _extract_by_aliases(text, [str(x) for x in aliases if x], extract_mode=extract_mode)
        if not value:
            continue
        extracted_values[field_key] = value[:500] if field_key == "ingredients" else value

    metadata: dict[str, object] = {
        "doc_title": title,
        "doc_type": "product_doc" if "产品" in title or "规格" in text else "general_md",
        "product_name": product_name,
        "brand": brand,
        "category": category,
        "faq_questions": [q.strip() for q in faq_questions[:12]],
        "keywords": _extract_keywords(text),
        **extracted_values,
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