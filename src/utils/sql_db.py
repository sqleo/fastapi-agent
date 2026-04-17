"""异步 MySQL 连接（SQLAlchemy + aiomysql）。"""

import os
from collections.abc import AsyncGenerator
from typing import Annotated
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastapi.params import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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

async_engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=60,
    pool_pre_ping=True,
    echo=False, # sql 日志
    future=True,
)

async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


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
        async with async_engine.connect() as conn:
            print("Connecting Mysql...")
            await conn.execute(text("SELECT 1"))
            print(f"✅ 数据库连接成功: {DATABASE_URL}")
        return True
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        raise e
