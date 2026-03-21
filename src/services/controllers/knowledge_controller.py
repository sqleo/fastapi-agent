"""资料库相关业务逻辑."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.KnowledgeModel import KnowledgeModel


async def get_knowledge_base_owned(
    session: AsyncSession,
    *,
    kb_id: int,
    owner_user_id: int,
) -> KnowledgeModel | None:
    """按 id + 归属用户查询一条资料库（不区分 status）。"""
    stmt = select(KnowledgeModel).where(
        KnowledgeModel.id == kb_id,
        KnowledgeModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_knowledge_bases_by_owner(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> list[KnowledgeModel]:
    """按归属用户列出知识库（不包含禁用项），按更新时间倒序。"""
    stmt = (
        select(KnowledgeModel)
        .where(KnowledgeModel.owner_user_id == owner_user_id, KnowledgeModel.status == 1)
        .order_by(KnowledgeModel.updated_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_knowledge_base(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    description: str | None = None,
    thumbnail_key: str | None = None,
    audit_label: str | None = None,
) -> KnowledgeModel:
    """为当前用户新建一条资料库记录并提交。"""
    kb = KnowledgeModel(
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        thumbnail_key=thumbnail_key,
        status=1,
        create_by=audit_label,
        update_by=audit_label,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb
