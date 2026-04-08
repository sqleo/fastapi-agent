"""认证相关 Schema."""

from pydantic import BaseModel, EmailStr, Field


class UserPublicResponse(BaseModel):
    """返回给前端的用户信息（不含密码）。"""

    id: int
    username: str
    email: str
    status: int

    model_config = {"from_attributes": True}


class UserLoginRequest(BaseModel):
    """登录请求：用户名或邮箱 + 密码。"""

    account: str = Field(..., min_length=1, max_length=255, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class LoginSuccessData(BaseModel):
    """登录成功时返回的访问令牌与用户信息。"""

    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型，固定为 bearer")
    expires_in: int = Field(..., description="多少秒后过期")
    user: UserPublicResponse


class UserRegisterRequest(BaseModel):
    """用户注册请求体。"""

    username: str = Field(..., min_length=2, max_length=64, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="密码")