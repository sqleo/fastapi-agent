import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动阶段
        print("lifespan：启动阶段")
        yield
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app = FastAPI(
        docs_url=False,
        redoc_url=False,
        lifespan=lifespan
    )
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