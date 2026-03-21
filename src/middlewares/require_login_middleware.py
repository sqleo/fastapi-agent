"""未携带有效 JWT 的请求统一返回 401，提示登录。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from fastapi.encoders import jsonable_encoder
from jwt.exceptions import PyJWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.jwt_tokens import decode_access_token
from utils.response import BizCode, fail

# 无需登录的路径（精确匹配，已去掉末尾 /，根路径为 "/"）
_PUBLIC_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/",
        "/ok",
        "/openapi.json",
        "/auth/login",
        "/auth/register",
    }
)

# 前缀匹配：文档 UI、静态资源等
_PUBLIC_PREFIXES: Final[tuple[str, ...]] = (
    "/docs",
    "/redoc",
    "/static",
)


def _normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def _is_public_path(path: str) -> bool:
    n = _normalize_path(path)
    if n in _PUBLIC_PATHS:
        return True
    for p in _PUBLIC_PREFIXES:
        if n == p or n.startswith(f"{p}/"):
            return True
    return False


def _unauthorized_json(message: str) -> JSONResponse:
    body = fail(code=BizCode.UNAUTHORIZED, message=message, data=None)
    return JSONResponse(
        status_code=401,
        content=jsonable_encoder(body.model_dump()),
        headers={"WWW-Authenticate": "Bearer"},
    )


class RequireLoginMiddleware(BaseHTTPMiddleware):
    """除白名单外，要求 ``Authorization: Bearer <token>`` 且 JWT 校验通过。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return _unauthorized_json("请先登录")
        token = auth.removeprefix("Bearer ").strip()
        if not token:
            return _unauthorized_json("请先登录")
        try:
            decode_access_token(token)
        except PyJWTError:
            return _unauthorized_json("登录已过期或令牌无效，请重新登录")

        return await call_next(request)
