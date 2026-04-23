

import asyncio
from pathlib import Path
from langgraph.graph import END, START, StateGraph
from report.nodes.human_review import human_review_node
from report.nodes.intent import intent_node
from report.nodes.outliner import outliner_node
from report.nodes.planner import planner_node
from report.nodes.researcher import researcher_node
from report.nodes.writer import writer_node
from report.state import ReportState
from report.memory.checkpoint import get_report_checkpoint_saver


async def route_after_review(state: ReportState) -> str:
    """根据人工审核结果路由"""
    decision = state.human_decision or {}
    action = decision.get("action", "confirm")
    if action == "revise":
        # 用户修改了大纲，更新 outline 后重新走 outliner
        return "outliner"
    elif action == "replan":
        # 用户不满意，回滚到 planner 重新规划
        return "planner"
    else:
        # 默认确认，继续撰写
        return "writer"

def build_report_graph() -> StateGraph[ReportState]:
    graph = StateGraph(ReportState)
    # 注册节点和边
    graph.add_node("intent", intent_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("outliner", outliner_node)
    graph.add_node("writer",  writer_node)

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "outliner")
    graph.add_edge("outliner", "human_review")
    graph.add_conditional_edges(
            "human_review",
            route_after_review,
            {
                "writer": "writer",
                "outliner": "outliner",
                "planner": "planner",
            }
        )
    graph.add_edge("writer", END)
    return graph.compile(
        name="report_graph",
        checkpointer=get_report_checkpoint_saver(),
    )
