from fastapi.responses import RedirectResponse
from services.create_app import create_app

app = create_app()


@app.get("/")

async def redirect_root_to_docs() -> RedirectResponse:
    return RedirectResponse("/docs")

