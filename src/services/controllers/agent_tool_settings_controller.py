"""用户 Agent 工具开关偏好：读 / 写 MySQL。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.UserAgentToolSettingsModel import UserAgentToolSettingsModel


async def get_saved_enabled_tools(
    session: AsyncSession,
    owner_user_id: int,
) -> list[str] | None:
    """返回已保存的启用工具列表（**默认：未保存 = 全部开启**）。

    - ``None``：无记录，或 ``enabled_tools`` 为 NULL → LangGraph 不传过滤，**全部工具可用**。
    - ``[]``：用户显式保存为空列表 → **全部禁用**。
    - 非空列表：仅这些工具启用。
    """
    stmt = select(UserAgentToolSettingsModel).where(
        UserAgentToolSettingsModel.user_id == owner_user_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or row.enabled_tools is None:
        return None
    return list(row.enabled_tools)


async def upsert_enabled_tools(
    session: AsyncSession,
    owner_user_id: int,
    enabled_tools: list[str] | None,
) -> None:
    """保存工具开关。

    - ``enabled_tools is None``：删除记录，恢复「全部可用」默认。
    - 否则写入列表（可为空列表）。
    """
    stmt = select(UserAgentToolSettingsModel).where(
        UserAgentToolSettingsModel.user_id == owner_user_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()

    if enabled_tools is None:
        if row is not None:
            await session.delete(row)
        await session.commit()
        return

    if row is None:
        row = UserAgentToolSettingsModel(user_id=owner_user_id, enabled_tools=list(enabled_tools))
        session.add(row)
    else:
        row.enabled_tools = list(enabled_tools)
    await session.commit()
