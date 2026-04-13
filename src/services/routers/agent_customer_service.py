"""智能客服专用对话：固定 LangGraph 图 ``customer_service``，与通用 ``/agent/chat`` 分离."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

from agent.tools.customer_service_tools import merge_customer_service_enabled_tools
from services.routers.agent import (
    LANGGRAPH_API_URL,
    ChatResponse,
    _agent_run_config,
    _agent_stream_modes,
    _sse_json,
    _transform_stream_part,
)
from utils.auth_deps import CurrentUserDeps

logger = logging.getLogger("services.agent_customer_service")

router = APIRouter(prefix="/agent/customer-service", tags=["Agent — 智能客服"])

# LangGraph Server 注册的图 id，须与 langgraph.json 中 ``graphs`` 键一致
ASSISTANT_ID_CUSTOMER_SERVICE = "customer_service"


class CustomerServiceChatRequest(BaseModel):
    """智能客服聊天请求。"""

    message: str
    thread_id: str | None = None
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "本次允许的工具名列表；不传则使用智能客服默认："
            "knowledge_base_search + LangMem（manage_memory、search_memory）。"
            "LangMem 工具会与所选集合自动合并，避免被误关。"
        ),
    )


@router.post("/chat", response_model=ChatResponse)
async def customer_service_chat(
    req: CustomerServiceChatRequest,
    current_user: CurrentUserDeps,
):
    """非流式对话；底层 ``assistant_id=customer_service``。"""
    enabled = merge_customer_service_enabled_tools(req.enabled_tools)
    logger.info(
        "customer_service_chat start user_id=%s thread_id=%s tools=%s",
        current_user.id,
        req.thread_id or "-",
        len(enabled),
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=enabled,
        thread_id=tid,
        assistant_id=ASSISTANT_ID_CUSTOMER_SERVICE,
    )

    result = await client.runs.wait(
        tid,
        assistant_id=ASSISTANT_ID_CUSTOMER_SERVICE,
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
        "customer_service_chat done user_id=%s thread_id=%s reply_chars=%s",
        current_user.id,
        tid,
        len(reply or ""),
    )

    return ChatResponse(reply=reply, thread_id=tid)


@router.post("/chat/stream")
async def customer_service_chat_stream(
    req: CustomerServiceChatRequest,
    current_user: CurrentUserDeps,
):
    """SSE 流式；语义同 ``POST /agent/chat/stream``，图 id 为 ``customer_service``。"""
    enabled = merge_customer_service_enabled_tools(req.enabled_tools)
    logger.info(
        "customer_service_stream start user_id=%s thread_id=%s tools=%s",
        current_user.id,
        req.thread_id or "-",
        len(enabled),
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=enabled,
        thread_id=tid,
        assistant_id=ASSISTANT_ID_CUSTOMER_SERVICE,
    )

    stream_modes = _agent_stream_modes()

    async def event_generator():
        try:
            yield _sse_json(
                {"type": "start", "thread_id": tid, "stream_modes": stream_modes}
            )
            async for part in client.runs.stream(
                tid,
                assistant_id=ASSISTANT_ID_CUSTOMER_SERVICE,
                input={"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=stream_modes,
            ):
                ev = getattr(part, "event", "")
                raw = part.data if hasattr(part, "data") else None
                if ev == "error":
                    yield _sse_json({"type": "error", "message": str(raw)})
                    return
                if ev == "interrupt" or (isinstance(raw, dict) and raw.get("type") == "user_pause"):
                    yield _sse_json({
                        "type": "paused",
                        "thread_id": tid,
                        "message": "生成已暂停，可调用 /agent/chat/{thread_id}/pause 或 resume",
                        "checkpoint": raw.get("checkpoint_id") if isinstance(raw, dict) else None,
                    })
                    continue
                async for clean_chunk in _transform_stream_part(ev, raw):
                    yield _sse_json(clean_chunk)

            yield _sse_json({"type": "done", "thread_id": tid})
        except Exception:
            logger.exception("customer_service stream failed tid=%s", tid)
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
