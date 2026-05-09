import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned

logger = logging.getLogger(__name__)

async def chat_llm(
    session: AsyncSession,
    owner_user_id: int,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    temperature_override: float | None = None,
):
     
    settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)
    print("chat_llm settings:",settings)  # 调试输出全局设置
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
    if temperature_override is not None:
        temp = float(temperature_override)
    elif extra.get("temperature") is not None:
        temp = float(extra["temperature"])
    else:
        temp = temperature
    mxt = int(extra["max_tokens"]) if extra.get("max_tokens") is not None else max_tokens

    from langchain_litellm import ChatLiteLLM

    # litellm 要求模型名带 provider 前缀（如 openai/deepseek-chat）；
    litellm_model = model if "/" in model else f"openai/{model}"
    return ChatLiteLLM(
        model=litellm_model,
        temperature=temp,
        max_tokens=mxt,
        api_key=api_key,
        api_base=base_url,
        streaming=True # 支持流式输出  
    )