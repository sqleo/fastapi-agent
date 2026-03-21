"""用户认证路由：仅 HTTP 入参/出参，业务调用 controller."""

from fastapi import APIRouter, status
from controllers.auth_controller import register_user
from schemas.auth_schema import UserPublicResponse, UserRegisterRequest
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=SuccessResponse[UserPublicResponse],
    status_code=status.HTTP_201_CREATED,
    summary="用户注册",
)
async def register(
    body: UserRegisterRequest,
    session: AsyncSqlSessionDeps,
):
    """注册新用户。"""
    user = await register_user(
        session,
        username=body.username,
        email=str(body.email),
        password=body.password,
    )
    payload = UserPublicResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        status=user.status,
    )
    return ok(payload, message="注册成功")
