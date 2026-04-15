"""嵌入配置解析：抽象主接口、数据库主路径、降级策略抽象子类."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_global_setting_controller import get_global_setting_owned
from shared.embedding.config import FIXED_EMBEDDING_DIMENSION, EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError


class EmbeddingSettingsProvider(ABC):
    """嵌入配置来源（LlamaIndex RAG、LangMem 等共用同一抽象）。"""

    @abstractmethod
    async def resolve(self, session: AsyncSession, owner_user_id: int) -> EmbeddingConfig:
        """解析 ``owner_user_id`` 下的嵌入网关与模型；失败时抛出 ``EmbeddingConfigurationError``。"""


class DatabaseEmbeddingSettingsProvider(EmbeddingSettingsProvider):
    """嵌入配置解析：从数据库中获取嵌入厂商和模型。返回EmbeddingConfig对象。"""

    async def resolve(self, session: AsyncSession, owner_user_id: int) -> EmbeddingConfig:
        settings = await get_global_setting_owned(session, owner_user_id=owner_user_id)
        vid = settings.embedding_vendor_id
        model = (settings.embedding_model or "").strip()
        if vid is None or not model:
            raise EmbeddingConfigurationError(
                "未配置嵌入模型：请在全局设置中填写 embedding_vendor_id 与 embedding_model",
            )
        # 查询嵌入厂商
        vstmt = select(LlmVendorModel).where(
            LlmVendorModel.id == int(vid),
            LlmVendorModel.owner_user_id == owner_user_id,
        )
        vres = await session.execute(vstmt)
        vendor = vres.scalar_one_or_none()
        if vendor is None:
            raise EmbeddingConfigurationError(f"嵌入厂商不存在或无权限: vendor_id={vid}")

        base_url = (vendor.base_url or "").strip()
        api_key = (vendor.api_key or "").strip()
        if not base_url or not api_key:
            raise EmbeddingConfigurationError(
                "嵌入厂商缺少 base_url 或 api_key，请补全 llm_vendor 记录",
            )

        return EmbeddingConfig(
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            dimensions=FIXED_EMBEDDING_DIMENSION,
        )


class EmbeddingFallbackProvider(EmbeddingSettingsProvider):
    """降级策略基类：例如环境变量默认模型、平台内置网关等。

    子类实现 ``resolve``；当前仓库不提供默认降级实现，仅占位扩展。
    """
