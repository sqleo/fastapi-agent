"""路由 + 检索 + 生成示例图 ``graph_service``：对应 ``langgraph.json`` 中 ``graph_service``。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

from services.routers.agent import (
    LANGGRAPH_API_URL,
    ChatResponse,
    _agent_run_config,
    _agent_stream_modes,
    _agent_stream_subgraphs,
    _sse_json,
    _transform_stream_part,
)
from utils.auth_deps import CurrentUserDeps

logger = logging.getLogger("services.graph_service_api")

router = APIRouter(prefix="/agent/graph-service", tags=["Agent — GraphService"])

ASSISTANT_ID_GRAPH_SERVICE = "graph_service"


class GraphServiceChatRequest(BaseModel):
    """与 ``graph_service`` 图对话（MessagesState，无独立工具开关字段）。"""

    message: str
    thread_id: str | None = Field(
        default=None,
        description="已有会话则传入；不传则新建线程",
    )


@router.post("/chat", response_model=ChatResponse)
async def graph_service_chat(
    req: GraphServiceChatRequest,
    current_user: CurrentUserDeps,
):
    """非流式：``assistant_id=graph_service``。"""
    logger.info(
        "graph_service_chat start user_id=%s thread_id=%s",
        current_user.id,
        req.thread_id or "-",
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=None,
        thread_id=tid,
        assistant_id=ASSISTANT_ID_GRAPH_SERVICE,
    )

    result = await client.runs.wait(
        tid,
        assistant_id=ASSISTANT_ID_GRAPH_SERVICE,
        input={"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    last_message = result["messages"][-1]
    reply = (
        last_message.get("content", "")
        if isinstance(last_message, dict)
        else str(last_message)
    )
    logger.info(
        "graph_service_chat done user_id=%s thread_id=%s reply_chars=%s",
        current_user.id,
        tid,
        len(reply or ""),
    )
    return ChatResponse(reply=reply, thread_id=tid)


@router.post("/chat/stream")
async def graph_service_chat_stream(
    req: GraphServiceChatRequest,
    current_user: CurrentUserDeps,
):
    """SSE 流式，语义同其它 Agent 流式接口。"""
    logger.info(
        "graph_service_stream start user_id=%s thread_id=%s",
        current_user.id,
        req.thread_id or "-",
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=None,
        thread_id=tid,
        assistant_id=ASSISTANT_ID_GRAPH_SERVICE,
    )
    stream_modes = _agent_stream_modes()
    stream_subgraphs = _agent_stream_subgraphs()

    async def event_generator():
        try:
            yield _sse_json(
                {
                    "type": "start",
                    "thread_id": tid,
                    "stream_modes": stream_modes,
                    "stream_subgraphs": stream_subgraphs,
                    "assistant_id": ASSISTANT_ID_GRAPH_SERVICE,
                }
            )
            async for part in client.runs.stream(
                tid,
                assistant_id=ASSISTANT_ID_GRAPH_SERVICE,
                input={"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=stream_modes,
                stream_subgraphs=stream_subgraphs,
            ):
                ev = getattr(part, "event", "")
                raw = part.data if hasattr(part, "data") else None
                if ev == "error":
                    yield _sse_json({"type": "error", "message": str(raw)})
                    return
                if ev == "interrupt" or (
                    isinstance(raw, dict) and raw.get("type") == "user_pause"
                ):
                    yield _sse_json({
                        "type": "paused",
                        "thread_id": tid,
                        "message": "生成已暂停",
                        "checkpoint": raw.get("checkpoint_id")
                        if isinstance(raw, dict)
                        else None,
                    })
                    continue
                async for clean_chunk in _transform_stream_part(ev, raw):
                    yield _sse_json(clean_chunk)
            yield _sse_json({"type": "done", "thread_id": tid})
        except Exception:
            logger.exception("graph_service stream failed tid=%s", tid)
            yield _sse_json({"type": "error", "message": "流式接口异常"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
