from fastapi import Query
from fastapi.responses import RedirectResponse

from ingestion.async_parse import parse_local_file_to_markdown_file
from schemas.auth_schema import IngestRequest
from services.agent_router import router as agent_router
from services.auth_router import router as auth_router
from services.create_app import create_app
from services.knowledge_router import router as knowledge_router
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

app = create_app()

app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(agent_router)

@app.get("/")
async def redirect_root_to_docs() -> RedirectResponse:
    """Redirect root to docs."""
    return RedirectResponse("/docs")

@app.post("/ingest", response_model=SuccessResponse[IngestRequest])
async def ingestRequest(
    body: IngestRequest,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[IngestRequest]:
    await parse_local_file_to_markdown_file(
        file_path=body.file_path,
        db_session=session,
        kb_file_id=body.kb_file_id,
        knowledge_base_id=body.knowledge_base_id,
        index_to_milvus=True,
    )
    await session.commit()
    return ok(data=body, message="ingest 完成")

@app.get("/ok")
async def ok() -> str:
    """Health check."""
    return "ok"
