from fastapi.responses import RedirectResponse

from services.agent_router import router as agent_router
from services.auth_router import router as auth_router
from services.create_app import create_app

app = create_app()

app.include_router(auth_router)
app.include_router(agent_router)

@app.get("/")
async def redirect_root_to_docs() -> RedirectResponse:
    """Redirect root to docs."""
    return RedirectResponse("/docs")

 
@app.get("/ok")
async def ok() -> str:
    """Health check."""
    return "ok"
