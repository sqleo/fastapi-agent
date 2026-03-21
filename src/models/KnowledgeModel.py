from typing import Any, ClassVar, Optional

from sqlalchemy import Index
from sqlmodel import Field

from models.BasicModel import BasicModel


class KnowledgeModel(BasicModel, table=True):
    """资料库：私有，仅 owner_user_id 对应用户可访问。"""

    __tablename__ = "knowledge_base"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        Index("ix_knowledge_base_owner_status", "owner_user_id", "status"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        index=True,
        description="所属用户，与 JWT 用户 id 一致",
    )
    name: str = Field(max_length=255, description="资料库名称", index=True)
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="描述",
    )
    thumbnail_key: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="缩略图：对象存储键或站内相对路径（如 static/...），空表示无缩略图",
    )
    status: int = Field(default=1, description="1 正常，0 禁用", index=True)
