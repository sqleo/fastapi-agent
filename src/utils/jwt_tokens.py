"""JWT 访问令牌的签发与校验。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import PyJWTError

from configs.env import env_config


def _require_jwt_secret() -> str:
    key = (env_config.jwt_secret_key or "").strip()
    if not key:
        msg = "JWT_SECRET_KEY 未设置：请在项目根 .env 中配置（见 configs/env.py / env_config）"
        raise ValueError(msg)
    return key


def create_access_token(
    *,
    subject: str,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """生成已签名的 access token。

    Returns:
        ``(token 字符串, expires_in 秒数)``。
    """
    secret = _require_jwt_secret()
    c = env_config
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=c.jwt_access_token_expire_minutes)
    expires_in = int((expire - now).total_seconds())

    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    if c.jwt_issuer:
        payload["iss"] = c.jwt_issuer
    if c.jwt_audience:
        payload["aud"] = c.jwt_audience
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        secret,
        algorithm=c.jwt_algorithm,
    )
    # PyJWT>=2 返回 str；旧版可能返回 bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并校验 access token；失败时抛出 ``PyJWTError``。"""
    secret = _require_jwt_secret()
    c = env_config
    options = {
        "require": ["exp", "iat", "sub"],
        "verify_signature": True,
        "verify_exp": True,
    }
    kwargs: dict[str, Any] = {
        "algorithms": [c.jwt_algorithm],
        "options": options,
        "leeway": c.jwt_leeway_seconds,
    }
    if c.jwt_audience:
        kwargs["audience"] = c.jwt_audience
    if c.jwt_issuer:
        kwargs["issuer"] = c.jwt_issuer

    return jwt.decode(token, secret, **kwargs)


__all__ = [
    "PyJWTError",
    "create_access_token",
    "decode_access_token",
]
