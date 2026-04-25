"""通过本地图实例直接运行 Agent（脱离独立 LangGraph 平台部署）。

流式接口 ``/chat/stream`` 模拟原 SDK 的 SSE 输出，每条 ``data:`` 后为 JSON，
便于前端区分正文与思考片段。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from infra.langgraph.control import (
    request_pause,
    resume_from_pause,
    get_formatted_history,
    travel,
)
from infra.langgraph import delete_graph_service_conversation
from agent.tools import (
    hidden_from_client_tool_names,
    merge_enabled_with_hidden,
    tool_catalog_for_client,
)
from schemas.chat_control_schema import (
    HistoryResponse,
    PauseRequest,
    PauseResponse,
    ResumeRequest,
    ResumeResponse,
    TimeTravelRequest,
    TimeTravelResponse,
)
from schemas.chat_schema import DeleteChatResponse
from services.controllers.agent_tool_settings_controller import (
    get_saved_enabled_tools,
    upsert_enabled_tools,
)
from utils.agent_temperature import resolve_llm_temperature_for_assistant
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger("services.agent_api")


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str
    thread_id: str | None = None
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "本次请求允许的工具 name 列表；不传则使用 PUT /agent/tools/settings 保存的偏好；"
            "未保存过偏好时 **默认全部工具开启**；传 [] 表示本次全部禁用"
        ),
    )


class AgentToolItem(BaseModel):
    """可暴露给前端的工具元数据。"""

    name: str
    description: str | None = None
    enabled: bool = Field(
        True,
        description="该工具是否启用；**无保存记录时全部为 true（默认全开）**",
    )


class ToolSettingsUpdate(BaseModel):
    """保存工具开关：与聊天 configurable.enabled_tools 语义一致。"""

    enabled_tools: list[str] | None = Field(
        None,
        description="仅允许列出的工具；null=删除偏好、**恢复默认（全部开启）**；[]=全部禁用",
    )


def _agent_run_config(
    *,
    user_id: int,
    enabled_tools: list[str] | None,
    thread_id: str | None = None,
    assistant_id: str = "agent",
) -> dict[str, Any]:
    # LangMem 命名空间模板从 configurable 取字符串键 user_id / thread_id
    conf: dict[str, Any] = {"user_id": str(user_id)}
    if thread_id:
        conf["thread_id"] = str(thread_id)
    if enabled_tools is not None:
        conf["enabled_tools"] = enabled_tools
    temp = resolve_llm_temperature_for_assistant(assistant_id)
    if temp is not None:
        conf["llm_temperature"] = temp
    return {"configurable": conf}


def _agent_stream_modes() -> list[str]:
    """返回默认的流模式。"""
    return ["messages", "custom"]


def _agent_stream_subgraphs() -> bool:
    """是否流式输出子图内容。"""
    return True


class ChatResponse(BaseModel):
    """Chat response body."""

    reply: str
    thread_id: str


def _sse_json(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _resolve_enabled_tools_for_chat(
    req_tools: list[str] | None,
    sql: AsyncSession,
    user_id: int,
) -> list[str] | None:
    """请求体显式传了 enabled_tools 则优先；否则读用户保存的偏好。"""
    if req_tools is not None:
        return merge_enabled_with_hidden(req_tools)
    saved = await get_saved_enabled_tools(sql, user_id)
    return merge_enabled_with_hidden(saved)


def _catalog_with_enabled(saved: list[str] | None) -> list[dict]:
    """合并对前端暴露的 tool_catalog 与保存的开关状态。"""
    catalog = tool_catalog_for_client()
    if saved is None:
        return [{**t, "enabled": True} for t in catalog]
    allowed = set(saved)
    return [{**t, "enabled": (t["name"] in allowed)} for t in catalog]


@router.get("/tools", response_model=SuccessResponse[list[AgentToolItem]])
async def list_agent_tools(
    current_user: CurrentUserDeps,
    sql: AsyncSqlSessionDeps,
):
    """列出当前 Agent 注册的工具及每个工具的启用状态。"""
    saved = await get_saved_enabled_tools(sql, current_user.id)
    rows = [AgentToolItem(**x) for x in _catalog_with_enabled(saved)]
    return ok(rows, message="查询成功")


@router.put("/tools/settings", response_model=SuccessResponse[None])
async def update_agent_tool_settings(
    body: ToolSettingsUpdate,
    current_user: CurrentUserDeps,
    sql: AsyncSqlSessionDeps,
):
    """保存用户级工具开关。"""
    valid_names = {t["name"] for t in tool_catalog_for_client()}
    if body.enabled_tools is not None:
        unknown = set(body.enabled_tools) - valid_names
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"未知工具名: {sorted(unknown)}",
            )
    await upsert_enabled_tools(sql, current_user.id, body.enabled_tools)
    return ok(None, message="工具开关已保存")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    current_user: CurrentUserDeps,
    sql: AsyncSqlSessionDeps,
):
    """本地调用 Agent 并等待完整回复。"""
    from agent.core.graph import graph

    enabled = await _resolve_enabled_tools_for_chat(req.enabled_tools, sql, current_user.id)
    tid = req.thread_id or str(uuid.uuid4())
    
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=enabled,
        thread_id=tid,
    )

    logger.info("Local graph_chat start tid=%s", tid)
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    messages = result.get("messages", [])
    reply = ""
    if messages:
        last_message = messages[-1]
        reply = last_message.content if hasattr(last_message, "content") else str(last_message)

    return ChatResponse(reply=reply, thread_id=tid)


def _internal_tool_names() -> frozenset[str]:
    return hidden_from_client_tool_names()


async def _transform_stream_part(ev: str, raw_data: Any):
    """清洗本地流数据，模拟原 SDK 输出格式。"""
    if ev == "custom":
        yield {"type": "custom", "payload": raw_data}
        return

    # 本地 astream(stream_mode="updates") 产出 dict: {node_name: {values}}
    # 本地 astream(stream_mode="messages") 产出 (MessageChunk, metadata)
    
    if ev == "messages":
        # raw_data is (Message, metadata)
        msg = raw_data[0] if isinstance(raw_data, tuple) else raw_data
        if not hasattr(msg, "type"):
            return
            
        msg_type = msg.type
        content = getattr(msg, "content", "")
        tool_calls = getattr(msg, "tool_calls", [])
        internal = _internal_tool_names()

        # 处理思考过程
        reasoning = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
        if reasoning:
            yield {"type": "thinking", "content": reasoning}

        if msg_type in ("ai", "AIMessage", "AIMessageChunk"):
            if tool_calls:
                t_names = [tc.get("name") for tc in tool_calls if tc.get("name")]
                visible = [n for n in t_names if n not in internal]
                if visible:
                    yield {"type": "tool", "content": f"调用工具: {', '.join(visible)}..."}
            elif content:
                yield {"type": "text", "content": content}

        elif msg_type in ("tool", "ToolMessage", "ToolMessageChunk"):
            tool_name = getattr(msg, "name", "")
            if tool_name not in internal and content:
                yield {"type": "reference", "tool": tool_name, "content": content}


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: CurrentUserDeps,
    sql: AsyncSqlSessionDeps,
):
    """本地流式 SSE 输出。"""
    from agent.core.graph import graph

    enabled = await _resolve_enabled_tools_for_chat(req.enabled_tools, sql, current_user.id)
    tid = req.thread_id or str(uuid.uuid4())
    config = _agent_run_config(
        user_id=current_user.id,
        enabled_tools=enabled,
        thread_id=tid,
    )

    async def event_generator():
        try:
            yield _sse_json({"type": "start", "thread_id": tid})
            
            # 使用本地 astream 对齐 SDK 行为
            async for mode, data in graph.astream(
                {"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=["messages", "custom"],
            ):
                # 某些版本返回的是 tuple (mode, data)
                async for clean_chunk in _transform_stream_part(mode, data):
                    yield _sse_json(clean_chunk)

            # 结束后检查是否有未完成的 interrupt（暂停点）
            state = await graph.aget_state(config)
            if state.next:
                 yield _sse_json({
                    "type": "paused",
                    "thread_id": tid,
                    "message": "生成已暂停（等待用户输入或手动恢复）",
                })

            yield _sse_json({"type": "done", "thread_id": tid})
        except Exception as e:
            logger.exception("Local stream failed")
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


@router.delete("/chat/{thread_id}", response_model=SuccessResponse[DeleteChatResponse])
async def delete_chat(
    thread_id: str,
    current_user: CurrentUserDeps,
):
    """删除对话及本地持久化数据。"""
    logger.info("delete_chat user_id=%s thread_id=%s", current_user.id, thread_id)
    await delete_graph_service_conversation(thread_id)
    return ok(DeleteChatResponse(thread_id=thread_id, message="对话已删除"), message="删除成功")


@router.post("/chat/{thread_id}/pause", response_model=SuccessResponse[PauseResponse])
async def pause_generation(
    thread_id: str,
    current_user: CurrentUserDeps,
    req: PauseRequest | None = None,
):
    """暂停当前线程的生成过程。"""
    await request_pause(thread_id)
    return ok(PauseResponse(thread_id=thread_id, message="已请求暂停"), message="已暂停")


@router.post("/chat/{thread_id}/resume", response_model=SuccessResponse[ResumeResponse])
async def resume_generation(
    thread_id: str,
    current_user: CurrentUserDeps,
    req: ResumeRequest | None = None,
):
    """继续暂停的生成。"""
    await resume_from_pause(thread_id, req.resume_value if req else None)
    return ok(ResumeResponse(thread_id=thread_id, message="已恢复生成"), message="继续生成")


@router.get("/chat/{thread_id}/history", response_model=SuccessResponse[HistoryResponse])
async def get_chat_history(
    thread_id: str,
    current_user: CurrentUserDeps,
):
    """获取本地 Checkpointer 中的历史状态。"""
    from agent.core.graph import graph
    checkpoints = await get_formatted_history(graph, thread_id, limit=20)
    return ok(HistoryResponse(thread_id=thread_id, checkpoints=checkpoints, total=len(checkpoints)))


@router.post("/chat/{thread_id}/travel", response_model=SuccessResponse[TimeTravelResponse])
async def time_travel(
    thread_id: str,
    req: TimeTravelRequest,
    current_user: CurrentUserDeps,
):
    """本地时间旅行（分支或重放）。"""
    from agent.core.graph import graph
    result = await travel(
        graph,
        thread_id=thread_id,
        checkpoint_id=req.checkpoint_id,
        mode=req.mode,
        new_input=req.new_input,
        user_id=current_user.id,
    )
    return ok(TimeTravelResponse(
        thread_id=thread_id,
        new_thread_id=result.get("new_thread_id"),
        checkpoint_id=req.checkpoint_id,
        mode=req.mode,
        message=result.get("message", "成功"),
    ))
