"""入库前轻量抽取：标题、产品字段、FAQ 与关键词。"""

from __future__ import annotations

import re
from collections import Counter

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


def extract_doc_metadata(text: str, *, fallback_title: str) -> dict[str, object]:
    """从 Markdown 文本中提取适合检索过滤的轻量元数据。"""
    title = _first_heading(text) or fallback_title
    faq_questions = re.findall(r"\*\*Q\d+[:：](.+?)\*\*", text)
    ingredients = _section_body(text, "主要成分（每40g/根）") or _section_body(text, "主要成分")
    product_name = title.replace("产品文档", "").replace("：", " ").strip()
    category = None
    for candidate in ("能量棒", "奶昔", "饮料", "饮品", "零食"):
        if candidate in text or candidate in title:
            category = candidate
            break
    brand = None
    if "：" in title:
        brand = title.split("：", 1)[0].strip()

    metadata: dict[str, object] = {
        "doc_title": title,
        "doc_type": "product_doc" if "产品" in title or "规格" in text else "general_md",
        "product_name": product_name,
        "brand": brand,
        "category": category,
        "shelf_life": _field_value(text, "保质期"),
        "storage": _field_value(text, "储存条件"),
        "specification": _field_value(text, "规格"),
        "standard": _field_value(text, "执行标准"),
        "ingredients": ingredients[:500] if ingredients else None,
        "faq_questions": [q.strip() for q in faq_questions[:12]],
        "keywords": _extract_keywords(text),
    }
    return {k: v for k, v in metadata.items() if v not in (None, "", [], {})}


def build_ingest_text(text: str, metadata: dict[str, object]) -> str:
    """把关键字段前置到文本前，提升召回与重排稳定性。"""
    prefix_lines: list[str] = []
    for key in ("doc_title", "product_name", "brand", "category", "shelf_life", "storage", "specification"):
        value = metadata.get(key)
        if value:
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
    for key in (
        "doc_title",
        "doc_type",
        "product_name",
        "brand",
        "category",
        "shelf_life",
        "storage",
        "specification",
        "standard",
    ):
        value = metadata.get(key)
        if not value:
            continue
        if isinstance(value, str):
            compact[key] = value[:120]
        else:
            compact[key] = value
    return compact