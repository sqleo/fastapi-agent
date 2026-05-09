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

import weakref
from sqlalchemy.pool import NullPool

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

_engine_map: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

def _get_engine_and_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        if loop in _engine_map:
            return _engine_map[loop]
        
        # 第一次请求的通常是 Uvicorn 主事件循环，给它带连接池的 Engine；
        # 后续通过 asyncio.run 创建的临时事件循环使用 NullPool，防止连接在循环结束后被遗弃导致报错
        is_main_loop = len(_engine_map) == 0
        if is_main_loop:
            engine = _build_engine()
        else:
            engine = create_async_engine(
                DATABASE_URL,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
                future=True,
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _engine_map[loop] = (engine, factory)
        return engine, factory
    else:
        # 非异步上下文的 fallback
        engine = _build_engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        return engine, factory

def get_async_engine() -> AsyncEngine:
    """按事件循环懒加载引擎，避免跨 loop 复用连接池导致不同 loop 报错。"""
    return _get_engine_and_factory()[0]


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return _get_engine_and_factory()[1]


def async_session() -> AsyncSession:
    """返回与当前事件循环绑定的 ``AsyncSession``。"""
    return _get_session_factory()()


async def dispose_async_engine() -> None:
    """释放当前事件循环绑定的连接池。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop in _engine_map:
        engine, factory = _engine_map[loop]
        await engine.dispose()
        del _engine_map[loop]


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
