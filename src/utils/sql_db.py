import os
from typing import Annotated

from dotenv import load_dotenv
from fastapi.params import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "MYSQL_URL",
    "mysql+aiomysql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=os.getenv("MYSQL_PORT", "3306"),
        db=os.getenv("MYSQL_DATABASE", "app_db"),
    ),
)

async_engine = create_async_engine(
    DATABASE_URL,
   # 连接池保持的连接数
    pool_size=5,
    # 允许超过pool_size的最大连接数
    max_overflow=10,
    # 获取连接的超时时间(秒)
    pool_timeout=30,
    # 连接回收时间(秒)
    pool_recycle=60,  # 针对 Docker NAT 环境优化
    # 启用连接有效性检测
    pool_pre_ping=True,  # 解决 Lost connection 的核心
    # 启用SQL语句日志输出，便于开发调试
    echo=True,
    # 启用SQLAlchemy 2.0风格的未来模式API
    future=True,
)

# 创建异步会话 工厂，用于创建异步会话实例 并设置 expire_on_commit=False 禁用自动提交事务
async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_sql_session() -> AsyncSession:
    async with async_session() as session:
        yield session

AsyncSqlSessionDeps = Annotated[AsyncSession, Depends(get_sql_session)]

# 检查数据库连接是否正常
async def check_db_connection():
    """检查数据库连接是否正常"""
    try:
        async with async_engine.connect() as conn:
            print("Connecting Mysql...")
            await conn.execute(text("SELECT 1"))
            print(f"✅ 数据库连接成功: {DATABASE_URL}")
        return True
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        raise e
