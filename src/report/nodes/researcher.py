import asyncio
from typing import cast

from report.llm import create_llm
from report.state import PlannerTask, ReportState, ResultTaskChunk
from report.tool.data_query import data_query
from report.tool.kb_search import kb_search
from report.tool.web_search import web_search
from report.utils.emit_trace_event import emit_trace_event
from langchain_core.prompts import ChatPromptTemplate

_summarize_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是信息提炼专家。请将以下调研原始内容压缩为 150 字以内的摘要。"
        "保留关键数据和核心观点，去除冗余。直接输出摘要文本，不要加标题或前缀。"
    )),
    ("human", "调研主题：{topic_key}\n\n原始内容：\n{raw_content}"),
])


tools_map = {tool.name: tool for tool in [web_search, kb_search, data_query]}

async def process_task(task: PlannerTask) -> ResultTaskChunk:
    task_id = task.task_id
    topic_key = task.topic_key
    query = task.query
    tool = task.tool
    emit_trace_event(
        "task",
        {
            "phase": "research",
            "status": "running",
            "task_id": task_id,
            "topic_key": topic_key,
            "tool": tool,
            "message": f"抓取: {query}",
        },
    )
    llm = await create_llm("llm")
    summarize_chain = _summarize_prompt | llm
    tool_fn = tools_map.get(tool, tools_map["web_search"])
    raw_result = await tool_fn.ainvoke({"query": query})
    summary_resp = await summarize_chain.ainvoke({
            "topic_key": topic_key or "-",
            "raw_content": raw_result,
        })
    summarized_content = summary_resp.content.strip()

    chunk = ResultTaskChunk(
        task_id=task_id,
        topic_key=topic_key,
        content=summarized_content,
        source=f"{tool}: {query}")
    emit_trace_event(
        "task",
        {
            "phase": "research",
            "status": "completed",
            "task_id": task_id,
            "topic_key": topic_key,
            "source": tool,
            "message": f"抓取完成: {query}",
        },
    )
    return chunk
    

async def researcher_node(state: ReportState) -> dict:
    """调研节点 - 根据 planner 的任务列表调用工具进行调研"""
    emit_trace_event(
        "phase",
        {
            "phase": "research",
            "status": "running",
            "message": "正在并行执行调研任务",
        },
    )
    research_chunks: list[dict] = []
    evidence_map: dict[str, list[str]] = {}
    plans = state.research_plan or []
    total = len(plans)
    if total == 0:
        emit_trace_event(
            "metric",
            {
                "phase": "research",
                "done": 0,
                "total": 0,
                "coverage": 0,
            },
        )
        return {
            "research_chunks": research_chunks,
            "evidence_map": evidence_map,
        }
    # 并行执行调研任务
    tasks = [process_task(task) for task in plans]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    done = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed_task = plans[i]
            emit_trace_event("task", {
                "task_id": failed_task.task_id,
                "topic_key": failed_task.topic_key,
                "tool": failed_task.tool,
                "message": f"抓取失败: {failed_task.query}",
            })
            continue
        chunk = cast(ResultTaskChunk, result)
        research_chunks.append(chunk.model_dump())
        if chunk.topic_key:
            if chunk.topic_key:
                evidence_map.setdefault(chunk.topic_key, []).append(chunk.source or "")
        done += 1
        emit_trace_event(
            "metric",
            {
                "phase": "research",
                "done": done,
                "total": total,
                "coverage": round((done / total) * 100, 2),
            },
        )
    emit_trace_event(
        "phase",
        {
            "phase": "research",
            "status": "completed",
            "message": "调研执行完成",
        },
    )
    return {
        "research_chunks": research_chunks,
        "evidence_map": evidence_map,
    }