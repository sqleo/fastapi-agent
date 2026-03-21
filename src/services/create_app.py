import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel
from starlette.middleware.cors import CORSMiddleware

from utils.response import register_exception_handlers
from utils.sql_db import async_engine


def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动阶段：创建表（开发环境；生产建议用 Alembic）
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        print("lifespan：启动阶段，数据库表已就绪")
        yield
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app = FastAPI(
        title="FastAPI Agent",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    # 挂载静态文件
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    return app

# @app.get("/")
# async def redirect_root_to_docs() -> RedirectResponse:
#     return RedirectResponse("/docs")