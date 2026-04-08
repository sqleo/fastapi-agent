from __future__ import annotations

import logging

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned

logger = logging.getLogger(__name__)

_DEEPSEEK_REASONING_MODELS = frozenset({
    "deepseek-reasoner",
    "deepseek-r1",
})


def _is_deepseek_reasoner(model_name: str, vendor_code: str) -> bool:
    return model_name.lower() in _DEEPSEEK_REASONING_MODELS or (
        vendor_code == "deepseek" and "reason" in model_name.lower()
    )


async def create_llm(
    session: AsyncSession,
    owner_user_id: int,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1000,
) -> BaseChatModel:
    """根据「LLM 全局设置」创建聊天模型。

    DeepSeek 推理模型（deepseek-reasoner 等）使用 ``ChatDeepSeek``
    以支持流式 ``reasoning_content``；其余走 ``init_chat_model`` + OpenAI 兼容。
    """
    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)
    if not settings.chat_vendor_id or not (settings.chat_model or "").strip():
        raise ValueError(
            "未配置聊天模型：请在「LLM 全局设置」中设置默认聊天厂商与模型（chat_vendor_id、chat_model）"
        )
    stmt = select(LlmVendorModel).where(
        LlmVendorModel.id == settings.chat_vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise ValueError(f"聊天厂商不存在或无权访问: vendor_id={settings.chat_vendor_id}")
    base_url = (vendor.base_url or "").strip()
    if not base_url:
        raise ValueError(f"厂商未配置 base_url: vendor_id={vendor.id}")
    api_key = (vendor.api_key or "").strip()
    model = settings.chat_model.strip()
    extra = vendor.extra_config if isinstance(vendor.extra_config, dict) else {}
    temp = float(extra["temperature"]) if extra.get("temperature") is not None else temperature
    mxt = int(extra["max_tokens"]) if extra.get("max_tokens") is not None else max_tokens
    vendor_code = (vendor.code or "").strip().lower()

    if _is_deepseek_reasoner(model, vendor_code):
        logger.info("create_llm: using ChatDeepSeek for model=%s", model)
        return ChatDeepSeek(
            model=model,
            api_key=api_key if api_key else None,
            api_base=base_url,
            max_tokens=mxt,
        )

    return init_chat_model(
        model,
        model_provider="openai",
        base_url=base_url,
        api_key=api_key if api_key else None,
        temperature=temp,
        max_tokens=mxt,
    )
