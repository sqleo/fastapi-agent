"""LlamaRAG：解析到中间 Markdown（parsed_md）等接口.

解析逻辑以本模块 ``POST .../llamarag/files/{file_id}/parse-md`` 为准；
扩展或修改解析流程时只维护 ``llamarag.parse`` / ``llamarag.parsing``，不必考虑
``POST /v1/files/{file_id}/parse-md``（文件管理侧另有入口）。
"""

from __future__ import annotations

from fastapi import APIRouter

from llamarag.parse.pipeline import parse_file_to_parsed_md
from schemas.file_management_schema import FileParseIntermediateMdResponse
from utils.auth_deps import CurrentUserDeps
from utils.content_semver import format_semver
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/llamarag", tags=["LlamaRAG"])


def _to_parse_response(row) -> FileParseIntermediateMdResponse:
    key = (row.parsed_md_storage_key or "").strip()
    url = f"/static/{key}" if key else ""
    return FileParseIntermediateMdResponse(
        file_id=int(row.id),
        content_semver=format_semver(row.semver_major, row.semver_minor, row.semver_patch),
        parse_status=row.parse_status.value if hasattr(row.parse_status, "value") else str(row.parse_status),
        parsed_md_storage_key=key,
        parsed_md_url=url,
    )


@router.post(
    "/files/{file_id}/parse-md",
    response_model=SuccessResponse[FileParseIntermediateMdResponse],
    summary="解析为中间 Markdown（parsed_md）",
)
async def parse_file_to_parsed_md_route(
    file_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[FileParseIntermediateMdResponse]:
    """将当前用户已上传文件解析到 ``static/parsed_md/{owner}/{file_id}.md``。

    后缀支持由 ``llamarag.parsing.registry`` 决定。
    """
    row = await parse_file_to_parsed_md(
        session,
        owner_user_id=current_user.id,
        file_id=file_id,
    )
    return ok(_to_parse_response(row), message="解析成功")
