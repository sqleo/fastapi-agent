"""Rerank：统一走 LiteLLM ``arerank``（Cohere 兼容协议）。

配置约定（与 https://docs.litellm.ai/docs/rerank 、各 provider 文档一致）：
"""

from __future__ import annotations

import logging
from typing import List

import litellm
from litellm import arerank
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned

logger = logging.getLogger(__name__)

# 平台种子里的厂商 code → LiteLLM rerank 用的 provider 段（与 litellm.provider_list 一致）
_VENDOR_CODE_TO_LITELLM_RERANK_PREFIX: dict[str, str] = {
    "cohere": "cohere",
    "jina": "jina_ai",
    "deepinfra": "deepinfra",
}


def _resolve_litellm_rerank_model(*, stored_model: str, vendor: LlmVendorModel) -> str:
    raw = (stored_model or "").strip()
    if not raw:
        raise ValueError("rerank_model 为空")
    extra = vendor.extra_config if isinstance(vendor.extra_config, dict) else {}

    full = extra.get("litellm_rerank_model")
    if isinstance(full, str) and full.strip():
        return full.strip()

    if "/" in raw:
        prefix, _rest = raw.split("/", 1)
        if prefix in litellm.provider_list:
            return raw

    prov = extra.get("litellm_rerank_provider")
    if isinstance(prov, str) and prov.strip():
        p = prov.strip()
        if p not in litellm.provider_list:
            raise ValueError(
                f"extra_config.litellm_rerank_provider={p!r} 不是 LiteLLM 已知 provider"
            )
        return f"{p}/{raw}"

    vcode = (vendor.code or "").strip().lower()
    mapped = _VENDOR_CODE_TO_LITELLM_RERANK_PREFIX.get(vcode)
    if mapped:
        return f"{mapped}/{raw}"

    raise ValueError(
        "Rerank 请在全局设置填写 LiteLLM 标准 model（例如 "
        "deepinfra/Qwen/Qwen3-Reranker-4B、cohere/rerank-english-v3.0），"
        "或在厂商 extra_config 中设置 litellm_rerank_model / litellm_rerank_provider。"
        "详见 https://docs.litellm.ai/docs/rerank"
    )


async def rerank_llm(
    session: AsyncSession,
    owner_user_id: int,
    *,
    query: str,
    documents: List[str],
    top_n: int | None = None,
) -> list[dict]:
    """
    通用重排序函数
    返回格式: [{'index': int, 'relevance_score': float, 'text': str}, ...]
    """
    if not documents:
        return []

    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)

    if not settings.rerank_vendor_id or not (settings.rerank_model or "").strip():
        logger.warning("未配置 Rerank 模型，跳过重排序")
        return []

    stmt = select(LlmVendorModel).where(
        LlmVendorModel.id == settings.rerank_vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    vendor = result.scalar_one_or_none()

    if not vendor:
        raise ValueError(f"Rerank 厂商不存在: id={settings.rerank_vendor_id}")

    base_url = (vendor.base_url or "").strip()
    api_key = (vendor.api_key or "").strip()
    tn = top_n if top_n is not None else len(documents)

    try:
        vcode = (vendor.code or "").strip().lower()
        model_name = settings.rerank_model.strip()
        is_dashscope = ("dashscope" in base_url or vcode == "aliyun" or model_name.lower().startswith("qwen"))

        if is_dashscope:
            import httpx
            # Use specific dashscope endpoint
            dashscope_url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
            
            # Clean model name (e.g. Qwen/Qwen3-Reranker-0.6B -> qwen3-rerank)
            if "/" in model_name:
                model_name = model_name.split("/")[-1]
            lower_model = model_name.lower()
            if "qwen3" in lower_model:
                model_name = "qwen3-rerank"
            elif "gte" in lower_model:
                model_name = "gte-rerank"
                
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "input": {
                    "query": query,
                    "documents": documents
                },
                "parameters": {
                    "return_documents": False,
                    "top_n": tn
                }
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(dashscope_url, headers=headers, json=payload, timeout=60.0)
                if resp.status_code != 200:
                    raise Exception(f"DashScope Rerank error: {resp.status_code} {resp.text}")
                data = resp.json()
            
            results = data.get("output", {}).get("results", [])
            reranked_results = []
            for r in results:
                idx = r.get("index")
                score = r.get("relevance_score", 0.0)
                if idx is not None and 0 <= idx < len(documents):
                    reranked_results.append({
                        "index": idx,
                        "relevance_score": score,
                        "text": documents[idx]
                    })
            return reranked_results

        model = _resolve_litellm_rerank_model(
            stored_model=model_name,
            vendor=vendor,
        )
        kwargs: dict = {
            "model": model,
            "query": query,
            "documents": documents,
            "top_n": tn,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url

        response = await arerank(**kwargs)
        if hasattr(response, "model_dump"):
            response = response.model_dump()
        elif hasattr(response, "dict"):
            response = response.dict()

        reranked_results = list(response.get("results") or [])
        for res in reranked_results:
            res["text"] = documents[int(res["index"])]
        return reranked_results

    except Exception as e:
        logger.error(f"Rerank 调用失败: {str(e)}", exc_info=True)
        return [{"index": i, "relevance_score": 0.0, "text": doc} for i, doc in enumerate(documents)]


async def rerank_to_scored_tuples(
    session: AsyncSession,
    owner_user_id: int,
    *,
    query: str,
    passages: list[str],
    top_n: int,
) -> list[tuple[float, str]] | None:
    """已配置全局 Rerank 时返回 ``(relevance_score, text)``（API 顺序）；未配置返回 ``None``，由调用方用 Milvus 分数。"""
    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)
    if not settings.rerank_vendor_id or not (settings.rerank_model or "").strip():
        return None
    rows = await rerank_llm(
        session,
        owner_user_id,
        query=query,
        documents=passages,
        top_n=top_n,
    )
    if not rows:
        return None
    out: list[tuple[float, str]] = []
    for r in rows:
        txt = r.get("text")
        if txt is None and "index" in r:
            i = int(r["index"])
            if 0 <= i < len(passages):
                txt = passages[i]
        if not txt:
            continue
        out.append((float(r.get("relevance_score", 0.0)), str(txt)))
    return out[:top_n] if out else None
