"""FastAPI 应用入口：组装并注册全部业务路由."""

from fastapi.responses import RedirectResponse

from services.create_app import create_app
from services.routers.agent import router as agent_router
from services.routers.auth import router as auth_router
from services.routers.file_management import router as file_management_router
from services.routers.knowledge_base import router as knowledge_base_router
from services.routers.llm_global_setting import router as llm_global_setting_router
from services.routers.llm_vendor import router as llm_vendor_router
from services.routers.monitor import router as monitor_router

app = create_app()

app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(file_management_router)
app.include_router(knowledge_base_router)
app.include_router(llm_vendor_router)
app.include_router(llm_global_setting_router)
app.include_router(monitor_router)


@app.get("/")
async def redirect_root_to_docs() -> RedirectResponse:
    """Redirect root to docs."""
    return RedirectResponse("/docs")


@app.get("/ok")
async def ok() -> str:
    """Health check."""
    return "ok"
