from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field
from report.llm import create_llm
from report.state import PlannerTask, ReportState
from report.utils.emit_trace_event import emit_trace_event


class ResultPlannerTask(BaseModel):
    tasks: list[PlannerTask] = Field(..., description="调研任务列表")

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个调研规划专家。根据用户意图，生成调研计划。\n"
        "每条任务包含：task_id (字符串格式，如 't1', 't2'), topic_key (调研主题标识，如 market_size / policy / competition / technology), query, tool (kb_search/web_search/data_query), priority (1-3)。\n"
        "规则：\n"
        "- 每个关键维度至少 1 条调研任务\n"
        "- 优先使用 kb_search（知识库），不足时用 web_search（网络搜索）\n"
        "- 涉及数据分析的用 data_query（数据查询）\n"
        "- 总任务数控制在 5-10 条\n"
        "保持 query 简洁有针对性。\n"
        "请严格以 JSON 格式输出。"
    )),
    ("human", "用户需求：{user_query}\n结构化意图：{intent}"),
])


def format_for_plan(state: ReportState) -> dict:
    """RunnableLambda: 格式化输入"""
    return {
        "user_query": state.user_query,
        "intent": str(state.intent),
    }



async def planner_node(state: ReportState) -> dict:
    """任务规划节点"""
    emit_trace_event(
        "stage",
        {
            "phase": "planning",
            "status": "running",
            "message": "正在生成调研规划",
        },
    )

    try:
        llm = await create_llm("llm")
        chain = (
            RunnableLambda(format_for_plan)
            | chat_prompt
            | llm.bind(max_tokens=4096).with_structured_output(ResultPlannerTask, method="json_mode")
        )
        result: ResultPlannerTask = await chain.ainvoke(state)
    except Exception as e:
        raise

    research_plan = [t.model_dump() for t in result.tasks]

    return {"research_plan": research_plan}
