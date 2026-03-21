"""用户认证路由：仅 HTTP 入参/出参，业务调用 controller."""

from fastapi import APIRouter, status

from controllers.auth_controller import login_user, register_user
from schemas.auth_schema import (
    LoginSuccessData,
    UserLoginRequest,
    UserPublicResponse,
    UserRegisterRequest,
)
from utils.auth_deps import CurrentUserDeps
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


@router.post(
    "/login",
    response_model=SuccessResponse[LoginSuccessData],
    summary="用户登录（JWT）",
)
async def login(
    body: UserLoginRequest,
    session: AsyncSqlSessionDeps,
):
    """使用用户名或邮箱登录，返回 Bearer 格式的 access_token。"""
    data = await login_user(
        session,
        account=body.account,
        password=body.password,
    )
    return ok(data, message="登录成功")


@router.get(
    "/me",
    response_model=SuccessResponse[UserPublicResponse],
    summary="当前登录用户",
)
async def me(current_user: CurrentUserDeps):
    """获取当前登录用户；请求头需携带 ``Authorization: Bearer <token>``。"""
    payload = UserPublicResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        status=current_user.status,
    )
    return ok(payload, message="查询成功")
