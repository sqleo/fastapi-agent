"""Report Agent API 路由
通过 HTTP 接口暴露报告生成能力，支持中断、恢复、回滚等操作
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.graph.state import RunnableConfig
from langgraph.types import Command, Interrupt
from pydantic import BaseModel, Field
from pydantic_core import to_json

from report.graph import build_report_graph
from report.utils.interrupt_payload import interrupt_payload
from utils.auth_deps import get_current_user
from utils.json import safe_serialize, sse_json
from utils.report_sse import EventHandler, EventPayload, iter_report_sse_events
from utils.response import SuccessResponse, ok, fail, BizCode

logger = logging.getLogger("services.routers.report")

router = APIRouter(tags=["Report"], prefix="/report")

report_graph = build_report_graph()


def _identity_event_handler(payload: EventPayload) -> EventPayload:
    return payload


def _custom_event_unwrap_handler(payload: EventPayload) -> EventPayload | None:
    """将 custom 事件解包为业务事件类型（phase/task/metric/artifact）。"""
    event_name = payload.get("event_name")
    data = payload.get("data")
    if not isinstance(event_name, str) or not isinstance(data, dict):
        return None
    return {
        "type": event_name,
        "node": payload.get("node"),
        **data,
    }


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
    thread_id: Optional[str] = Field(None, description="可选，指定会话 ID 用于恢复")


class GenerateReportResponse(BaseModel):
    """生成报告响应"""
    thread_id: str = Field(..., description="会话 ID，用于后续查询状态、恢复执行")
    status: str = Field(..., description="状态: running / interrupted / completed")
    current_node: Optional[str] = Field(None, description="当前执行到的节点")
    interrupt_payload: Optional[dict[str, Any]] = Field(None, description="中断时的 payload 数据")
    result: Optional[dict[str, Any]] = Field(None, description="完成时的结果")


class ResumeReportRequest(BaseModel):
    """恢复中断的报告任务"""
    thread_id: str = Field(..., description="会话 ID")
    action: str = Field(..., description="用户选择的操作: confirm / revise / replan")
    updates: Optional[dict[str, Any]] = Field(None, description="额外更新数据，如修改后的大纲")
    metadata: Optional[dict[str, Any]] = Field(None, description="元数据，如节点名称")

class ReportStatusResponse(BaseModel):
    """报告状态查询响应"""
    thread_id: str = Field(..., description="会话 ID")
    status: str = Field(..., description="状态: running / interrupted / completed / not_found")
    current_node: Optional[list[str]] = Field(None, description="待执行节点")
    state: Optional[dict[str, Any]] = Field(None, description="当前完整状态")


@router.post("/generate")
async def generate_report(
    request: GenerateReportRequest,
    user = Depends(get_current_user),
):
    """创建报告生成任务（流式输出）
    
    Server-Sent Events 流式输出每个节点执行状态
    """
    tid = request.thread_id or str(uuid4())
    config: RunnableConfig = {
        "configurable": {
            "thread_id": tid,
            "user_id": user.id,
            "graph": report_graph,
        }
    }

    async def event_generator():
        try:
            yield sse_json({"type": "start", "thread_id": tid})
            events = report_graph.astream_events(
                {"user_query": request.user_query},
                config=config,
                version="v2",
            )
            generate_handlers: dict[str, EventHandler] = {
                "message": _build_message_filter_handler({"writer"}),
                "custom": _custom_event_unwrap_handler,
            }
            async for sse_event in iter_report_sse_events(
                events,
                handlers=generate_handlers,
                default_handler=_identity_event_handler,
            ):
                yield sse_event
            interrupt_data = await interrupt_payload(report_graph, config)
            if interrupt_data:
                yield sse_json({
                    "type": "interrupted",
                    "thread_id": tid,
                    "payload": interrupt_data, # 包装在 payload 里方便前端解析
                })
            else:
                yield sse_json({"type": "done", "thread_id": tid})

        except Exception as e:
            logger.exception("报告生成失败")
            yield sse_json({"type": "error", "message": str(e)})

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
    user = Depends(get_current_user),
):
    """恢复被中断的报告任务（流式输出）"""
    tid = request.thread_id
    config: RunnableConfig = {
        "configurable": {
            "thread_id": tid,
            "user_id": user.id,
            "graph": report_graph,
        }
    }

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

    async def event_generator():
        try:
            yield sse_json({"type": "start", "thread_id": tid})
            
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
                "message": _build_message_filter_handler({"writer"}),
                "custom": _custom_event_unwrap_handler,
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
                yield sse_json({
                    "type": "interrupted",
                    "thread_id": tid,
                    "payload": interrupt_data,
                })
            else:
                yield sse_json({"type": "done", "thread_id": tid})

        except Exception as e:
            logger.exception("恢复报告失败")
            yield sse_json({"type": "error", "message": str(e)})

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
    user = Depends(get_current_user),
):
    user_id: int = user.id
    """查询报告生成状态"""
    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "graph": report_graph,
        }
    }

    state = await report_graph.aget_state(config)
    if state is None or state.values is None:
        return ok(
            data=ReportStatusResponse(
                thread_id=thread_id,
                status="not_found",
                current_node=None,
                state=None,
            )
        )

    if not state.next:
        status = "completed"
    else:
        status = "interrupted" if "human_review" in state.next else "running"

    # 安全序列化 state，避免 Pydantic 序列化警告
    serialized_state = safe_serialize(state.values) if state.values else None

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
    user = Depends(get_current_user),
):
    user_id: int = user.id
    """回滚报告到指定节点"""
    from infra.langgraph.control import rollback_to

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "graph": report_graph,
        }
    }

    try:
        command = await rollback_to(
            config=config,
            target_node=target_node,
        )

        # 执行回滚
        result = await report_graph.ainvoke(command, config=config)

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
    user = Depends(get_current_user),
):
    user_id: int = user.id
    """流式获取报告生成进度

    Server-Sent Events 流式输出，每个事件为节点执行状态
    """
    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "graph": report_graph,
        }
    }

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