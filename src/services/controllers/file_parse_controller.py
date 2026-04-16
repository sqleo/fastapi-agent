"""将已上传文件解析为 ``static/parsed_md/`` 中间 Markdown.

实现已迁至 ``llamarag.parse.process_file_to_md``；本模块保留与历史路由相同的入口名。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from llamarag.parse.process_file_to_md import process_file_to_md
from models.FileManagementModel import FileAssetModel


async def parse_file_to_intermediate_md_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    file_id: int,
) -> FileAssetModel:
    """校验归属后生成中间 Markdown，并更新 ``parsed_md_storage_key``；关联知识库条目置为可入队。"""
    return await process_file_to_md(
        session,
        owner_user_id=owner_user_id,
        file_id=file_id,
    )
