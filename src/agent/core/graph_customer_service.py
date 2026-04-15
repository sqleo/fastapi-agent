"""智能客服 LangGraph：由大模型归类是否产品相关问题；仅判为是时进入 RAG Agent."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.control.interrupt import token_level_pause_middleware
from agent.injection import inject_llm_from_global_settings
from agent.memory.context_window import short_term_message_window
from agent.memory.langmem import get_langgraph_store
from agent.middleware import filter_tools_by_enabled_config
from agent.middleware.tool_policy import strip_tool_calls_not_in_enabled_list
from agent.tools.customer_service_tools import (
    ALL_CUSTOMER_SERVICE_TOOLS,
)
from utils.langgraph_sse_error_patch import apply_vendor_api_sse_patch
from utils.llm_init import create_llm
from utils.sql_db import async_session

apply_vendor_api_sse_patch()

logger = logging.getLogger("agent.graph_customer_service")

tools = ALL_CUSTOMER_SERVICE_TOOLS


_CUSTOMER_SERVICE_SYSTEM_PROMPT = f"""你是一个精确、简洁的问答助手。
- 只使用提供的上下文回答问题，不要添加额外解释、问候、背景或无关内容。
- 回答控制在100-200字以内（或最多3-5句）。
- 直接给出答案，使用 bullet points 或编号列表，避免长段落。
- 如果上下文不足，直接说“信息不足，无法回答”。

上下文：
{{retrieved_context}}

问题：{{user_query}}

答案："""

_placeholder_model = init_chat_model(
    "placeholder",
    model_provider="openai",
    base_url="https://api.openai.com/v1",
    api_key="placeholder-unused",
)

_NO_ANSWER_TEXT = "根据提供的资料，无法找到相关答案。"


class _ProductIntent(BaseModel):
    is_product_question: bool = Field(
        description="用户是否在询问本公司/品牌产品、购买与使用、售后与活动等与知识库业务相关的问题",
    )


_CLASSIFIER_SYSTEM = """你是问题类型分类器，只根据用户**当前这条**文字判断是否需要走「产品知识库」。

判为「是」（is_product_question=true）：
- 询问商品/产品有哪些、是什么、规格、价格、购买或领取渠道、用法用量、成分、功效、适用人群、保存、喝了会怎样、副作用、是否拉肚子等**与在售商品/饮品/保健品使用相关**的问题
- 售后、退换、保修、投诉、官方活动/优惠、与上述业务直接相关的政策说明

判为「否」（is_product_question=false）：
- 纯闲聊、问候、与公司业务无关的百科、旅游/本地生活、天气、其它品牌、编程解题等**明显无关**的话题

重要：只要问题**可能**与本公司产品、购买或使用有关，应判为「是」，交给知识库检索；**边界模糊时判为「是」**（宁可多检一次，由知识库无命中再说明无法找到）。"""

_JSON_BOOL_IN_RE = re.compile(r'"is_product_question"\s*:\s*(true|false)', re.I)


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


def _resolve_user_id(configurable: dict[str, Any]) -> int:
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
        "LangGraph 调用缺少有效的 configurable.user_id（须为正整数），无法执行问题分类",
    )


def _last_user_text(state: MessagesState) -> str:
    for m in reversed(state["messages"]):
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
    return ""


def _message_content_to_str(msg: Any) -> str:
    c = getattr(msg, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return " ".join(parts).strip()
    return str(c or "")


def _parse_product_intent_from_text(raw: str) -> _ProductIntent | None:
    s = raw.strip()
    if "```" in s:
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        data = json.loads(s)
        if isinstance(data, dict) and "is_product_question" in data:
            v = data["is_product_question"]
            if isinstance(v, bool):
                return _ProductIntent(is_product_question=v)
    except json.JSONDecodeError:
        pass
    m = _JSON_BOOL_IN_RE.search(raw)
    if m:
        return _ProductIntent(is_product_question=m.group(1).lower() == "true")
    return None


async def _run_product_classifier(llm: Any, text: str) -> _ProductIntent:
    """先尝试 structured_output；不支持或失败时改为要求模型输出一行 JSON 并解析."""
    base_messages = [
        SystemMessage(content=_CLASSIFIER_SYSTEM),
        HumanMessage(content=text),
    ]
    try:
        structured = llm.with_structured_output(_ProductIntent)
        return await structured.ainvoke(base_messages)
    except Exception:
        logger.warning(
            "classifier with_structured_output failed, using JSON text fallback",
            exc_info=True,
        )
    resp = await llm.ainvoke(
        [SystemMessage(content=_CLASSIFIER_SYSTEM), HumanMessage(content=text)],
    )
    body = _message_content_to_str(resp)
    parsed = _parse_product_intent_from_text(body)
    if parsed is not None:
        return parsed
    logger.warning(
        "classifier JSON parse failed, fail-open to RAG; raw=%r",
        body[:400],
    )
    return _ProductIntent(is_product_question=True)


async def classify_product_gate(
    state: MessagesState, config: RunnableConfig
) -> Command:
    """非产品类问题直接结束，不进入带 RAG 的 Agent."""
    configurable = (config or {}).get("configurable") or {}
    text = _last_user_text(state)
    if not text:
        return Command(
            update={"messages": [AIMessage(content=_NO_ANSWER_TEXT)]},
            goto=END,
        )

    user_id = _resolve_user_id(configurable)
    override = configurable.get("llm_temperature")
    temperature_override = float(override) if override is not None else None

    try:
        async with async_session() as session:
            llm = await create_llm(
                session,
                user_id,
                temperature_override=temperature_override,
            )
        out = await _run_product_classifier(llm, text)
    except Exception:
        logger.exception("classify_product_gate failed, fail-open to RAG")
        return Command(goto="rag_agent")

    if out.is_product_question:
        return Command(goto="rag_agent")

    return Command(
        update={"messages": [AIMessage(content=_NO_ANSWER_TEXT)]},
        goto=END,
    )


_cs_rag_agent = create_agent(
    _placeholder_model,
    tools=tools,
    system_prompt=_CUSTOMER_SERVICE_SYSTEM_PROMPT,
    store=get_langgraph_store(),
    middleware=[
        strip_tool_calls_not_in_enabled_list,
        filter_tools_by_enabled_config,
        short_term_message_window,
        token_level_pause_middleware,
        inject_llm_from_global_settings,
    ],
    name="智能客服-RAG",
)

_builder = (
    StateGraph(MessagesState)
    .add_node("classify_product_gate", classify_product_gate)
    .add_node("rag_agent", _cs_rag_agent)
    .add_edge(START, "classify_product_gate")
    .add_edge("rag_agent", END)
)

graph = _builder.compile(
    store=get_langgraph_store(),
    name="智能客服",
)
