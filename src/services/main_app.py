from fastapi.responses import RedirectResponse

from ingestion.async_parse import parse_local_file_to_markdown_file
from services.agent_router import router as agent_router
from services.auth_router import router as auth_router
from services.create_app import create_app
from services.knowledge_router import router as knowledge_router
app = create_app()

app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(agent_router)

@app.get("/")
async def redirect_root_to_docs() -> RedirectResponse:
    """Redirect root to docs."""
    return RedirectResponse("/docs")

@app.get("/ingest")
async def ingest():
    """Ingest a file."""
    await parse_local_file_to_markdown_file("static/kb_uploads/2/6a06cf2ebbd9401daf0ce16363f02c8f_example.docx")
    return "ingest"

@app.get("/ok")
async def ok() -> str:
    """Health check."""
    return "ok"
