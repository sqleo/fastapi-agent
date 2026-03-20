"""FastAPI router for interacting with LangGraph Agent via SDK."""

import os

from fastapi import APIRouter
from langgraph_sdk import get_client
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["Agent"])

LANGGRAPH_API_URL = os.getenv("LANGGRAPH_API_URL", "http://localhost:8123")


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str
    thread_id: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    thread_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the Agent and get a response."""
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    config = {}
    if req.model:
        config["configurable"] = {"model": req.model}

    result = await client.runs.wait(
        thread["thread_id"],
        assistant_id="agent",
        input={"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    last_message = result["messages"][-1]
    reply = last_message.get("content", "") if isinstance(last_message, dict) else str(last_message)

    return ChatResponse(reply=reply, thread_id=thread["thread_id"])


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a message to the Agent and stream the response."""
    from fastapi.responses import StreamingResponse

    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    config = {}
    if req.model:
        config["configurable"] = {"model": req.model}

    async def event_generator():
        async for event in client.runs.stream(
            thread["thread_id"],
            assistant_id="agent",
            input={"messages": [{"role": "user", "content": req.message}]},
            config=config,
            stream_mode="messages-tuple",
        ):
            if hasattr(event, "data") and event.data:
                content = ""
                if isinstance(event.data, list) and len(event.data) >= 2:
                    msg = event.data[1]
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                if content:
                    yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
