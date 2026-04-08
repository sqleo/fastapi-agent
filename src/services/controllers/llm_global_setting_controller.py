"""用户全局模型设置业务逻辑。"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmGlobalSettingModel import LlmGlobalSettingModel
from models.LlmVendorModel import LlmVendorModel


async def _assert_vendor_owned(session: AsyncSession, *, owner_user_id: int, vendor_id: int) -> None:
    stmt = select(LlmVendorModel.id).where(
        LlmVendorModel.id == vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"厂商不存在: {vendor_id}")


async def _get_or_create(session: AsyncSession, *, owner_user_id: int) -> LlmGlobalSettingModel:
    stmt = select(LlmGlobalSettingModel).where(LlmGlobalSettingModel.owner_user_id == owner_user_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = LlmGlobalSettingModel(owner_user_id=owner_user_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_global_setting_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> LlmGlobalSettingModel:
    """获取用户全局设置；若不存在则自动创建空设置。"""
    return await _get_or_create(session, owner_user_id=owner_user_id)


async def update_global_setting_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    patch: dict,
) -> LlmGlobalSettingModel:
    """更新用户全局设置，并校验引用厂商归属。"""
    for field_name in (
        "chat_vendor_id",
        "embedding_vendor_id",
        "multimodal_vendor_id",
        "rerank_vendor_id",
        "asr_vendor_id",
        "tts_vendor_id",
    ):
        vid = patch.get(field_name)
        if vid is not None:
            await _assert_vendor_owned(session, owner_user_id=owner_user_id, vendor_id=int(vid))

    row = await _get_or_create(session, owner_user_id=owner_user_id)
    for key, value in patch.items():
        setattr(row, key, value)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row

