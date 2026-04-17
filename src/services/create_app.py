from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel
from starlette.middleware.cors import CORSMiddleware


from services.middlewares.require_login_middleware import RequireLoginMiddleware
from utils.logging_setup import configure_logging
from utils.response import register_exception_handlers
from utils.sql_db import async_engine, check_db_connection
from monitor.pg import init_monitor_pool, close_monitor_pool

logger = logging.getLogger("services.request")


def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()

        # ---- 启动：检测数据库连接 ----
        await check_db_connection()

        # 创建业务表（开发环境；生产建议用 Alembic）
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("MySQL 业务表已就绪")

        # 初始化 LLM 监控库（PostgreSQL，会自动建 schema + 表）
        try:
            await init_monitor_pool()
            logger.info("PostgreSQL 监控表已就绪")
        except Exception:
            logger.warning("LLM 监控库初始化失败，监控功能不可用", exc_info=True)

        yield

        # ---- 关闭：释放连接池 ----
        await close_monitor_pool()
        await async_engine.dispose()
        logger.info("数据库连接已关闭")

    app = FastAPI(
        title="FastAPI Agent",
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        """每个请求都写一条增量访问日志到 root/file handler。"""
        start = time.perf_counter()
        client_host = request.client.host if request.client else "-"
        method = request.method
        path = request.url.path
        query = request.url.query
        full_path = f"{path}?{query}" if query else path
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "http_request failed method=%s path=%s client=%s ms=%.1f",
                method,
                full_path,
                client_host,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "http_request method=%s path=%s status=%s client=%s ms=%.1f",
            method,
            full_path,
            response.status_code,
            client_host,
            elapsed_ms,
        )
        return response

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