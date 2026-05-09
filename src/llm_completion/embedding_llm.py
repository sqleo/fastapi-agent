"""按「LLM 全局设置」构造 LangChain LiteLLM 嵌入客户端（与 RAG / LangMem / 入库共用）。

嵌入向量维度从 ``llm_global_setting.embedding_dim`` 读取；未配置时回退
``env_config.embedding_dimensions``（``MILVUS_DIM`` / ``EMBEDDING_DIMENSIONS``）。
"""

from __future__ import annotations

import asyncio
import logging
import threading

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from configs.env import env_config
from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned
from shared.embedding.exceptions import EmbeddingConfigurationError

logger = logging.getLogger(__name__)


def _litellm_embedding_model_id(model: str) -> str:
    """LiteLLM 要求嵌入模型带 provider 前缀，与 ``chat_llm`` 一致。
    """
    raw = (model or "").strip()
    if not raw:
        return raw
    if "/" in raw:
        return raw
    return f"openai/{raw}"


async def embedding_llm(
    session: AsyncSession,
    owner_user_id: int,
):
    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)

    if not settings.embedding_vendor_id or not (settings.embedding_model or "").strip():
        raise ValueError(
            "未配置向量化模型：请在「LLM 全局设置」中设置默认向量化厂商与模型（embedding_vendor_id、embedding_model）"
        )
    stmt = select(LlmVendorModel).where(
        LlmVendorModel.id == settings.embedding_vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise ValueError(f"向量化厂商不存在或无权访问: vendor_id={settings.embedding_vendor_id}")
    base_url = (vendor.base_url or "").strip()
    if not base_url:
        raise ValueError(f"厂商未配置 base_url: vendor_id={vendor.id}")
    api_key = (vendor.api_key or "").strip()
    model_raw = settings.embedding_model.strip()
    litellm_model = _litellm_embedding_model_id(model_raw)
    dim = int(settings.embedding_dim or env_config.embedding_dimensions)
    # LiteLLM（openai 分支）：仅当模型名含 ``text-embedding-3`` 时才接受 ``dimensions``；
    # 否则会抛 UnsupportedParamsError（如 ``text-embedding-v4``、``ada-002`` 仍传了 dimensions）。
    # 非 3 系列不向网关传 dimensions，向量长度为模型默认输出；Milvus / LangMem 列宽须与该长度一致。
    dims_for_litellm = dim if "text-embedding-3" in litellm_model.lower() else None
    if dims_for_litellm is None and dim:
        logger.debug(
            "LiteLLMEmbeddings 不传 dimensions（model=%s）；配置维 %s 仅作业务提示，须与接口实际维一致",
            litellm_model,
            dim,
        )
    from langchain_litellm import LiteLLMEmbeddings

    # 显式 float：部分 OpenAI 兼容网关（如 DashScope text-embedding-v4）拒绝 SDK 默认的
    # encoding_format 取值，仅接受 [float, base64]，否则 400。
    return LiteLLMEmbeddings(
        model=litellm_model,
        api_key=api_key,
        api_base=base_url,
        dimensions=dims_for_litellm,
        encoding_format="float",
    )


# ──────────────────────────────────────────────────────────────────────────────
# 缓存：(user_id, embedding_version) → LiteLLMEmbeddings
#
# LangMem PostgresStore 的 embed 回调是同步的（背后跑在 asyncio.to_thread 里），
# 每次调用都开 asyncio.run 重新查 DB / 构造 LiteLLM 客户端代价极高。
# 这里按 (user_id, version) 缓存，配置变更时 controller 主动调
# ``invalidate_embeddings_cache(user_id)`` 失效。
# ──────────────────────────────────────────────────────────────────────────────

_emb_cache: dict[tuple[int, int], object] = {}
_emb_cache_lock = threading.Lock()


def _cache_get(user_id: int, version: int):
    return _emb_cache.get((int(user_id), int(version)))


def _cache_set(user_id: int, version: int, value) -> None:
    with _emb_cache_lock:
        _emb_cache[(int(user_id), int(version))] = value


def invalidate_embeddings_cache(user_id: int | None = None) -> None:
    """配置变更时清缓存：传 ``None`` 清空全部，传 ``user_id`` 仅清该用户。"""
    with _emb_cache_lock:
        if user_id is None:
            _emb_cache.clear()
            return
        for key in [k for k in _emb_cache if k[0] == int(user_id)]:
            _emb_cache.pop(key, None)


async def build_embeddings_for_user(
    session: AsyncSession,
    owner_user_id: int,
):
    """异步工厂：返回该用户当前 ``embedding_version`` 对应的 LiteLLMEmbeddings。

    - 命中缓存直接返回；
    - 否则查库构造，写入缓存（key 含 version，不会和老版本混）。
    """
    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)
    cached = _cache_get(owner_user_id, int(settings.embedding_version))
    if cached is not None:
        return cached
    emb = await embedding_llm(session, owner_user_id)
    _cache_set(owner_user_id, int(settings.embedding_version), emb)
    return emb


def sync_embedding_for_owner(owner_user_id: int):
    """同步获取 ``LiteLLMEmbeddings``，自动按 (user_id, version) 缓存。

    供向量检索、Taskiq/Ingestion、LangMem embed 回调等路径使用。
    无运行中事件循环时用 ``asyncio.run`` 临时启动一个跑 DB 查询；
    有事件循环（异步上下文）时拒绝并抛 ``EmbeddingConfigurationError``。

    ``ValueError`` 会转换为 ``EmbeddingConfigurationError``。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise EmbeddingConfigurationError(
            "同步获取嵌入失败：当前处于异步上下文，请使用 await build_embeddings_for_user(session, user_id)",
        )

    async def _run():
        from utils.sql_db import async_session

        async with async_session() as session:
            return await build_embeddings_for_user(session, owner_user_id)

    try:
        return asyncio.run(_run())
    except ValueError as e:
        raise EmbeddingConfigurationError(str(e)) from e
    except EmbeddingConfigurationError:
        raise
    except Exception as exc:
        logger.exception("sync_embedding_for_owner failed owner_user_id=%s", owner_user_id)
        raise EmbeddingConfigurationError(str(exc)) from exc
