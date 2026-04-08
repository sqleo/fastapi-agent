from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel
from starlette.middleware.cors import CORSMiddleware

import models  # noqa: F401 — 注册 SQLModel 表元数据

from services.middlewares.require_login_middleware import RequireLoginMiddleware
from utils.logging_setup import configure_logging
from utils.response import register_exception_handlers
from utils.sql_db import async_engine


def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 须在 uvicorn 完成 logging 配置之后再挂文件 Handler，否则会写不进 logs/app.log
        configure_logging()
        # 启动阶段：创建表（开发环境；生产建议用 Alembic）
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        print("lifespan：启动阶段，数据库表已就绪")
        yield

    app = FastAPI(
        title="FastAPI Agent",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    # 挂载静态文件
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # 未登录拦截（先于 CORS 注册，使 CORS 仍包在最外层，便于浏览器读到 401 的跨域头）
    app.add_middleware(RequireLoginMiddleware)
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