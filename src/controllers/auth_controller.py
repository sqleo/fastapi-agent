"""认证相关业务逻辑."""

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.UserModel import UserModel


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def register_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
) -> UserModel:
    """注册新用户；用户名、邮箱不可重复。

    Args:
        session: 异步数据库会话
        username: 用户名
        email: 邮箱
        password: 明文密码

    Returns:
        新建的用户 ORM 对象

    Raises:
        HTTPException: 409 冲突或数据库约束错误
    """
    username = username.strip()
    email = email.lower().strip()

    q_user = await session.execute(select(UserModel).where(UserModel.username == username))
    if q_user.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被使用",
        )

    q_email = await session.execute(select(UserModel).where(UserModel.email == email))
    if q_email.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱已被注册",
        )

    user = UserModel(
        username=username,
        email=email,
        password=_hash_password(password),
        status=1,
    )
    session.add(user)
    try:
        await session.commit()
        await session.refresh(user)
    except IntegrityError as e:
        await session.rollback()
        raw = str(getattr(e, "orig", e))
        if "Duplicate entry" in raw or "1062" in raw:
            detail = "用户名或邮箱已存在"
        else:
            detail = f"写入用户失败: {raw}"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from e

    return user
