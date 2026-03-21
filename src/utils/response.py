"""统一 API 成功 / 失败响应结构."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

T = TypeVar("T")


class BizCode:
    """业务错误码（非 0）；成功固定为 0."""

    SUCCESS = 0
    VALIDATION_ERROR = 42201
    BAD_REQUEST = 40001
    UNAUTHORIZED = 40101
    FORBIDDEN = 40301
    NOT_FOUND = 40401
    CONFLICT = 40901
    UNPROCESSABLE = 42202
    INTERNAL_ERROR = 50001


class SuccessResponse(BaseModel, Generic[T]):
    """统一成功响应."""

    code: int = Field(default=BizCode.SUCCESS, description="0 表示成功")
    message: str = Field(default="success", description="说明文案")
    data: T | None = Field(default=None, description="业务数据")


class FailResponse(BaseModel):
    """统一失败响应."""

    code: int = Field(..., description="非 0 业务错误码")
    message: str = Field(..., description="错误说明")
    data: Any = Field(default=None, description="附加信息，如字段校验明细")


def ok(data: T | None = None, *, message: str = "success") -> SuccessResponse[T]:
    """构造成功响应。"""
    return SuccessResponse(code=BizCode.SUCCESS, message=message, data=data)


def fail(
    *,
    code: int,
    message: str,
    data: Any = None,
) -> FailResponse:
    """构造失败响应体（一般配合 JSONResponse 使用）。"""
    return FailResponse(code=code, message=message, data=data)


def _http_status_to_biz_code(status_code: int) -> int:
    mapping = {
        status.HTTP_400_BAD_REQUEST: BizCode.BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED: BizCode.UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: BizCode.FORBIDDEN,
        status.HTTP_404_NOT_FOUND: BizCode.NOT_FOUND,
        status.HTTP_409_CONFLICT: BizCode.CONFLICT,
        status.HTTP_422_UNPROCESSABLE_ENTITY: BizCode.UNPROCESSABLE,
        status.HTTP_500_INTERNAL_SERVER_ERROR: BizCode.INTERNAL_ERROR,
    }
    return mapping.get(status_code, status_code * 100 if status_code < 1000 else status_code)


def _detail_to_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return str(detail)
    except Exception:
        return "请求处理失败"


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理，将 HTTP 异常与参数校验错误转为 ``FailResponse`` JSON."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = fail(
            code=_http_status_to_biz_code(exc.status_code),
            message=_detail_to_message(exc.detail),
            data=None,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(body.model_dump()),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        body = fail(
            code=BizCode.VALIDATION_ERROR,
            message="请求参数校验失败",
            data=jsonable_encoder(exc.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(body.model_dump()),
        )
