"""路由 + 检索 + 生成示例图 ``graph_service``：对应 ``langgraph.json`` 中 ``graph_service``。

进程内直连与 LangGraph API 共用 ``graph``（checkpoint）。
不经过 LangGraph SDK ``client.runs.*``。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.core.graph_service import graph_with_checkpoint
from infra.langgraph import delete_graph_service_conversation
from schemas.chat_schema import DeleteChatResponse
from services.routers.agent import (
    ChatResponse,
    _agent_run_config,
    _agent_stream_modes,
    _agent_stream_subgraphs,
    _sse_json,
)
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok

logger = logging.getLogger("services.graph_service_api")

router = APIRouter(prefix="/agent/graph-service", tags=["Agent — GraphService"])

ASSISTANT_ID_GRAPH_SERVICE = "graph_service"


def _last_assistant_text(result: dict[str, Any]) -> str:
    """从 ``ainvoke`` 返回的 state 中取最后一条助手内容（兼容 dict / Message）。"""
    msgs = result.get("messages") or []
    if not msgs:
        return ""
    last = msgs[-1]
    if isinstance(last, dict):
        return str(last.get("content") or "")
    c = getattr(last, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            str(b.get("text", ""))
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(parts).strip()
    return str(c or "")


def _yield_sse_from_chat_model_stream(ev: dict[str, Any]):
    """从 ``astream_events`` 的 ``on_chat_model_stream`` 拆出 ``generate`` 节点 token（不落库、不包 Runnable）。"""
    # 处理 chat model 流式输出（generate 节点）
    if ev.get("event") == "on_chat_model_stream":
        meta = ev.get("metadata") or {}
        if meta.get("langgraph_node") == "generate":
            data = ev.get("data")
            if not isinstance(data, dict):
                return
            chunk = data.get("chunk")
            if chunk is None:
                return
            content = getattr(chunk, "content", None)
            if isinstance(content, str) and content:
                yield {"type": "text", "content": content}
                return
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = str(block.get("text") or "")
                        if text:
                            yield {"type": "text", "content": text}
        return

    # 处理节点完成事件（兼容 classify 节点直接输出）
    if ev.get("event") == "on_chain_end":
        meta = ev.get("metadata") or {}
        node_name = meta.get("langgraph_node")
        if node_name == "classify":
            data = ev.get("data")
            if not isinstance(data, dict):
                return
            output = data.get("output")
            if not isinstance(output, dict):
                return
            messages = output.get("messages")
            if not isinstance(messages, list):
                return
            for msg in messages:
                if hasattr(msg, "content"):
                    content = msg.content
                    if isinstance(content, str) and content:
                        yield {"type": "text", "content": content}
                        return
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = str(block.get("text") or "")
                                if text:
                                    yield {"type": "text", "content": text}
        return


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
    """非流式。"""
    logger.info(
        "graph_service_chat start user_id=%s thread_id=%s",
        current_user.id,
        req.thread_id or "-",
    )
    tid = req.thread_id or str(uuid.uuid4())
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=None,
        thread_id=tid,
        assistant_id=ASSISTANT_ID_GRAPH_SERVICE,
    )

    result = await graph_with_checkpoint.ainvoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    reply = _last_assistant_text(result)
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
    """SSE 流式。"""
    logger.info(
        "graph_service_stream start user_id=%s thread_id=%s",
        current_user.id,
        req.thread_id or "-",
    )
    tid = req.thread_id or str(uuid.uuid4())
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
            async for ev in graph_with_checkpoint.astream_events(
                {"messages": [{"role": "user", "content": req.message}]},
                config,
                version="v2",
            ):
                for piece in _yield_sse_from_chat_model_stream(
                    ev if isinstance(ev, dict) else dict(ev)
                ):
                    yield _sse_json(piece)
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


@router.delete(
    "/chat/{thread_id}",
    response_model=SuccessResponse[DeleteChatResponse],
    summary="删除对话（直连 graph_service）",
    description=(
        "删除本进程内 graph_service 在 checkpoint 中该 thread 的状态（多轮上下文）。"
        "与 ``DELETE /agent/chat/{thread_id}``（SDK 删除 LangGraph Thread）语义对齐；"
        "直连路径不经过 LangGraph SDK。"
    ),
)
async def graph_service_delete_chat(
    thread_id: str,
    current_user: CurrentUserDeps,
):
    """删除对话：清理 checkpoint 中该 ``thread_id`` 的数据。"""
    tid = (thread_id or "").strip()
    if not tid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="thread_id 无效",
        )
    logger.info(
        "graph_service_delete_chat user_id=%s thread_id=%s",
        current_user.id,
        tid,
    )
    try:
        await delete_graph_service_conversation(tid)
    except Exception as e:
        logger.exception("graph_service_delete_chat failed thread_id=%s", tid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除对话失败，请稍后重试",
        ) from e

    return ok(
        DeleteChatResponse(thread_id=tid, message="对话已成功删除"),
        message="删除成功",
    )
