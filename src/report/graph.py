

import asyncio
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from report.nodes.intent import intent_node
from report.nodes.outliner import outliner_node
from report.nodes.writer import writer_node
from report.state import ReportState


def build_report_graph() -> StateGraph[ReportState]:
    graph = StateGraph(ReportState)
    graph.add_node("intent", intent_node)
    graph.add_node("outliner", outliner_node)
    graph.add_node("writer",  writer_node)
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "outliner")
    graph.add_edge("outliner", "writer")
    graph.add_edge("writer", END)
    return graph.compile(name="report_graph")


async def main():
    report_graph = build_report_graph()

    # 生成图片
    png_bytes = report_graph.get_graph().draw_mermaid_png()
    Path("report_graph.png").write_bytes(png_bytes)
    print("已生成: report_graph.png")

    # 运行图
    result = await report_graph.ainvoke({"user_query": "2025年中国汽车行业现状"})
    print(f"\n=== 结果 ===")
    print(f"意图: {result.get('intent')}\n")
    print(f"大纲: {result.get('outline')}\n")
    print(f"报告: {result.get('final_report', '')[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())