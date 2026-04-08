from fastapi.responses import RedirectResponse

from services.create_app import create_app
from services.routers.agent import router as agent_router
from services.routers.auth import router as auth_router
from services.routers.llm_global_setting import router as llm_global_setting_router
from services.routers.llm_vendor import router as llm_vendor_router

app = create_app()

app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(llm_vendor_router)
app.include_router(llm_global_setting_router)


@app.get("/")
async def redirect_root_to_docs() -> RedirectResponse:
    """Redirect root to docs."""
    return RedirectResponse("/docs")


@app.get("/ok")
async def ok() -> str:
    """Health check."""
    return "ok"
