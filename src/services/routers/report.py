"""Report Agent API 路由.

通过 HTTP 接口暴露报告生成能力，支持中断、恢复、回滚等操作。
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.graph.state import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.ReportHistoryModel import ReportHistoryStatus
from report.graph import build_report_graph
from report.utils.interrupt_payload import interrupt_payload
from schemas.report_schema import (
    ReportHistoryDetail,
    ReportHistoryListResponse,
)
from services.controllers.report_history_controller import (
    delete_report_history_owned,
    get_report_history_owned,
    infer_report_status,
    list_report_histories_owned,
    upsert_report_history_owned,
)
from services.controllers.report_workspace_mapper import (
    to_history_list_item,
    to_workspace_detail,
)
from utils.auth_deps import CurrentUserDeps
from utils.json import safe_serialize, sse_json
from utils.report_sse import EventHandler, EventPayload, iter_report_sse_events
from utils.report_stream_mapper import map_report_stream_event
from utils.response import BizCode, SuccessResponse, fail, ok
from utils.sql_db import AsyncSqlSessionDeps

logger = logging.getLogger("services.routers.report")

router = APIRouter(tags=["Report"], prefix="/report")

report_graph = build_report_graph()


def _identity_event_handler(payload: EventPayload) -> EventPayload:
    return payload


def _build_custom_event_handler(thread_id: str) -> EventHandler:
    """将 custom 事件映射为前端可直接消费的事件类型。"""
    def _handler(payload: EventPayload) -> EventPayload | None:
        event_name = payload.get("event_name")
        data = payload.get("data")
        if not isinstance(event_name, str) or not isinstance(data, dict):
            return None
        return map_report_stream_event(event_name, data, thread_id=thread_id)

    return _handler


def _build_message_filter_handler(allowed_nodes: set[str] | None) -> EventHandler:
    """按节点过滤 message 事件，None 表示不过滤。"""
    def _handler(payload: EventPayload) -> EventPayload | None:
        if payload.get("type") != "message":
            return payload
        if allowed_nodes is None:
            return payload
        node = payload.get("node")
        if isinstance(node, str) and node in allowed_nodes:
            return payload
        return None

    return _handler


def _resume_node_alias_handler(payload: EventPayload) -> EventPayload:
    """兼容历史字段：resume 流保留 node。"""
    if payload.get("type") != "node":
        return payload
    state = payload.get("state")
    if state == "running":
        return {
            "type": "node",
            "state": "running",
            "node": payload.get("node"),
        }
    if state == "completed":
        return {
            "type": "node",
            "state": "completed",
            "node": payload.get("node"),
            "output": payload.get("output"),
        }
    return payload


class GenerateReportRequest(BaseModel):
    """生成报告请求"""
    user_query: str = Field(..., description="用户查询主题，例如：'2026年Q1新能源汽车市场分析'")
    thread_id: str | None = Field(None, description="可选，指定会话 ID 用于恢复")

class GenerateReportResponse(BaseModel):
    """生成报告响应"""
    thread_id: str = Field(..., description="会话 ID，用于后续查询状态、恢复执行")
    status: str = Field(..., description="状态: running / interrupted / completed")
    current_node: str | None = Field(None, description="当前执行到的节点")
    interrupt_payload: dict[str, Any] | None = Field(None, description="中断时的 payload 数据")
    result: dict[str, Any] | None = Field(None, description="完成时的结果")


class ResumeReportRequest(BaseModel):
    """恢复中断的报告任务"""
    thread_id: str = Field(..., description="会话 ID")
    action: str = Field(..., description="用户选择的操作: confirm / revise / replan")
    updates: dict[str, Any] | None = Field(None, description="额外更新数据，如修改后的大纲")
    metadata: dict[str, Any] | None = Field(None, description="元数据，如节点名称")

class ReportStatusResponse(BaseModel):
    """报告状态查询响应"""
    thread_id: str = Field(..., description="会话 ID")
    status: str = Field(..., description="状态: running / interrupted / completed / not_found")
    current_node: list[str] | None = Field(None, description="待执行节点")
    state: dict[str, Any] | None = Field(None, description="当前完整状态")


def _build_report_config(*, thread_id: str, user_id: int) -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "graph": report_graph,
        }
    }


async def _sync_history_from_graph(
    session: AsyncSession,
    *,
    owner_user_id: int,
    operator_name: str | None,
    thread_id: str,
    config: RunnableConfig,
    user_query: str | None = None,
    status_override: str | None = None,
    interrupt_data: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> None:
    state = await report_graph.aget_state(config)
    state_values = state.values if state and state.values else None
    current_node = list(state.next) if state and state.next else None
    inferred_status = status_override or infer_report_status(list(state.next) if state and state.next else None).value
    await upsert_report_history_owned(
        session,
        owner_user_id=owner_user_id,
        thread_id=thread_id,
        operator_name=operator_name,
        user_query=user_query,
        state_values=state_values,
        status=inferred_status,
        current_node=current_node,
        interrupt_payload=interrupt_data,
        last_error=last_error,
    )


@router.post("/generate")
async def generate_report(
    request: GenerateReportRequest,
    user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
):
    """创建报告生成任务（流式输出）
    
    Server-Sent Events 流式输出每个节点执行状态
    """
    tid = request.thread_id or str(uuid4())
    config = _build_report_config(thread_id=tid, user_id=user.id)
    await upsert_report_history_owned(
        session,
        owner_user_id=user.id,
        thread_id=tid,
        operator_name=user.username,
        user_query=request.user_query,
        status="running",
    )

    async def event_generator():
        try:
            yield sse_json({"type": "lifecycle", "thread_id": tid, "status": "started"})
            events = report_graph.astream_events(
                {"user_query": request.user_query},
                config=config,
                version="v2",
            )
            generate_handlers: dict[str, EventHandler] = {
                "message": lambda _: None,
                "custom": _build_custom_event_handler(tid),
            }
            async for sse_event in iter_report_sse_events(
                events,
                handlers=generate_handlers,
                default_handler=_identity_event_handler,
            ):
                yield sse_event
            interrupt_data = await interrupt_payload(report_graph, config)
            if interrupt_data:
                await _sync_history_from_graph(
                    session,
                    owner_user_id=user.id,
                    operator_name=user.username,
                    thread_id=tid,
                    config=config,
                    user_query=request.user_query,
                    status_override="interrupted",
                    interrupt_data=interrupt_data,
                )
                yield sse_json({
                    "type": "interrupt",
                    "thread_id": tid,
                    "stage": "intent" if (interrupt_data.get("metadata") or {}).get("node_name") == "human_review_intent" else "outline",
                    "message": interrupt_data.get("message") or "等待人工审核",
                    "payload": interrupt_data,
                })
            else:
                await _sync_history_from_graph(
                    session,
                    owner_user_id=user.id,
                    operator_name=user.username,
                    thread_id=tid,
                    config=config,
                    user_query=request.user_query,
                    status_override="completed",
                )
                yield sse_json({"type": "lifecycle", "thread_id": tid, "status": "completed"})

        except Exception as e:
            logger.exception("报告生成失败")
            await upsert_report_history_owned(
                session,
                owner_user_id=user.id,
                thread_id=tid,
                operator_name=user.username,
                user_query=request.user_query,
                status="failed",
                last_error=str(e),
            )
            yield sse_json({"type": "error", "thread_id": tid, "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no", # nginx 反向代理时禁用缓冲，确保实时输出
        },
    )


@router.post("/resume")
async def resume_report(
    request: ResumeReportRequest,
    user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
):
    """恢复被中断的报告任务（流式输出）"""
    tid = request.thread_id
    config = _build_report_config(thread_id=tid, user_id=user.id)

    # 验证状态是否存在
    state = await report_graph.aget_state(config)
    if state is None or not state.values:
        body = fail(
            code=BizCode.NOT_FOUND,
            message=f"会话 {tid} 不存在或已过期",
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=body.model_dump(),
        )
    await upsert_report_history_owned(
        session,
        owner_user_id=user.id,
        thread_id=tid,
        operator_name=user.username,
        state_values=state.values,
        status="running",
        current_node=list(state.next) if state.next else None,
    )

    async def event_generator():
        try:
            yield sse_json({"type": "lifecycle", "thread_id": tid, "status": "started"})
            
            resume_data = {
                "action": request.action,
                **(request.updates or {}),
                "metadata": request.metadata or {},
                "thread_id": tid,
            }
            # 使用 astream_events 流式恢复执行
            events = report_graph.astream_events(
                Command(resume=resume_data),
                config=config,
                version="v2",
            )
            resume_handlers: dict[str, EventHandler] = {
                "node": _resume_node_alias_handler,
                "message": lambda _: None,
                "custom": _build_custom_event_handler(tid),
            }
            async for sse_event in iter_report_sse_events(
                events,
                handlers=resume_handlers,
                default_handler=_identity_event_handler,
            ):
                yield sse_event
            # 检查是否有新的中断
            interrupt_data = await interrupt_payload(report_graph, config)
            if interrupt_data:
                await _sync_history_from_graph(
                    session,
                    owner_user_id=user.id,
                    operator_name=user.username,
                    thread_id=tid,
                    config=config,
                    status_override="interrupted",
                    interrupt_data=interrupt_data,
                )
                yield sse_json({
                    "type": "interrupt",
                    "thread_id": tid,
                    "stage": "intent" if (interrupt_data.get("metadata") or {}).get("node_name") == "human_review_intent" else "outline",
                    "message": interrupt_data.get("message") or "等待人工审核",
                    "payload": interrupt_data,
                })
            else:
                await _sync_history_from_graph(
                    session,
                    owner_user_id=user.id,
                    operator_name=user.username,
                    thread_id=tid,
                    config=config,
                    status_override="completed",
                )
                yield sse_json({"type": "lifecycle", "thread_id": tid, "status": "completed"})

        except Exception as e:
            logger.exception("恢复报告失败")
            await upsert_report_history_owned(
                session,
                owner_user_id=user.id,
                thread_id=tid,
                operator_name=user.username,
                status="failed",
                last_error=str(e),
            )
            yield sse_json({"type": "error", "thread_id": tid, "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{thread_id}", response_model=SuccessResponse[ReportStatusResponse])
async def get_report_status(
    thread_id: str,
    user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
):
    """查询研报当前执行状态。"""
    user_id: int = user.id
    config = _build_report_config(thread_id=thread_id, user_id=user_id)
    history_row = await get_report_history_owned(
        session,
        owner_user_id=user_id,
        thread_id=thread_id,
    )

    state = await report_graph.aget_state(config)
    if state is None or state.values is None:
        if history_row is not None:
            current_node = [history_row.current_node] if history_row.current_node else None
            return ok(
                data=ReportStatusResponse(
                    thread_id=thread_id,
                    status=history_row.status.value if hasattr(history_row.status, "value") else str(history_row.status),
                    current_node=current_node,
                    state=None,
                )
            )
        return ok(
            data=ReportStatusResponse(
                thread_id=thread_id,
                status="not_found",
                current_node=None,
                state=None,
            )
        )

    status = infer_report_status(list(state.next) if state.next else None).value

    # 安全序列化 state，避免 Pydantic 序列化警告
    serialized_state = safe_serialize(state.values) if state.values else None
    await upsert_report_history_owned(
        session,
        owner_user_id=user_id,
        thread_id=thread_id,
        operator_name=user.username,
        state_values=state.values,
        status=status,
        current_node=list(state.next) if state.next else None,
    )

    return ok(
        data=ReportStatusResponse(
            thread_id=thread_id,
            status=status,
            current_node=state.next,  # pyright: ignore[reportArgumentType]
            state=serialized_state,
        )
    )


@router.post("/rollback/{thread_id}/{target_node}", response_model=SuccessResponse[dict])
async def rollback_report(
    thread_id: str,
    target_node: str,
    user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
):
    """将研报回滚到指定节点并同步历史状态。"""
    user_id: int = user.id
    from infra.langgraph.control import rollback_to

    config = _build_report_config(thread_id=thread_id, user_id=user_id)

    try:
        command = await rollback_to(
            config=config,
            target_node=target_node,
        )

        # 执行回滚
        await report_graph.ainvoke(command, config=config)
        await _sync_history_from_graph(
            session,
            owner_user_id=user_id,
            operator_name=user.username,
            thread_id=thread_id,
            config=config,
        )

        return ok(
            data={
                "thread_id": thread_id,
                "rollback_to": target_node,
                "status": "ok",
            }
        )

    except ValueError as e:
        body = fail(
            code=BizCode.BAD_REQUEST,
            message=str(e),
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=body.model_dump(),
        )
    except Exception as e:
        logger.exception("回滚失败")
        body = fail(
            code=BizCode.INTERNAL_ERROR,
            message=f"回滚失败: {str(e)}",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body.model_dump(),
        )


@router.get("/stream/{thread_id}")
async def stream_report(
    thread_id: str,
    user: CurrentUserDeps,
):
    """按 thread_id 继续流式输出研报进度。"""
    user_id: int = user.id
    config = _build_report_config(thread_id=thread_id, user_id=user_id)

    async def event_generator():
        try:
            async for event in report_graph.astream(
                None,
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in event.items():
                    yield f"event: node_complete\ndata: {node_name}\n\n"
                    yield f"data: {node_output}\n\n"

            yield "event: completed\ndata: done\n\n"

        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/history",
    response_model=SuccessResponse[ReportHistoryListResponse],
    summary="研报历史列表",
)
async def list_report_history(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    history_status: ReportHistoryStatus | None = Query(
        default=None,
        alias="status",
        description="按状态筛选",
    ),
    keyword: str | None = Query(default=None, description="按 topic / user_query 模糊搜索"),
) -> SuccessResponse[ReportHistoryListResponse]:
    """分页查询当前用户的研报历史。"""
    total, rows = await list_report_histories_owned(
        session,
        owner_user_id=current_user.id,
        page=page,
        page_size=page_size,
        status=history_status,
        keyword=keyword,
    )
    payload = ReportHistoryListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[to_history_list_item(row) for row in rows],
    )
    return ok(payload, message="查询成功")


@router.get(
    "/history/{thread_id}",
    response_model=SuccessResponse[ReportHistoryDetail],
    summary="研报历史详情",
)
async def get_report_history(
    thread_id: str,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[ReportHistoryDetail]:
    """查询当前用户的研报历史详情。"""
    row = await get_report_history_owned(
        session,
        owner_user_id=current_user.id,
        thread_id=thread_id,
    )
    if row is None:
        body = fail(
            code=BizCode.NOT_FOUND,
            message="研报历史不存在",
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=body.model_dump(),
        )
    config = _build_report_config(thread_id=thread_id, user_id=current_user.id)
    state = await report_graph.aget_state(config)
    state_values = safe_serialize(state.values) if state and state.values else None
    current_node = next(iter(state.next), None) if state and state.next else row.current_node
    interrupt_data = await interrupt_payload(report_graph, config) if state and state.next else row.interrupt_payload
    return ok(
        to_workspace_detail(
            row=row,
            state_values=state_values,
            current_node=current_node,
            interrupt_payload=interrupt_data if isinstance(interrupt_data, dict) else None,
        ),
        message="查询成功",
    )


@router.delete(
    "/history/{thread_id}",
    response_model=SuccessResponse,
    summary="删除研报历史",
)
async def delete_report_history(
    thread_id: str,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse:
    """删除当前用户的指定研报历史记录。"""
    await delete_report_history_owned(
        session,
        owner_user_id=current_user.id,
        thread_id=thread_id,
    )
    return ok(message="删除成功")
