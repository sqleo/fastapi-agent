"""通过 LangGraph SDK 调用远程服务（``LANGGRAPH_API_URL``）上的 Agent。

对话线程（thread）与 checkpoint 由 **LangGraph 服务端** 持久化；本路由只做鉴权并转发
``configurable.user_id``。生产环境建议统一使用 ``/agent/*``，与进程内直连 ``graph`` 的路径分离，
避免两套会话状态。

流式接口 ``/chat/stream`` 使用 SSE，每条 ``data:`` 后为 JSON，便于前端区分正文与思考片段
（若远程消息里带有 ``additional_kwargs`` / 多模态块，则会尽量解析）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

from agent.tools import tool_catalog
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger("services.agent_api")

LANGGRAPH_API_URL = os.getenv("LANGGRAPH_API_URL", "http://localhost:8123")


def _agent_stream_modes() -> list[str]:
    """LangGraph ``runs.stream`` 的 ``stream_mode`` 列表，逗号分隔，见官方 StreamMode。"""
    raw = os.getenv(
        "LANGGRAPH_AGENT_STREAM_MODES",
        "messages-tuple,values,updates,custom",
    ).strip()
    modes = [x.strip() for x in raw.split(",") if x.strip()]
    return modes or ["values", "updates", "custom"]


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str
    thread_id: str | None = None
    enabled_tools: list[str] | None = Field(
        default=None,
        description="允许模型使用的工具 name 列表（与 GET /agent/tools 一致）；不传=全部可用，[]=全部禁用",
    )


class AgentToolItem(BaseModel):
    """可暴露给前端的工具元数据。"""

    name: str
    description: str | None = None


def _agent_run_config(
    *,
    user_id: int,
    enabled_tools: list[str] | None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    # LangMem 命名空间模板从 configurable 取字符串键 user_id / thread_id
    conf: dict[str, Any] = {"user_id": str(user_id)}
    if thread_id:
        conf["thread_id"] = str(thread_id)
    if enabled_tools is not None:
        conf["enabled_tools"] = enabled_tools
    return {"configurable": conf}


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    thread_id: str


def _sse_json(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.get("/tools", response_model=SuccessResponse[list[AgentToolItem]])
async def list_agent_tools(
    current_user: CurrentUserDeps,
):
    """列出当前 Agent 注册的工具，供前端展示开关（需登录）。"""
    rows = [AgentToolItem(**x) for x in tool_catalog()]
    _ = current_user.id
    return ok(rows, message="查询成功")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    current_user: CurrentUserDeps,
):
    """向 Agent 发一条消息并等待完整回复（非流式）。"""
    logger.info(
        "graph_chat start user_id=%s thread_id=%s msg_chars=%s tools=%s",
        current_user.id,
        req.thread_id or "-",
        len(req.message or ""),
        "all" if req.enabled_tools is None else len(req.enabled_tools),
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=req.enabled_tools,
        thread_id=tid,
    )

    result = await client.runs.wait(
        tid,
        assistant_id="agent",
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
        "graph_chat done user_id=%s thread_id=%s reply_chars=%s",
        current_user.id,
        tid,
        len(reply or ""),
    )

    return ChatResponse(reply=reply, thread_id=tid)

async def _transform_stream_part(ev: str, raw_data: Any):
    """清洗 LangGraph 原始流数据，只产出前端需要的精简包。"""
    if ev != "messages" or not isinstance(raw_data, list) or not raw_data:
        return

    msg = raw_data[0]
    if not isinstance(msg, dict):
        return

    msg_type = msg.get("type", "")
    content = msg.get("content", "")
    tool_calls = msg.get("tool_calls")

    reasoning = (msg.get("additional_kwargs") or {}).get("reasoning_content")
    if reasoning:
        yield {"type": "thinking", "content": reasoning}

    if msg_type in ("AIMessageChunk", "ai", "AIMessage"):
        if tool_calls:
            t_names = [tc.get("name") for tc in tool_calls if tc.get("name")]
            if t_names:
                yield {"type": "tool", "content": f"调用工具: {', '.join(t_names)}..."}
        elif content:
            yield {"type": "text", "content": content}

    elif msg_type in ("tool", "ToolMessage", "ToolMessageChunk"):
        tool_name = msg.get("name", "")
        if content:
            yield {"type": "reference", "tool": tool_name, "content": content}
 
@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: CurrentUserDeps,
):
    """SSE：每条 ``data:`` 后为 JSON。
    订阅哪些模式由环境变量 ``LANGGRAPH_AGENT_STREAM_MODES`` 控制（逗号分隔），默认
    ``messages-tuple,values,updates,debug``。
    """
    logger.info(
        "graph_stream start user_id=%s thread_id=%s msg_chars=%s tools=%s",
        current_user.id,
        req.thread_id or "-",
        len(req.message or ""),
        "all" if req.enabled_tools is None else len(req.enabled_tools),
    )
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=req.enabled_tools,
        thread_id=tid,
    )

    stream_modes = _agent_stream_modes()

    async def event_generator():
        event_count = 0
        try:
            yield _sse_json(
                {"type": "start", "thread_id": tid, "stream_modes": stream_modes}
            )
            async for part in client.runs.stream(
                tid,
                assistant_id="agent",
                input={"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=stream_modes,
            ):
                event_count += 1
                ev = getattr(part, "event", "")
                raw = part.data if hasattr(part, "data") else None
                # 错误拦截
                if ev == "error":
                    yield _sse_json({"type": "error", "message": str(raw)})
                    return

                # --- 核心：通过清洗函数转换数据 ---
                async for clean_chunk in _transform_stream_part(ev, raw):
                    yield _sse_json(clean_chunk)

            # 结束标志
            yield _sse_json({"type": "done", "thread_id": tid})
            
        except Exception as e:
            logger.exception("Stream execution failed for tid=%s", tid)
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
