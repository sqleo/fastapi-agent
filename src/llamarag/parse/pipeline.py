"""LlamaRAG 解析管道：路由入口与可替换实现.

分层（自底向上）：

- ``llamarag.parsing.registry.get_intermediate_md_generator_for_ext``：按 ``file_ext`` 选
  ``IntermediateMdGenerator``（md/pdf 等），只负责「源路径 → 目标 md 路径」。
- ``process_file_to_md``：查库、校验归属、调 ``generator.generate``、更新
  ``FileAssetModel`` 与 ``KnowledgeBaseFileModel``。
- 本模块 ``parse_file_to_parsed_md``：供 ``POST /v1/llamarag/files/{file_id}/parse-md`` 调用；
  ``get_parse_pipeline`` 返回上述完整管道，便于测试或以后换实现。

仅服务于 ``/v1/llamarag/...``；勿以 ``/v1/files/.../parse-md`` 为设计锚点。
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from models.FileManagementModel import FileAssetModel


class ParsePipeline(Protocol):
    """可调用异步解析管道（函数或带 ``__call__`` 的实例）。"""

    def __call__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: int,
        file_id: int,
    ) -> Coroutine[Any, Any, FileAssetModel]:
        """执行解析并返回更新后的 ``FileAssetModel``。"""
        ...


def get_parse_pipeline() -> ParsePipeline:
    """返回当前默认管道（默认即 ``process_file_to_md``）。

    后续可根据策略换实现，只要符合 ``ParsePipeline`` 即可。
    """
    from llamarag.parse.process_file_to_md import process_file_to_md

    return process_file_to_md


async def parse_file_to_parsed_md(
    session: AsyncSession,
    *,
    owner_user_id: int,
    file_id: int,
) -> FileAssetModel:
    """解析入口：经 ``get_parse_pipeline`` 执行完整流程."""
    pipeline = get_parse_pipeline()
    return await pipeline(session, owner_user_id=owner_user_id, file_id=file_id)
