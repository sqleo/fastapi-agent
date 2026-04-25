
from pathlib import Path
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from report.nodes.human_review import human_review_node, human_review_intent_node
from report.nodes.intent import intent_node
from report.nodes.outliner import outliner_node
from report.nodes.planner import planner_node
from report.nodes.researcher import researcher_node
from report.nodes.writer import writer_node
from report.state import ReportState
from report.memory.checkpoint import get_report_checkpoint_saver
from report.config import ROUTING_TABLE


async def route_after_review(state: ReportState) -> str:
    """根据人工审核结果路由 (大纲阶段)"""
    decision = state.human_decision or {}
    action = decision.get("action", "confirm")
    node_name = (decision.get("metadata") or {}).get("node_name", "planner")
    stage_config = ROUTING_TABLE.get(node_name)

    if not stage_config:
        return node_name
    return stage_config.get(action, stage_config.get("__default__", "__default__"))
 


def build_report_graph() -> CompiledStateGraph[ReportState]:
    graph = StateGraph(ReportState)
    graph.add_node("intent", intent_node)
    graph.add_node("human_review_intent", human_review_intent_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("outliner", outliner_node)
    graph.add_node("writer",  writer_node)

    # 注册边
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "human_review_intent")
    
    # 意图审核后的路由
    graph.add_conditional_edges(
        "human_review_intent",
        route_after_review,
    )
    # 2026年上海前端就业环境
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "outliner")
    graph.add_edge("outliner", "human_review")
    
    # 大纲审核后的路由
    graph.add_conditional_edges(
        "human_review",
        route_after_review
    )
    
    graph.add_edge("writer", END)
    
    return graph.compile(
        name="report_graph",
        checkpointer=get_report_checkpoint_saver(),
    )
