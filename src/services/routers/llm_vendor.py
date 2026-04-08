"""LLM 厂商：市场列表、安装、我的厂商。"""

from fastapi import APIRouter, HTTPException, status

from schemas.llm_vendor_schema import (
    InstalledVendorItem,
    VendorMarketplaceItem,
    VendorUpdateRequest,
)
from services.controllers.llm_provider_controller import update_vendor_owned
from services.controllers.llm_vendor_seed import (
    get_vendor_template,
    install_vendor_for_user,
    list_installed_vendors_for_user,
    list_vendor_marketplace,
)
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/llm/vendors", tags=["LLM Vendors"])


@router.get(
    "/marketplace",
    response_model=SuccessResponse[list[VendorMarketplaceItem]],
    summary="厂商市场列表",
)
async def marketplace() -> SuccessResponse[list[VendorMarketplaceItem]]:
    """展示平台支持的厂商（未安装前展示）。"""
    rows = [VendorMarketplaceItem.model_validate(x) for x in list_vendor_marketplace()]
    return ok(rows, message="查询成功")


@router.get(
    "/installed",
    response_model=SuccessResponse[list[InstalledVendorItem]],
    summary="我的已安装厂商",
)
async def installed(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[list[InstalledVendorItem]]:
    """展示当前用户已安装的厂商。"""
    rows = await list_installed_vendors_for_user(session, owner_user_id=current_user.id)
    payload = [
        InstalledVendorItem(
            id=x.id,
            code=x.code,
            name=x.name,
            description=x.description,
            website_url=x.website_url,
            doc_url=x.doc_url,
            logo_url=x.logo_url,
            base_url=x.base_url,
            default_model_type=x.default_model_type,
            capabilities=(get_vendor_template(x.code) or {}).get("capabilities", []),
            config_schema=(get_vendor_template(x.code) or {}).get("config_schema"),
            extra_config=x.extra_config or {},
            status=x.status,
        )
        for x in rows
    ]
    return ok(payload, message="查询成功")


@router.post(
    "/install/{vendor_code}",
    response_model=SuccessResponse[InstalledVendorItem],
    status_code=status.HTTP_201_CREATED,
    summary="安装厂商到我的列表",
)
async def install_vendor(
    vendor_code: str,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[InstalledVendorItem]:
    """安装指定厂商；已安装则直接返回该厂商记录。"""
    try:
        row = await install_vendor_for_user(
            session,
            owner_user_id=current_user.id,
            vendor_code=vendor_code,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    data = InstalledVendorItem(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        website_url=row.website_url,
        doc_url=row.doc_url,
        logo_url=row.logo_url,
        base_url=row.base_url,
        default_model_type=row.default_model_type,
        capabilities=(get_vendor_template(row.code) or {}).get("capabilities", []),
        config_schema=(get_vendor_template(row.code) or {}).get("config_schema"),
        extra_config=row.extra_config or {},
        status=row.status,
    )
    return ok(data, message="安装成功")


@router.patch(
    "/{vendor_id}",
    response_model=SuccessResponse[InstalledVendorItem],
    summary="更新已安装厂商配置",
)
async def patch_vendor(
    vendor_id: int,
    body: VendorUpdateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[InstalledVendorItem]:
    """更新当前用户某个已安装厂商的厂商级配置（API Key/base_url 等）。"""
    try:
        row = await update_vendor_owned(
            session,
            owner_user_id=current_user.id,
            vendor_id=vendor_id,
            patch=body.model_dump(exclude_none=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    data = InstalledVendorItem(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        website_url=row.website_url,
        doc_url=row.doc_url,
        logo_url=row.logo_url,
        base_url=row.base_url,
        default_model_type=row.default_model_type,
        capabilities=(get_vendor_template(row.code) or {}).get("capabilities", []),
        config_schema=(get_vendor_template(row.code) or {}).get("config_schema"),
        extra_config=row.extra_config or {},
        status=row.status,
    )
    return ok(data, message="更新成功")

