"""通过 LangGraph SDK 调用远程服务（``LANGGRAPH_API_URL``）上的 Agent。

流式接口 ``/chat/stream`` 使用 SSE，每条 ``data:`` 后为 JSON，便于前端区分正文与思考片段
（若远程消息里带有 ``additional_kwargs`` / 多模态块，则会尽量解析）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

from agent.tools import tool_catalog
from agent.control.interrupt import request_pause, resume_from_pause
from agent.control.time_travel import get_formatted_history, travel
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from schemas.chat_schema import DeleteChatResponse
from schemas.chat_control_schema import (
    HistoryResponse,
    PauseResponse,
    ResumeResponse,
    TimeTravelResponse,
)

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

                # 中断检测（支持用户暂停）
                if ev == "interrupt" or (isinstance(raw, dict) and raw.get("type") == "user_pause"):
                    yield _sse_json({
                        "type": "paused",
                        "thread_id": tid,
                        "message": "生成已暂停，可调用 /pause 或 /resume",
                        "checkpoint": raw.get("checkpoint_id") if isinstance(raw, dict) else None,
                    })
                    continue

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


@router.delete(
    "/chat/{thread_id}",
    response_model=SuccessResponse[DeleteChatResponse],
    summary="删除对话",
    description="删除指定对话线程（LangGraph Thread），同时清理 checkpoint 和关联记忆。",
)
async def delete_chat(
    thread_id: str,
    current_user: CurrentUserDeps,
):
    """删除对话。

    前端调用此接口后，对话将永久删除（不可恢复）。
    """
    logger.info(
        "delete_chat start user_id=%s thread_id=%s",
        current_user.id,
        thread_id,
    )

    client = get_client(url=LANGGRAPH_API_URL)

    # 校验线程是否存在（LangGraph 会抛出异常如果不存在）
    try:
        await client.threads.get(thread_id)
    except Exception as e:  # LangGraph SDK 通常抛 404 相关异常
        logger.warning("Thread not found or access error: %s", e)
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在或无权访问",
        ) from e

    # 执行删除操作
    await client.threads.delete(thread_id)

    logger.info(
        "delete_chat success user_id=%s thread_id=%s",
        current_user.id,
        thread_id,
    )

    return ok(
        DeleteChatResponse(
            thread_id=thread_id,
            message="对话已成功删除",
        ),
        message="删除成功",
    )


@router.post(
    "/chat/{thread_id}/pause",
    response_model=SuccessResponse[PauseResponse],
    summary="暂停生成（精细中断）",
)
async def pause_generation(
    thread_id: str,
    current_user: CurrentUserDeps,
    req: PauseRequest | None = None,
) -> SuccessResponse[PauseResponse]:
    """在 LLM 生成过程中暂停（支持每一段 token 粒度）。
    
    调用后当前流式输出会中断，并保存 checkpoint，支持后续继续或时间旅行。
    """
    logger.info("pause_generation user_id=%s thread_id=%s", current_user.id, thread_id)

    try:
        result = await request_pause(thread_id)
        # 这里可以进一步通过 SDK 获取最新 checkpoint_id（简化版先不取）
        return ok(
            PauseResponse(
                thread_id=thread_id,
                checkpoint_id=None,  # 可后续增强从 LangGraph 获取
                message="生成已暂停",
            ),
            message="已暂停生成",
        )
    except Exception as e:
        logger.exception("Failed to pause generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"暂停失败: {str(e)}",
        ) from e


@router.post(
    "/chat/{thread_id}/resume",
    response_model=SuccessResponse[ResumeResponse],
    summary="继续生成",
)
async def resume_generation(
    thread_id: str,
    current_user: CurrentUserDeps,
    req: ResumeRequest | None = None,
) -> SuccessResponse[ResumeResponse]:
    """从暂停点继续生成剩余内容。"""
    logger.info("resume_generation user_id=%s thread_id=%s", current_user.id, thread_id)

    resume_value = req.resume_value if req else None
    result = await resume_from_pause(thread_id, resume_value)

    return ok(
        ResumeResponse(
            thread_id=thread_id,
            message="已恢复生成",
        ),
        message="继续生成",
    )


@router.get(
    "/chat/{thread_id}/history",
    response_model=SuccessResponse[HistoryResponse],
    summary="获取对话历史 checkpoint（时间旅行）",
)
async def get_chat_history(
    thread_id: str,
    current_user: CurrentUserDeps,
) -> SuccessResponse[HistoryResponse]:
    """获取该对话的所有 checkpoint，支持时间旅行回放。
    
    业务路由只做鉴权和响应封装，核心逻辑在 src/agent/time_travel.py 中。
    """
    logger.info("get_chat_history user_id=%s thread_id=%s", current_user.id, thread_id)
    
    checkpoints = await get_formatted_history(thread_id, limit=20)
    
    return ok(
        HistoryResponse(
            thread_id=thread_id,
            checkpoints=checkpoints,
            total=len(checkpoints),
        ),
        message="查询成功",
    )


@router.post(
    "/chat/{thread_id}/travel",
    response_model=SuccessResponse[TimeTravelResponse],
    summary="时间旅行",
)
async def time_travel(
    thread_id: str,
    req: TimeTravelRequest,
    current_user: CurrentUserDeps,
) -> SuccessResponse[TimeTravelResponse]:
    """从指定历史 checkpoint 回放或创建新分支（fork）。
    
    业务路由仅负责鉴权和响应格式化，核心逻辑（fork/replay）已移至 src/agent/time_travel.py。
    """
    logger.info(
        "time_travel user_id=%s thread_id=%s checkpoint=%s mode=%s input=%s",
        current_user.id,
        thread_id,
        req.checkpoint_id,
        req.mode,
        bool(req.new_input),
    )

    result = await travel(
        thread_id=thread_id,
        checkpoint_id=req.checkpoint_id,
        mode=req.mode,
        new_input=req.new_input,
        user_id=current_user.id,
    )

    return ok(
        TimeTravelResponse(
            thread_id=thread_id,
            new_thread_id=result.get("new_thread_id"),
            checkpoint_id=req.checkpoint_id,
            mode=req.mode,
            message=result.get("message", "时间旅行成功"),
        ),
        message="时间旅行成功",
    )
