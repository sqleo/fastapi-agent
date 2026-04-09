"""用户级 Agent 工具开关偏好（与聊天 configurable.enabled_tools 对齐）。"""

from __future__ import annotations

from sqlalchemy import Column, JSON
from sqlmodel import Field

from models.BasicModel import BasicModel


class UserAgentToolSettingsModel(BasicModel, table=True):
    """每个用户一条：显式启用的工具名列表（**默认未建记录 = 全部工具开启**）。

    - 无记录：与未配置相同，Agent 使用全部注册工具。
    - ``enabled_tools=[]``：全部禁用。
    - ``enabled_tools=["name", ...]``：仅列出的工具可用。
    """

    __tablename__ = "user_agent_tool_settings"

    user_id: int = Field(
        foreign_key="user.id",
        unique=True,
        index=True,
        description="用户 id",
    )

    enabled_tools: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="允许使用的工具 name 列表；空列表表示全部禁用",
    )
