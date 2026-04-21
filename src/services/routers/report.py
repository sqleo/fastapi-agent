"""Report Agent API 路由
通过 HTTP 接口暴露报告生成能力，支持中断、恢复、回滚等操作
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.types import Command, Interrupt
from pydantic import BaseModel, Field

from report.graph import build_report_graph
from utils.auth_deps import get_current_user
from utils.response import SuccessResponse, ok, fail, BizCode

logger = logging.getLogger("services.routers.report")

router = APIRouter(tags=["Report"], prefix="/report")

report_graph = build_report_graph()


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
    config = {
        "configurable": {
            "thread_id": tid,
            "user_id": user.id,
            "graph": report_graph,
        }
    }

    async def event_generator():
        # 节点友好名称映射
        node_names = {
            "intent": "解析用户意图",
            "researcher": "知识库调研",
            "outliner": "生成报告大纲",
            "planner": "规划写作路线",
            "writer": "撰写报告内容",
            "human_review": "等待人工审核",
        }
        
        try:
            # 开始事件
            yield f"data: {{\"type\": \"start\", \"thread_id\": \"{tid}\"}}\n\n"
            
            # 流式执行整个 graph
            async for event in report_graph.astream(
                {"user_query": request.user_query},
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in event.items():
                    # 节点开始消息
                    node_title = node_names.get(node_name, node_name)
                    yield f"data: {{\"type\": \"message\", \"message\": \"🔄 开始{node_title}\"}}\n\n"
                    
                    # 节点数据
                    yield f"data: {{\"type\": \"node_data\", \"node\": \"{node_name}\", \"data\": {node_output}}}\n\n"
                    
                    # 节点完成消息
                    yield f"data: {{\"type\": \"message\", \"message\": \"✅ {node_title}完成\"}}\n\n"

            # 执行完成
            yield f"data: {{\"type\": \"done\", \"thread_id\": \"{tid}\"}}\n\n"

        except Interrupt as e:
            yield f"data: {{\"type\": \"interrupted\", \"node\": \"human_review\", \"payload\": {e.value}}}\n\n"
            
        except Exception as e:
            logger.exception("报告生成失败")
            yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/resume", response_model=SuccessResponse[GenerateReportResponse])
async def resume_report(
    request: ResumeReportRequest,
    user = Depends(get_current_user),
):
    user_id: int = user.id
    """恢复被中断的报告任务"""
    config = {
        "configurable": {
            "thread_id": request.thread_id,
            "user_id": user_id,
            "graph": report_graph,
        }
    }

    # 验证状态是否存在
    state = await report_graph.aget_state(config)
    if state is None:
        body = fail(
            code=BizCode.NOT_FOUND,
            message=f"会话 {request.thread_id} 不存在",
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=body.model_dump(),
        )

    try:
        resume_data = {
            "action": request.action,
            **(request.updates or {}),
        }

        result = await report_graph.ainvoke(
            Command(resume=resume_data),
            config=config,
        )

        return ok(
            data=GenerateReportResponse(
                thread_id=request.thread_id,
                status="completed",
                result=result,
            )
        )

    except Interrupt as e:
        return ok(
            data=GenerateReportResponse(
                thread_id=request.thread_id,
                status="interrupted",
                interrupt_payload=e.value,
            )
        )

    except Exception as e:
        logger.exception("恢复报告失败")
        body = fail(
            code=BizCode.INTERNAL_ERROR,
            message=f"恢复报告失败: {str(e)}",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body.model_dump(),
        )


@router.get("/status/{thread_id}", response_model=SuccessResponse[ReportStatusResponse])
async def get_report_status(
    thread_id: str,
    user = Depends(get_current_user),
):
    user_id: int = user.id
    """查询报告生成状态"""
    config = {
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
            )
        )

    if not state.next:
        status = "completed"
    else:
        status = "interrupted" if "human_review" in state.next else "running"

    return ok(
        data=ReportStatusResponse(
            thread_id=thread_id,
            status=status,
            current_node=state.next,
            state=state.values,
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
    from report.control.time_travel import rollback_to

    config = {
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
    config = {
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

        except Interrupt:
            yield "event: interrupted\ndata: human_review\n\n"

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