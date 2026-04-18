"""异步 MySQL 连接（SQLAlchemy + aiomysql）。"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Annotated
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastapi.params import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()


def _resolve_database_url() -> str:
    """解析 ``MYSQL_URL``；未设置时由分项环境变量拼接，并对账号密码做 URL 编码。"""
    raw = os.getenv("MYSQL_URL", "").strip()
    if raw:
        if "charset=" not in raw:
            sep = "&" if "?" in raw else "?"
            raw = f"{raw}{sep}charset=utf8mb4"
        return raw

    user = quote_plus(os.getenv("MYSQL_USER", "root"))
    password = quote_plus(os.getenv("MYSQL_PASSWORD", "root"))
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "app_db")
    return (
        f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}"
        "?charset=utf8mb4"
    )


DATABASE_URL = _resolve_database_url()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_loop_id: int | None = None


def _running_loop_id() -> int | None:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return None


def _build_engine() -> AsyncEngine:
    return create_async_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=60,
        pool_pre_ping=True,
        echo=False,  # sql 日志
        future=True,
    )


def get_async_engine() -> AsyncEngine:
    """按事件循环懒加载引擎，避免跨 loop 复用连接池导致 ``different loop``。"""
    global _engine, _session_factory, _loop_id
    cur = _running_loop_id()
    if _engine is None:
        _engine = _build_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _loop_id = cur
        return _engine

    if _loop_id is not None and cur is not None and _loop_id != cur:
        _engine = _build_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _loop_id = cur
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_async_engine()
    assert _session_factory is not None
    return _session_factory


def async_session() -> AsyncSession:
    """返回与当前事件循环绑定的 ``AsyncSession``。"""
    return _get_session_factory()()


async def dispose_async_engine() -> None:
    """释放当前事件循环绑定的连接池。"""
    global _engine, _session_factory, _loop_id
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _loop_id = None


async def get_sql_session() -> AsyncGenerator[AsyncSession, None]:
    """每个请求一个 Session；任意未捕获异常时回滚，避免脏事务占用连接。"""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


AsyncSqlSessionDeps = Annotated[AsyncSession, Depends(get_sql_session)]


async def check_db_connection():
    """检查数据库连接是否正常。"""
    try:
        engine = get_async_engine()
        async with engine.connect() as conn:
            print("Connecting Mysql...")
            await conn.execute(text("SELECT 1"))
            print(f"✅ 数据库连接成功: {DATABASE_URL}")
        return True
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        raise e
