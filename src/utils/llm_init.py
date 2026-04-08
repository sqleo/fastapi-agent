from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned


async def create_llm(
    session: AsyncSession,
    owner_user_id: int,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1000,
) -> BaseChatModel:
    """根据「LLM 全局设置」`/llm/settings/global` 中的聊天厂商与模型创建聊天模型（OpenAI 兼容）。"""
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
    return init_chat_model(
        model,
        model_provider="openai",
        base_url=base_url,
        api_key=api_key if api_key else None,
        temperature=temp,
        max_tokens=mxt,
    )
