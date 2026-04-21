from report.llm import create_llm
from report.state import ReportState, ResultTaskChunk
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


async def researcher_node(state: ReportState) -> dict:
    """调研节点 - 根据 planner 的任务列表调用工具进行调研"""
    emit_trace_event("researcher_node", {"description": "执行调研"})

    llm = await create_llm("llm")
    summarize_chain = _summarize_prompt | llm
    tools_map = {tool.name: tool for tool in [web_search, kb_search, data_query]}
    research_chunks: list[dict] = []
    evidence_map: dict[str, list[str]] = {}
    plans = state.research_plan or []
    for task in plans:
        tool_fn = tools_map.get(task.get("source"), tools_map["web_search"])
        # 调用工具
        raw_result = await tool_fn.ainvoke({"query": task.get("query", "")})
        # 立即摘要
        summary_resp = await summarize_chain.ainvoke({
            "topic_key": task.get("topic_key", "-"),
            "raw_content": raw_result,
        })
        summarized_content = summary_resp.content.strip()

        chunk = ResultTaskChunk(
            task_id=task.get("task_id"),
            topic_key=task.get("topic_key"),
            content=summarized_content,
            source=f"{task.get('source', '-')}: {task.get('query', '-')}")
        
        research_chunks.append(chunk.model_dump())
        if task.get("topic_key"):
            if task.get("topic_key") not in evidence_map:
                evidence_map[task.get("topic_key")] = []
            evidence_map[task.get("topic_key")].append(chunk.source)
        print(f"✅ 任务 {task.get('task_id')} 完成，结果片段: {chunk}")
    return {
        "research_chunks": research_chunks,
        "evidence_map": evidence_map,
    }
