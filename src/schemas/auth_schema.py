"""认证相关 Schema."""

from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """注册请求体."""

    username: str = Field(..., min_length=2, max_length=64, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


class UserPublicResponse(BaseModel):
    """返回给前端的用户信息（不含密码）."""

    id: int
    username: str
    email: str
    status: int

    model_config = {"from_attributes": True}
