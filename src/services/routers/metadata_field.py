"""metadata 抽取配置路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from schemas.metadata_field_schema import (
    MetadataFieldAliasCreateRequest,
    MetadataFieldAliasItem,
    MetadataFieldAliasUpdateRequest,
    MetadataFieldCreateRequest,
    MetadataFieldItem,
    MetadataFieldListResponse,
    MetadataFieldUpdateRequest,
)
from services.controllers.metadata_field_controller import (
    create_field_alias_owned,
    create_metadata_field_owned,
    delete_field_alias_owned,
    delete_metadata_field_owned,
    list_aliases_by_field_ids_owned,
    list_field_aliases_owned,
    list_metadata_fields_owned,
    update_field_alias_owned,
    update_metadata_field_owned,
)
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/metadata-fields", tags=["Metadata Config"])


def _to_alias_item(x) -> MetadataFieldAliasItem:
    return MetadataFieldAliasItem(
        id=x.id,
        field_id=x.field_id,
        alias_text=x.alias_text,
        match_mode=x.match_mode.value if hasattr(x.match_mode, "value") else str(x.match_mode),
        status=x.status,
        priority=x.priority,
        created_at=x.created_at,
        updated_at=x.updated_at,
    )


def _to_field_item(x, aliases: list) -> MetadataFieldItem:
    return MetadataFieldItem(
        id=x.id,
        owner_user_id=x.owner_user_id,
        biz_code=x.biz_code,
        knowledge_base_id=x.knowledge_base_id,
        field_key=x.field_key,
        field_name=x.field_name,
        value_type=x.value_type.value if hasattr(x.value_type, "value") else str(x.value_type),
        extract_mode=x.extract_mode.value if hasattr(x.extract_mode, "value") else str(x.extract_mode),
        status=x.status,
        priority=x.priority,
        created_at=x.created_at,
        updated_at=x.updated_at,
        aliases=[_to_alias_item(a) for a in aliases],
    )


@router.get(
    "",
    response_model=SuccessResponse[MetadataFieldListResponse],
    summary="metadata 字段配置列表",
)
async def list_metadata_fields(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    biz_code: str | None = Query(default=None, description="业务线编码；不传表示查询全局级"),
    knowledge_base_id: int | None = Query(default=None, description="知识库 id；不传表示查询非知识库级"),
    status_filter: int | None = Query(default=None, alias="status", description="状态过滤：1启用，0禁用"),
) -> SuccessResponse[MetadataFieldListResponse]:
    rows = await list_metadata_fields_owned(
        session,
        owner_user_id=current_user.id,
        biz_code=biz_code,
        knowledge_base_id=knowledge_base_id,
        status_filter=status_filter,
    )
    alias_map = await list_aliases_by_field_ids_owned(session, field_ids=[int(x.id) for x in rows])
    payload = MetadataFieldListResponse(
        total=len(rows),
        items=[_to_field_item(x, alias_map.get(int(x.id), [])) for x in rows],
    )
    return ok(payload, message="查询成功")


@router.post(
    "",
    response_model=SuccessResponse[MetadataFieldItem],
    status_code=status.HTTP_201_CREATED,
    summary="新建 metadata 字段配置",
)
async def create_metadata_field(
    body: MetadataFieldCreateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[MetadataFieldItem]:
    row = await create_metadata_field_owned(
        session,
        owner_user_id=current_user.id,
        operator_name=current_user.username,
        biz_code=body.biz_code,
        knowledge_base_id=body.knowledge_base_id,
        field_key=body.field_key,
        field_name=body.field_name,
        value_type=body.value_type,
        extract_mode=body.extract_mode,
        status_value=body.status,
        priority=body.priority,
        aliases=[x.model_dump() for x in body.aliases],
    )
    aliases = await list_field_aliases_owned(session, owner_user_id=current_user.id, field_id=int(row.id))
    return ok(_to_field_item(row, aliases), message="创建成功")


@router.patch(
    "/{field_id}",
    response_model=SuccessResponse[MetadataFieldItem],
    summary="更新 metadata 字段配置",
)
async def patch_metadata_field(
    field_id: int,
    body: MetadataFieldUpdateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[MetadataFieldItem]:
    row = await update_metadata_field_owned(
        session,
        owner_user_id=current_user.id,
        operator_name=current_user.username,
        field_id=field_id,
        patch=body.model_dump(exclude_unset=True),
    )
    aliases = await list_field_aliases_owned(session, owner_user_id=current_user.id, field_id=int(row.id))
    return ok(_to_field_item(row, aliases), message="更新成功")


@router.delete(
    "/{field_id}",
    response_model=SuccessResponse[dict[str, int]],
    summary="删除 metadata 字段配置",
)
async def delete_metadata_field(
    field_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[dict[str, int]]:
    await delete_metadata_field_owned(
        session,
        owner_user_id=current_user.id,
        field_id=field_id,
    )
    return ok({"field_id": field_id}, message="删除成功")


@router.get(
    "/{field_id}/aliases",
    response_model=SuccessResponse[list[MetadataFieldAliasItem]],
    summary="字段别名列表",
)
async def list_metadata_field_aliases(
    field_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[list[MetadataFieldAliasItem]]:
    rows = await list_field_aliases_owned(
        session,
        owner_user_id=current_user.id,
        field_id=field_id,
    )
    return ok([_to_alias_item(x) for x in rows], message="查询成功")


@router.post(
    "/{field_id}/aliases",
    response_model=SuccessResponse[MetadataFieldAliasItem],
    status_code=status.HTTP_201_CREATED,
    summary="新增字段别名",
)
async def create_metadata_field_alias(
    field_id: int,
    body: MetadataFieldAliasCreateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[MetadataFieldAliasItem]:
    row = await create_field_alias_owned(
        session,
        owner_user_id=current_user.id,
        operator_name=current_user.username,
        field_id=field_id,
        alias_text=body.alias_text,
        match_mode=body.match_mode,
        status_value=body.status,
        priority=body.priority,
    )
    return ok(_to_alias_item(row), message="创建成功")


@router.patch(
    "/aliases/{alias_id}",
    response_model=SuccessResponse[MetadataFieldAliasItem],
    summary="更新字段别名",
)
async def patch_metadata_field_alias(
    alias_id: int,
    body: MetadataFieldAliasUpdateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[MetadataFieldAliasItem]:
    row = await update_field_alias_owned(
        session,
        owner_user_id=current_user.id,
        operator_name=current_user.username,
        alias_id=alias_id,
        patch=body.model_dump(exclude_unset=True),
    )
    return ok(_to_alias_item(row), message="更新成功")


@router.delete(
    "/aliases/{alias_id}",
    response_model=SuccessResponse[dict[str, int]],
    summary="删除字段别名",
)
async def delete_metadata_field_alias(
    alias_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[dict[str, int]]:
    await delete_field_alias_owned(
        session,
        owner_user_id=current_user.id,
        alias_id=alias_id,
    )
    return ok({"alias_id": alias_id}, message="删除成功")
