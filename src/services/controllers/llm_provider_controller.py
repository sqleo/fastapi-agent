"""LLM 厂商业务逻辑。"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmVendorModel
from services.controllers.llm_vendor_seed import (
    get_vendor_template,
    validate_vendor_patch_by_template,
)


async def get_vendor_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    vendor_id: int,
) -> LlmVendorModel:
    """获取当前用户已安装厂商，不存在则抛 404。"""
    stmt = select(LlmVendorModel).where(
        LlmVendorModel.id == vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="厂商不存在")
    return row


async def update_vendor_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    vendor_id: int,
    patch: dict,
) -> LlmVendorModel:
    """更新当前用户已安装厂商。"""
    row = await get_vendor_owned(session, owner_user_id=owner_user_id, vendor_id=vendor_id)

    merged = {
        "api_key": row.api_key,
        "api_secret": row.api_secret,
        "base_url": row.base_url,
        "organization": row.organization,
        "extra_config": dict(row.extra_config or {}),
    }
    if "extra_config" in patch and isinstance(patch["extra_config"], dict):
        merged["extra_config"].update(patch["extra_config"])
    for k, v in patch.items():
        if k == "extra_config":
            continue
        merged[k] = v

    template = get_vendor_template(row.code)
    if template is not None:
        validate_vendor_patch_by_template(template, merged)

    for key, value in patch.items():
        if key == "extra_config":
            current = dict(row.extra_config or {})
            current.update(value or {})
            row.extra_config = current
        else:
            setattr(row, key, value)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
