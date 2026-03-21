"""认证相关业务逻辑."""

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.UserModel import UserModel
from schemas.auth_schema import LoginSuccessData, UserPublicResponse
from utils.jwt_tokens import create_access_token


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


async def authenticate_user(
    session: AsyncSession,
    *,
    account: str,
    password: str,
) -> UserModel | None:
    """用用户名或邮箱查找用户并校验密码；失败返回 None。"""
    account = account.strip()
    if not account:
        return None
    email_try = account.lower()
    stmt = select(UserModel).where(
        or_(UserModel.username == account, UserModel.email == email_try),
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not _verify_password(password, user.password):
        return None
    return user


async def login_user(
    session: AsyncSession,
    *,
    account: str,
    password: str,
) -> LoginSuccessData:
    """校验账号密码并签发 JWT，返回登录成功数据结构。"""
    user = await authenticate_user(session, account=account, password=password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    token, expires_in = create_access_token(
        subject=str(user.id),
        extra_claims={"username": user.username},
    )
    public = UserPublicResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        status=user.status,
    )
    return LoginSuccessData(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        user=public,
    )


async def register_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
) -> UserModel:
    """注册新用户；用户名、邮箱不可重复。

    Args:
        session: 异步数据库会话。
        username: 用户名。
        email: 邮箱。
        password: 明文密码。

    Returns:
        新建并持久化后的 ``UserModel``。

    Raises:
        HTTPException: 冲突或完整性错误时返回 409。
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
