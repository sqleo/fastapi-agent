"""示例：按 LangGraph 文档风格的「路由 → 检索 → 生成」线性图（独立图文件，与其它 Agent 模式解耦）."""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import time
from typing import Annotated, Any, Literal

from langchain_core.callbacks.manager import AsyncCallbackManager
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import patch_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent.tools.vector_search import search_user_knowledge_vectors_raw
from infra.langgraph import get_graph_checkpointer, get_langgraph_store
from infra.memory import (
    advanced_memory_retrieve_node,
    advanced_memory_write_node,
    short_term_window_node,
)
from llm_completion.chat_llm import chat_llm
from llm_completion.entity_extract_llm import extract_entities_by_chat_llm
from llm_completion.rerank_llm import rerank_to_scored_tuples
from models.EntityDictionaryModel import EntityType
from models.FileManagementModel import FileAssetModel
from models.KnowledgeBaseModel import KnowledgeBaseFileModel
from repositories.entity_repository import resolve_entities_batch
from utils.sql_db import async_session

logger = logging.getLogger("agent.graph_service")


def _trace_log(message: str, *args: object) -> None:
    """全链路观测日志：INFO 可用时走 INFO，否则自动提升到 WARNING。"""
    if logger.isEnabledFor(logging.INFO):
        logger.info(message, *args)
        return
    logger.warning(message, *args)


class QueryTrace(TypedDict, total=False):
    """每轮查询的完整可观测结构；写入 ServiceState.query_trace 并在生成后打印为 JSON。"""

    raw_query: str
    normalized_query: str
    rewritten_query: str
    is_followup: bool
    is_faq: bool
    faq_confidence: float
    topics: list[str]
    time_expr: str | None
    entities: dict[str, str | None]
    entities_canonical: dict[str, bool]   # 每个字段是否命中词典
    metadata_filters: dict[str, object]
    top_k: int
    inherit_score: float
    inherited: bool
    need_clarify: bool
    # FAQ 精确匹配分支
    faq_attempted: bool
    faq_hit: bool
    faq_db_match: bool          # 是否命中 DB 编辑距离匹配
    faq_db_match_score: float | None
    faq_first_score: float | None
    # 主检索阶段
    retrieval_stage: str  # strict | widen_1 | widen_2 | ... | semantic_only | skipped
    retrieval_hit_count: int
    retrieval_first_score: float | None
    # Reranker
    rerank_used: bool
    rerank_top1_score: float | None
    # 耗时（ms）
    t_preprocess_ms: float
    t_faq_ms: float | None
    t_retrieve_ms: float | None
    t_rerank_ms: float | None
    t_generate_ms: float | None


_DIRECT_REPLY = "您需要了解产品与服务相关的问题吗？请告诉我具体问题～"
_NON_PRODUCT_REPLY = "抱歉，我只能回答关于产品和服务相关的问题。如果您有相关疑问，请告诉我！"

_ROUTER_SYSTEM = """你是路由分类器：判断用户这句话是否需要从知识库检索「产品、服务、规格、文档、功能」等才能回答。

规则：
- 需要检索 → 只回复一个词：rag
- 不需要（问候、闲聊、致谢或与业务无关等）→ 只回复一个词：direct
不要输出其它任何字符。"""

_ANSWER_SYSTEM = """基于下面「检索上下文」回答用户问题，简洁、可操作；不足则说明信息不足。

    【检索上下文】
    {retrieved_context}

    【用户问题】
    {user_query}
    -拒绝生硬写法 要有“呼吸感”与“情绪价值”
    -隐去所有关于搜索行为的描述性语句 如 ‘正在搜索’、‘检索显示’
    -最后不要做补充说明 比如：请注意 温馨提示
    """

_NextRoute = Literal["retrieve", "end"]
_MAX_CONTEXT_ROUNDS = 5
_INHERIT_MAX_TURN_GAP = 3
_INHERIT_MIN_DECAY = 0.45
_FAQ_HINTS = ("有没有", "是否", "支持吗", "能否", "可以吗", "是不是", "有无")
_TOPIC_HINTS = ("成分", "配料", "价格", "规格", "保质期", "怎么", "怎么样", "对比", "区别")
_PRONOUN_HINTS = ("它", "这个", "这款", "那款", "该产品", "这个产品", "这瓶", "那个")

# FAQ 分类置信度阈値：同时包含 FAQ 和信息类提示词时降低判断信心度
_FAQ_CONFIDENCE_THRESHOLD = 0.55

# Reranker 阈値
_RERANK_GENERATE_THRESHOLD = 0.70   # ≥ 进入生成
_RERANK_WIDEN_THRESHOLD = 0.40     # 0.40~0.70 放宽 filter 重试
_RERANK_TOP_K_CANDIDATE = 20       # Milvus 取候选数
_RERANK_TOP_N = 5                  # Reranker 取出带到 LLM

# filter 放宽顺序：优先移除最细粒度的字段
_WIDEN_KEY_ORDER = ("ingredient", "category", "brand", "product_name", "doc_type")


def _widen_filters(filters: dict[str, object]) -> dict[str, object] | None:
    """按 ``_WIDEN_KEY_ORDER`` 需移除一个 filter；如果已全空返回 None。"""
    for key in _WIDEN_KEY_ORDER:
        if key in filters:
            widened = dict(filters)
            widened.pop(key)
            return widened
    return None


def _format_reranked(reranked: list[tuple[float, str]]) -> str:
    """将 reranker 输出格式化为同 ``search_user_knowledge_vectors_sync`` 类似的字符串。"""
    if not reranked:
        return "未找到与查询相关的知识库片段。可尝试改写问题，或确认对应文件已解析并完成入库。"
    lines: list[str] = [f"共 {len(reranked)} 条相关片段（按相关度排序）：", ""]
    for i, (score, text) in enumerate(reranked, start=1):
        lines.append(f"### 片段 {i}（相关度 {score:.4f}）\n\n{text}")
        lines.append("")
    return "\n".join(lines).strip()


def _next_route_reducer(
    left: _NextRoute | None,
    right: _NextRoute | None,
) -> _NextRoute | None:
    """分类节点单次写入覆盖路由；首帧为 ``None``。"""
    return right if right is not None else left


def _dict_overwrite_reducer(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return right if right is not None else left


class ServiceState(TypedDict):
    """``messages`` 走 ``add_messages``；``next_route`` 供 ``add_conditional_edges`` 使用。"""
    messages: Annotated[list[AnyMessage], add_messages]
    next_route: Annotated[_NextRoute | None, _next_route_reducer]
    query_plan: Annotated[dict[str, Any] | None, _dict_overwrite_reducer]
    query_trace: Annotated[dict[str, Any] | None, _dict_overwrite_reducer]


def _last_user_text(state: ServiceState) -> str:
    """取最近一条用户话；兼容 LangGraph Studio 等入口里仍为 ``dict`` 的 message。"""
    raw = state.get("messages") or []
    if not raw:
        return ""
    if any(isinstance(m, dict) for m in raw):
        try:
            msgs = convert_to_messages(raw)
        except Exception:
            msgs = raw
    else:
        msgs = raw
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            c = m.content
            if isinstance(c, str) and c.strip():
                return c.strip()
            if isinstance(c, list):
                parts: list[str] = []
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                joined = " ".join(parts).strip()
                if joined:
                    return joined
        elif isinstance(m, dict):
            role = (str(m.get("type") or m.get("role") or "")).lower()
            if role in ("human", "user"):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()
                if isinstance(c, list):
                    parts = [
                        str(b.get("text", ""))
                        for b in c
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = " ".join(parts).strip()
                    if joined:
                        return joined
    return ""


def _recent_user_texts(state: ServiceState, max_rounds: int = _MAX_CONTEXT_ROUNDS) -> list[str]:
    raw = state.get("messages") or []
    if any(isinstance(m, dict) for m in raw):
        try:
            msgs = convert_to_messages(raw)
        except Exception:
            msgs = raw
    else:
        msgs = raw

    out: list[str] = []
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            text = _message_content_str(m).strip()
            if text:
                out.append(text)
        elif isinstance(m, dict):
            role = (str(m.get("type") or m.get("role") or "")).lower()
            if role in ("human", "user"):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    out.append(c.strip())
        if len(out) >= max_rounds:
            break
    return list(reversed(out))


def _extract_scalar_entity(entities: list[Any], entity_type: EntityType) -> str | None:
    for item in entities:
        if getattr(item, "entity_type", None) == entity_type:
            text = str(getattr(item, "text", "") or "").strip()
            if text:
                return text
    return None


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def _decay(turn_gap: int) -> float:
    if turn_gap <= 1:
        return 1.0
    if turn_gap >= _INHERIT_MAX_TURN_GAP:
        return 0.0
    return 1.0 - (turn_gap - 1) / max(1, _INHERIT_MAX_TURN_GAP - 1)


def _parse_first_score(result: str) -> float | None:
    m = re.search(r"相关度\s*([0-9.]+)", result)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_config_knowledge_base_id(config: RunnableConfig | None) -> int | None:
    configurable = (config or {}).get("configurable") or {}
    raw = configurable.get("knowledge_base_id")
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw).strip()
    if not s:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return n if n > 0 else None


def _is_no_hit(result: str) -> bool:
    s = (result or "").strip()
    return "未找到与查询相关" in s or s.startswith("检索失败")


async def _build_query_plan(state: ServiceState, config: RunnableConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (plan, partial_trace) — 包含实体归一化与 FAQ 置信度。"""
    _t0 = time.monotonic()
    query = _last_user_text(state)
    normalized_query = re.sub(r"\s+", " ", query).strip()
    recent_user_texts = _recent_user_texts(state)
    history_context = "\n".join(recent_user_texts[:-1]) if len(recent_user_texts) > 1 else ""

    configurable = (config or {}).get("configurable") or {}
    user_id_for_dict = _parse_config_user_id(configurable.get("user_id"))
    biz_code: str | None = str(configurable.get("biz_code") or "").strip() or None
    kb_id = _parse_config_knowledge_base_id(config)

    entities_raw: list[Any] = []
    if user_id_for_dict:
        try:
            async with async_session() as session:
                entities_raw = await extract_entities_by_chat_llm(
                    normalized_query,
                    owner_user_id=user_id_for_dict,
                    session=session,
                    title="query",
                )
        except Exception:
            logger.warning("查询实体抽取失败，退化为无实体过滤", exc_info=True)

    brand_raw = _extract_scalar_entity(entities_raw, EntityType.BRAND)
    product_name_raw = _extract_scalar_entity(entities_raw, EntityType.PRODUCT)
    category_raw = _extract_scalar_entity(entities_raw, EntityType.CATEGORY)

    is_followup = _contains_any(normalized_query, _PRONOUN_HINTS)
    prev_plan = state.get("query_plan") or {}
    inherit_turn_gap = int(prev_plan.get("inherit_turn_gap") or 0) + 1
    inherit_score = _decay(inherit_turn_gap)
    inherited = False
    if is_followup and inherit_score >= _INHERIT_MIN_DECAY:
        prev_entities = prev_plan.get("entities") or {}
        if not brand_raw and isinstance(prev_entities.get("brand"), str):
            brand_raw = str(prev_entities["brand"]).strip() or None
            inherited = inherited or bool(brand_raw)
        if not product_name_raw and isinstance(prev_entities.get("product_name"), str):
            product_name_raw = str(prev_entities["product_name"]).strip() or None
            inherited = inherited or bool(product_name_raw)
        if not category_raw and isinstance(prev_entities.get("category"), str):
            category_raw = str(prev_entities["category"]).strip() or None

    # ── 实体归一化：走词典 canonical（KB > Biz > Global），未命中保留原文 ─────────
    entities_canonical: dict[str, bool] = {}

    brand = brand_raw
    product_name = product_name_raw
    category = category_raw

    if user_id_for_dict:
        try:
            async with async_session() as session:
                resolved = await resolve_entities_batch(
                    brand_raw,
                    product_name_raw,
                    category_raw,
                    owner_user_id=user_id_for_dict,
                    biz_code=biz_code,
                    knowledge_base_id=kb_id,
                    session=session,
                )
            brand = resolved.get("brand")
            product_name = resolved.get("product_name")
            category = resolved.get("category")
            entities_canonical = {
                "brand": brand != brand_raw,
                "product_name": product_name != product_name_raw,
                "category": category != category_raw,
            }
        except Exception:
            logger.warning("实体词典归一化失败，退化使用模型原始文本", exc_info=True)

    # ── FAQ 置信度：同时含 FAQ + 信息类 hints 则降低信心 ────────────────────────
    faq_hint_count = sum(1 for h in _FAQ_HINTS if h in normalized_query)
    topic_hint_count = sum(1 for h in _TOPIC_HINTS if h in normalized_query)
    hint_total = faq_hint_count + topic_hint_count
    # 显式处理分母为 0：说明既无 FAQ 词也无信息类词，置信度定义为 0.0
    faq_confidence = 0.0 if hint_total == 0 else (faq_hint_count / hint_total)
    is_faq = faq_hint_count > 0 and faq_confidence >= _FAQ_CONFIDENCE_THRESHOLD
    topics = [x for x in _TOPIC_HINTS if x in normalized_query][:4]

    m = re.search(r"(今天|昨天|最近\d+天|最近一周|最近一月|今年|去年)", normalized_query)
    time_expr = m.group(1) if m else None

    metadata_filters: dict[str, object] = {}
    if brand:
        metadata_filters["brand"] = brand
    if product_name:
        metadata_filters["product_name"] = product_name
    if category:
        metadata_filters["category"] = category
    if product_name or brand or category:
        metadata_filters["doc_type"] = "product_doc"

    rewrite_parts: list[str] = [normalized_query]
    if brand and brand not in normalized_query:
        rewrite_parts.append(f"品牌:{brand}")
    if product_name and product_name not in normalized_query:
        rewrite_parts.append(f"产品:{product_name}")
    if category and category not in normalized_query:
        rewrite_parts.append(f"品类:{category}")
    if time_expr and time_expr not in normalized_query:
        rewrite_parts.append(f"时间:{time_expr}")
    rewritten_query = "；".join([x for x in rewrite_parts if x]).strip("；")

    top_k = 3 if is_faq else 8
    need_clarify = False
    clarify_question = None
    if is_followup and not (brand or product_name):
        need_clarify = True
        clarify_question = "你指的是哪一个产品或品牌？"

    plan = {
        "raw_query": query,
        "normalized_query": normalized_query,
        "rewritten_query": rewritten_query,
        "history_context": history_context,
        "is_followup": is_followup,
        "is_faq": is_faq,
        "topics": topics,
        "time_expr": time_expr,
        "entities": {
            "brand": brand,
            "product_name": product_name,
            "category": category,
        },
        "metadata_filters": metadata_filters,
        "top_k": top_k,
        "inherit_turn_gap": inherit_turn_gap if inherited else 0,
        "inherit_score": round(inherit_score, 3) if inherited else 0.0,
        "need_clarify": need_clarify,
        "clarify_question": clarify_question,
        "knowledge_base_id": _parse_config_knowledge_base_id(config),
    }

    t_preprocess_ms = round((time.monotonic() - _t0) * 1000, 1)
    _trace_log(
        "query_plan followup=%s faq=%s(conf=%.2f) entities=%s filters=%s top_k=%s inherited=%s t_ms=%.1f",
        plan["is_followup"],
        plan["is_faq"],
        faq_confidence,
        plan["entities"],
        plan["metadata_filters"],
        plan["top_k"],
        inherited,
        t_preprocess_ms,
    )

    partial_trace: dict[str, Any] = {
        "raw_query": query,
        "normalized_query": normalized_query,
        "rewritten_query": rewritten_query,
        "is_followup": is_followup,
        "is_faq": is_faq,
        "faq_confidence": round(faq_confidence, 3),
        "topics": topics,
        "time_expr": time_expr,
        "entities": plan["entities"],
        "entities_canonical": entities_canonical,
        "metadata_filters": metadata_filters,
        "top_k": top_k,
        "inherit_score": plan["inherit_score"],
        "inherited": inherited,
        "need_clarify": need_clarify,
        "faq_attempted": False,
        "faq_hit": False,
        "faq_db_match": False,
        "faq_db_match_score": None,
        "faq_first_score": None,
        "retrieval_stage": "skipped",
        "retrieval_hit_count": 0,
        "retrieval_first_score": None,
        "rerank_used": False,
        "rerank_top1_score": None,
        "t_preprocess_ms": t_preprocess_ms,
        "t_faq_ms": None,
        "t_retrieve_ms": None,
        "t_rerank_ms": None,
        "t_generate_ms": None,
    }
    return plan, partial_trace


def _message_content_str(msg: BaseMessage) -> str:
    c = getattr(msg, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            str(b.get("text", ""))
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(parts).strip()
    return str(c or "")


def _parse_config_user_id(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw).strip()
    if not s:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return n if n > 0 else None


def _resolve_user_id(config: RunnableConfig | None) -> int:
    configurable = (config or {}).get("configurable") or {}
    uid = _parse_config_user_id(configurable.get("user_id"))
    if uid is not None:
        return uid
    fb = (os.environ.get("LANGGRAPH_DEV_USER_ID") or "").strip()
    if fb:
        uid = _parse_config_user_id(fb)
        if uid is not None:
            logger.warning(
                "configurable.user_id 未传入，已使用 LANGGRAPH_DEV_USER_ID=%s（仅本地调试用）",
                uid,
            )
            return uid
    raise ValueError(
        "缺少有效的 configurable.user_id（须为正整数），无法创建会话级 LLM",
    )


def _needs_rag_from_text(body: str) -> bool:
    """解析路由模型输出：rag / direct。"""
    s = body.strip().lower()
    if "rag" in s and "direct" not in s:
        return True
    if "direct" in s and "rag" not in s:
        return False
    if re.match(r"^\s*rag\s*$", s, re.I):
        return True
    if re.match(r"^\s*direct\s*$", s, re.I):
        return False
    return True


async def _run_router(llm: Any, text: str, parent: RunnableConfig | None) -> bool:
    """内部路由 LLM：使用独立 callback，避免 token 进入 LangGraph messages 流。"""
    invoke_cfg = patch_config(parent, callbacks=AsyncCallbackManager([]))
    base = [
        SystemMessage(content=_ROUTER_SYSTEM),
        HumanMessage(content=text),
    ]
    resp = await llm.ainvoke(base, config=invoke_cfg)
    return _needs_rag_from_text(_message_content_str(resp))


async def classify_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    """基于 preprocess 结果决定 direct / retrieve，避免多轮追问在分类前被误伤。"""
    plan = state.get("query_plan") or {}
    text = str(plan.get("rewritten_query") or _last_user_text(state)).strip()
    history_context = str(plan.get("history_context") or "").strip()
    entities = plan.get("entities") or {}

    if not text:
        return {
            "messages": [AIMessage(content=_DIRECT_REPLY)],
            "next_route": "end",
        }

    if bool(plan.get("is_followup")) or bool(plan.get("is_faq")):
        return {"next_route": "retrieve"}

    has_entity = any(
        isinstance(entities.get(key), str) and str(entities.get(key)).strip()
        for key in ("brand", "product_name", "category")
    )
    if has_entity:
        return {"next_route": "retrieve"}

    router_input = text if not history_context else f"历史对话:\n{history_context}\n\n当前问题:\n{text}"

    user_id = _resolve_user_id(config)
    async with async_session() as session:
        llm = await chat_llm(session, user_id, temperature_override=0.0)
    if not await _run_router(llm, router_input, config):
        return {
            "messages": [AIMessage(content=_NON_PRODUCT_REPLY)],
            "next_route": "end",
        }
    return {"next_route": "retrieve"}


async def preprocess_query_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    plan, trace = await _build_query_plan(state, config)
    if plan.get("need_clarify"):
        return {
            "query_plan": plan,
            "query_trace": trace,
            "messages": [AIMessage(content=str(plan.get("clarify_question") or "请补充更具体的问题。"))],
        }
    return {"query_plan": plan, "query_trace": trace}


_FAQ_HIT_THRESHOLD = 0.70


_FAQ_DOC_TYPE = "faq_doc"
_FAQ_DB_EDIT_THRESHOLD = 0.80  # difflib ratio 阈值：近似 Q 命中


async def _faq_db_question_match(
    query: str,
    *,
    owner_user_id: int,
    knowledge_base_id: int | None,
) -> tuple[int | None, str | None, float]:
    """在 MySQL FileAssetModel.extra_metadata.faq_questions 中做编辑距离匹配。

    返回 (file_id, matched_question, ratio)；未命中时 file_id=None。
    """
    from sqlalchemy import select

    best_ratio = 0.0
    best_file_id: int | None = None
    best_question: str | None = None
    q_lower = query.lower().replace(" ", "")

    try:
        async with async_session() as session:
            stmt = (
                select(FileAssetModel.id, FileAssetModel.extra_metadata)
                .join(
                    KnowledgeBaseFileModel,
                    KnowledgeBaseFileModel.file_id == FileAssetModel.id,
                )
                .where(
                    FileAssetModel.owner_user_id == owner_user_id,
                    FileAssetModel.is_deleted == False,  # noqa: E712
                )
            )
            if knowledge_base_id is not None:
                stmt = stmt.where(KnowledgeBaseFileModel.knowledge_base_id == knowledge_base_id)
            rows = (await session.execute(stmt)).all()

        for file_id, extra in rows:
            if not extra or not isinstance(extra, dict):
                continue
            faq_qs = extra.get("faq_questions")
            if not isinstance(faq_qs, list):
                continue
            for fq in faq_qs:
                fq_lower = str(fq).lower().replace(" ", "")
                ratio = difflib.SequenceMatcher(None, q_lower, fq_lower).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_file_id = file_id
                    best_question = str(fq)
    except Exception:
        logger.warning("FAQ DB 编辑距离匹配失败", exc_info=True)

    if best_ratio >= _FAQ_DB_EDIT_THRESHOLD:
        return best_file_id, best_question, best_ratio
    return None, None, best_ratio


async def faq_match_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    """FAQ 精确匹配分支：
    1. 先做 DB 编辑距离匹配 faq_questions 字段 → 命中则以 file_id 过滤检索
    2. 未命中则用 doc_type=faq_doc 混合检索兜底
    3. 用 Reranker 评分决定是否短路进 generate
    """
    plan = state.get("query_plan") or {}
    trace = dict(state.get("query_trace") or {})
    _t0 = time.monotonic()

    query = str(plan.get("rewritten_query") or _last_user_text(state))
    normalized_query = str(plan.get("normalized_query") or query)
    knowledge_base_id = plan.get("knowledge_base_id")
    owner_user_id = _resolve_user_id(config)

    # ── Step 1: DB 编辑距离匹配 ───────────────────────────────────────────────
    db_file_id, db_question, db_ratio = await _faq_db_question_match(
        normalized_query,
        owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
    )
    trace["faq_db_match"] = db_file_id is not None
    trace["faq_db_match_score"] = round(db_ratio, 4)

    # ── Step 2: 检索（file_id 精准 or doc_type 兜底） ────────────────────────
    if db_file_id is not None:
        faq_filters: dict[str, object] = {"file_id": db_file_id}
        search_query = db_question or query
    else:
        faq_filters = {"doc_type": _FAQ_DOC_TYPE}
        ent = plan.get("entities") or {}
        if ent.get("brand"):
            faq_filters["brand"] = ent["brand"]
        if ent.get("product_name"):
            faq_filters["product_name"] = ent["product_name"]
        search_query = query

    raw_hits = await asyncio.to_thread(
        search_user_knowledge_vectors_raw,
        query=search_query,
        owner_user_id=owner_user_id,
        top_k=10,
        knowledge_base_id=knowledge_base_id,
        metadata_filters=faq_filters,
    )

    # ── Step 3: Rerank → 决定是否命中 ────────────────────────────────────────
    rerank_top1: float | None = None
    hit = False
    result_text = ""

    if raw_hits:
        passages = [h["text"] for h in raw_hits if h.get("text")]
        if passages:
            try:
                _tr0 = time.monotonic()
                async with async_session() as session:
                    reranked = await rerank_to_scored_tuples(
                        session,
                        owner_user_id,
                        query=query,
                        passages=passages,
                        top_n=3,
                    )
                trace["t_rerank_ms"] = round((time.monotonic() - _tr0) * 1000, 1)
                if reranked:
                    trace["rerank_used"] = True
                    rerank_top1 = reranked[0][0]
                    hit = rerank_top1 >= _FAQ_HIT_THRESHOLD
                    result_text = _format_reranked(reranked)
                else:
                    first_score = raw_hits[0]["score"] if raw_hits else None
                    rerank_top1 = first_score
                    hit = first_score is not None and first_score >= _FAQ_HIT_THRESHOLD
                    result_text = _format_reranked([(h["score"], h["text"]) for h in raw_hits[:3]])
            except Exception:
                logger.warning("FAQ reranker 失败，降级用 Milvus 分数", exc_info=True)
                first_score = raw_hits[0]["score"] if raw_hits else None
                rerank_top1 = first_score
                hit = first_score is not None and first_score >= _FAQ_HIT_THRESHOLD
                result_text = _format_reranked([(h["score"], h["text"]) for h in raw_hits[:3]])

    t_faq_ms = round((time.monotonic() - _t0) * 1000, 1)
    trace["faq_attempted"] = True
    trace["faq_hit"] = hit
    trace["faq_first_score"] = rerank_top1
    trace["rerank_top1_score"] = rerank_top1
    trace["t_faq_ms"] = t_faq_ms

    _trace_log(
        "faq_match db_match=%s(%.2f) hit=%s rerank_top1=%s t_ms=%.1f",
        db_file_id is not None,
        db_ratio,
        hit,
        rerank_top1,
        t_faq_ms,
    )

    updates: dict[str, Any] = {"query_trace": trace}
    if hit and result_text:
        updates["messages"] = [AIMessage(content=result_text, name="knowledge_base_search")]
    return updates


def route_after_faq(state: ServiceState) -> Literal["generate", "retrieve"]:
    trace = state.get("query_trace") or {}
    if trace.get("faq_hit"):
        return "generate"
    return "retrieve"


async def retrieve_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    """分阶段检索：初始严格 filter → 迭代放宽 filter → 语义兜底；每阶段均用 Reranker 判断是否进入生成。"""
    plan = state.get("query_plan") or {}
    trace = dict(state.get("query_trace") or {})
    if bool(plan.get("need_clarify")):
        return {}

    _t0 = time.monotonic()
    query = str(plan.get("rewritten_query") or _last_user_text(state))
    top_k = int(plan.get("top_k") or 8)
    knowledge_base_id = plan.get("knowledge_base_id")
    metadata_filters = plan.get("metadata_filters")

    owner_user_id = _resolve_user_id(config)
    current_filters: dict[str, object] = dict(metadata_filters or {})
    fallback_stage = "strict"
    rerank_top1: float | None = None
    reranked: list[tuple[float, str]] = []

    async def _fetch_and_rerank(
        search_query: str,
        filters: dict[str, object],
        candidate_k: int,
    ) -> tuple[list[tuple[float, str]], float | None]:
        """Raw Milvus 检索 + Reranker，返回 (reranked_list, top1_score)。"""
        raw = await asyncio.to_thread(
            search_user_knowledge_vectors_raw,
            query=search_query,
            owner_user_id=owner_user_id,
            top_k=candidate_k,
            knowledge_base_id=knowledge_base_id,
            metadata_filters=filters,
        )
        if not raw:
            return [], None
        passages = [h["text"] for h in raw if h.get("text")]
        if not passages:
            return [], None
        try:
            _tr0 = time.monotonic()
            async with async_session() as session:
                ranked = await rerank_to_scored_tuples(
                    session,
                    owner_user_id,
                    query=search_query,
                    passages=passages,
                    top_n=_RERANK_TOP_N,
                )
            trace["t_rerank_ms"] = round((time.monotonic() - _tr0) * 1000, 1)
            if ranked is not None:
                trace["rerank_used"] = True
            else:
                ranked = [(h["score"], h["text"]) for h in raw[:_RERANK_TOP_N]]
        except Exception:
            logger.warning("Reranker 失败，降级用 Milvus 分数", exc_info=True)
            ranked = [(h["score"], h["text"]) for h in raw[:_RERANK_TOP_N]]
        top1 = ranked[0][0] if ranked else None
        return ranked, top1

    # ── Stage 1: 严格 filter ─────────────────────────────────────────────────
    reranked, rerank_top1 = await _fetch_and_rerank(query, current_filters, _RERANK_TOP_K_CANDIDATE)

    # ── Stage 2+: 迭代放宽 filter（ingredient → category → brand → product → doc_type）
    widen_step = 0
    while (not reranked or (rerank_top1 is not None and rerank_top1 < _RERANK_GENERATE_THRESHOLD)):
        next_filters = _widen_filters(current_filters)
        if next_filters is None:
            break  # 已无 filter 可放宽，进入语义兜底
        widen_step += 1
        current_filters = next_filters
        fallback_stage = f"widen_{widen_step}"
        reranked, rerank_top1 = await _fetch_and_rerank(query, current_filters, _RERANK_TOP_K_CANDIDATE)
        if reranked and rerank_top1 is not None and rerank_top1 >= _RERANK_GENERATE_THRESHOLD:
            break

    # ── Stage N: 语义兜底（去掉所有动态 filter）────────────────────────────────
    if not reranked or (rerank_top1 is not None and rerank_top1 < _RERANK_WIDEN_THRESHOLD):
        fallback_stage = "semantic_only"
        sem_query = str(plan.get("normalized_query") or query)
        reranked, rerank_top1 = await _fetch_and_rerank(sem_query, {}, _RERANK_TOP_K_CANDIDATE)

    t_retrieve_ms = round((time.monotonic() - _t0) * 1000, 1)
    trace["retrieval_stage"] = fallback_stage
    trace["retrieval_hit_count"] = len(reranked)
    trace["retrieval_first_score"] = reranked[0][0] if reranked else None
    trace["rerank_top1_score"] = rerank_top1
    trace["t_retrieve_ms"] = t_retrieve_ms

    _trace_log(
        "retrieve query=%s filters=%s stage=%s hits=%d rerank_top1=%s t_ms=%.1f",
        query,
        current_filters,
        fallback_stage,
        len(reranked),
        rerank_top1,
        t_retrieve_ms,
    )

    result_text = _format_reranked(reranked) if reranked else "未找到与查询相关的知识库片段。可尝试改写问题，或确认对应文件已解析并完成入库。"
    return {
        "query_trace": trace,
        "messages": [AIMessage(content=result_text, name="knowledge_base_search")],
    }


async def generate_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    """生成节点：从消息历史中取出知识库检索结果，拼入系统提示，调用 LLM 生成回答。"""
    _t0 = time.monotonic()
    query = _last_user_text(state)
    plan = state.get("query_plan") or {}

    # 从消息历史中查找知识库检索结果
    retrieved_context = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") == "knowledge_base_search":
            retrieved_context = _message_content_str(msg)
            break

    # 如果没有检索结果，使用默认消息
    if not retrieved_context.strip():
        retrieved_context = "无检索到的相关知识库内容。"

    display_query = str(plan.get("rewritten_query") or query)
    prompt = _ANSWER_SYSTEM.format(retrieved_context=retrieved_context, user_query=display_query)
    user_id = _resolve_user_id(config)

    async with async_session() as session:
        llm = await chat_llm(session, user_id, temperature_override=0.1)
    response = await llm.ainvoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(content=display_query),
        ],
        config=config,
    )
    t_generate_ms = round((time.monotonic() - _t0) * 1000, 1)

    # ── 标准查询结构输出（可观测日志）──
    trace = dict(state.get("query_trace") or {})
    trace["t_generate_ms"] = t_generate_ms
    _trace_log("query_trace %s", json.dumps(trace, ensure_ascii=False, default=str))

    return {"messages": [response], "query_trace": trace}


def route_after_classify(state: ServiceState) -> Literal["faq_match", "retrieve", "__end__"]:
    if state.get("next_route") != "retrieve":
        return END
    plan = state.get("query_plan") or {}
    if bool(plan.get("is_faq")):
        return "faq_match"
    return "retrieve"


def route_after_preprocess(state: ServiceState) -> Literal["classify", "__end__"]:
    plan = state.get("query_plan") or {}
    if bool(plan.get("need_clarify")):
        return END
    return "classify"


_builder = (
    StateGraph(ServiceState)
    .add_node("short_term_window", short_term_window_node)
    .add_node("preprocess_query", preprocess_query_node)
    .add_node("classify", classify_node)
    .add_node("faq_match", faq_match_node)
    .add_node("retrieve", retrieve_node)
    .add_node("advanced_memory_retrieve", advanced_memory_retrieve_node)
    .add_node("generate", generate_node)
    .add_node("advanced_memory_write", advanced_memory_write_node)
    .add_edge(START, "short_term_window")
    .add_edge("short_term_window", "preprocess_query")
    .add_conditional_edges("preprocess_query", route_after_preprocess)
    .add_conditional_edges("classify", route_after_classify)
    .add_conditional_edges("faq_match", route_after_faq)
    .add_edge("retrieve", "advanced_memory_retrieve")
    .add_edge("advanced_memory_retrieve", "generate")
    .add_edge("generate", "advanced_memory_write")
    .add_edge("advanced_memory_write", END)
)

graph = _builder.compile(
    name="graph_service",
)

# 用于直连调用的 graph（带 checkpointer 和 LangMem store）
graph_with_checkpoint = _builder.compile(
    checkpointer=get_graph_checkpointer(),
    store=get_langgraph_store(),
    name="graph_service_direct",
)
