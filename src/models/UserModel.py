from sqlmodel import Field

from models.BasicModel import BasicModel


class UserModel(BasicModel, table=True):
    """用户表 ORM 模型."""

    __tablename__ = "user"

    username: str = Field(max_length=64, unique=True, description="用户名", index=True)
    email: str = Field(max_length=255, description="邮箱", index=True)
    password: str = Field(max_length=255, description="密码哈希")
    status: int = Field(default=1, description="状态：1 正常，0 禁用")
