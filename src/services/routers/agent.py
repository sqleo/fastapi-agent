"""通过 LangGraph SDK 调用远程服务（``LANGGRAPH_API_URL``）上的 Agent。

对话线程（thread）与 checkpoint 由 **LangGraph 服务端** 持久化；本路由只做鉴权并转发
``configurable.user_id``。生产环境建议统一使用 ``/agent/*``，与进程内直连 ``graph`` 的路径分离，
避免两套会话状态。

流式接口 ``/chat/stream`` 使用 SSE，每条 ``data:`` 后为 JSON，便于前端区分正文与思考片段
（若远程消息里带有 ``additional_kwargs`` / 多模态块，则会尽量解析）。
"""

from __future__ import annotations

import json
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

LANGGRAPH_API_URL = os.getenv("LANGGRAPH_API_URL", "http://localhost:8123")


def _agent_stream_modes() -> list[str]:
    """LangGraph ``runs.stream`` 的 ``stream_mode`` 列表，逗号分隔，见官方 StreamMode。"""
    raw = os.getenv(
        "LANGGRAPH_AGENT_STREAM_MODES",
        "messages-tuple,values,updates,custom",
    ).strip()
    modes = [x.strip() for x in raw.split(",") if x.strip()]
    return modes or ["messages-tuple", "values", "updates", "custom"]


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


def _agent_run_config(*, user_id: int, enabled_tools: list[str] | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"configurable": {"user_id": user_id}}
    if enabled_tools is not None:
        cfg["configurable"]["enabled_tools"] = enabled_tools
    return cfg


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    thread_id: str


def _sse_json(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _message_dict_from_messages_tuple_payload(payload: Any) -> dict[str, Any] | None:
    """LangGraph ``messages-tuple`` 的 SSE ``data`` 为 ``[message, metadata]``，消息在索引 0。"""
    if not isinstance(payload, list) or not payload:
        return None
    # 标准：(message, meta)
    first = payload[0]
    if isinstance(first, dict) and (
        "role" in first
        or first.get("type") in ("ai", "human", "tool", "system", "AIMessage", "HumanMessage")
        or "content" in first
    ):
        return first
    if len(payload) > 1:
        second = payload[1]
        if isinstance(second, dict) and ("role" in second or "content" in second):
            return second
    return None


def _content_and_reasoning_from_message_dict(msg: dict[str, Any]) -> tuple[str, str]:
    """从流式消息 dict 中拆出 (正文, 思考) 增量。"""
    text = ""
    reasoning = ""
    raw = msg.get("content")
    if isinstance(raw, str) and raw:
        text = raw
    elif isinstance(raw, list):
        for block in raw:
            if not isinstance(block, dict):
                if isinstance(block, str):
                    text += block
                continue
            btype = block.get("type") or ""
            if btype == "text":
                text += str(block.get("text", "") or "")
            elif btype in ("thinking", "reasoning", "reasoning_content"):
                reasoning += str(
                    block.get("thinking") or block.get("text") or block.get("content") or ""
                )
    ak = msg.get("additional_kwargs")
    if isinstance(ak, dict):
        for key in ("reasoning_content", "reasoning"):
            v = ak.get(key)
            if v:
                reasoning += str(v)
    return text, reasoning


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
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    config = _agent_run_config(user_id=current_user.id, enabled_tools=req.enabled_tools)

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
async def chat_stream(
    req: ChatRequest,
    current_user: CurrentUserDeps,
):
    """SSE：每条 ``data:`` 后为 JSON。

    - ``{"type":"start","thread_id":"..."}`` / ``{"type":"done",...}`` — 生命周期
    - ``{"type":"stream","event":"<LangGraph 事件名>","data":...}`` — 透传 LangGraph 流式块；
      ``event`` 如 ``metadata``、``messages``、``values``、``updates``、``debug`` 等，便于前端分渠道打日志
    - 当 ``event`` 为消息类且可解析时，额外带 ``delta_content`` / ``delta_reasoning``（与旧前端兼容）
    - ``{"type":"error",...}`` — 执行失败（在 ``stream``+``event:error`` 之后仍会发一条摘要）

    订阅哪些模式由环境变量 ``LANGGRAPH_AGENT_STREAM_MODES`` 控制（逗号分隔），默认
    ``messages-tuple,values,updates,debug``。
    """
    client = get_client(url=LANGGRAPH_API_URL)

    if req.thread_id:
        thread = await client.threads.get(req.thread_id)
    else:
        thread = await client.threads.create()

    tid = thread["thread_id"]
    config = _agent_run_config(user_id=current_user.id, enabled_tools=req.enabled_tools)

    stream_modes = _agent_stream_modes()

    async def event_generator():
        try:
            yield _sse_json({"type": "start", "thread_id": tid, "stream_modes": stream_modes})
            async for part in client.runs.stream(
                tid,
                assistant_id="agent",
                input={"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=stream_modes,
            ):
                ev = getattr(part, "event", "") or ""
                raw = part.data if hasattr(part, "data") else None
                try:
                    safe_data: Any = jsonable_encoder(raw)
                except Exception:
                    safe_data = {"_unserializable": repr(raw)}

                chunk: dict[str, Any] = {
                    "type": "stream",
                    "event": ev,
                    "data": safe_data,
                }
                eid = getattr(part, "id", None)
                if eid is not None:
                    chunk["id"] = eid

                if ev.startswith("messages"):
                    msg = _message_dict_from_messages_tuple_payload(raw)
                    if msg is not None:
                        td, rd = _content_and_reasoning_from_message_dict(msg)
                        if td:
                            chunk["delta_content"] = td
                        if rd:
                            chunk["delta_reasoning"] = rd

                yield _sse_json(chunk)

                if ev == "error":
                    detail = raw if isinstance(raw, dict) else {}
                    err_type = detail.get("error")
                    err_msg = detail.get("message") or str(detail) or "LangGraph 流式执行出错"
                    yield _sse_json(
                        {
                            "type": "error",
                            "error_type": err_type,
                            "message": err_msg,
                        }
                    )
                    return

                if chunk.get("delta_content"):
                    yield _sse_json({"type": "content", "delta": chunk["delta_content"]})
                if chunk.get("delta_reasoning"):
                    yield _sse_json({"type": "reasoning", "delta": chunk["delta_reasoning"]})

            yield _sse_json({"type": "done", "thread_id": tid})
        except Exception as e:
            yield _sse_json({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
