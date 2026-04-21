

import asyncio
from pathlib import Path
from langgraph.graph import END, START, StateGraph
from report.nodes.intent import intent_node
from report.nodes.outliner import outliner_node
from report.nodes.planner import planner_node
from report.nodes.researcher import researcher_node
from report.nodes.writer import writer_node
from report.state import ReportState


def build_report_graph() -> StateGraph[ReportState]:
    graph = StateGraph(ReportState)
    graph.add_node("intent", intent_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("outliner", outliner_node)
    graph.add_node("writer",  writer_node)
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "outliner")
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
    print("=== 开始流式生成 ===\n")

    # 用 updates 模式打印节点完成状态
    async for event in report_graph.astream(
        {"user_query": "2026年下半年中国股市分析报告，要求包含行业趋势、重点公司分析、投资建议等内容"},
        stream_mode="updates",
    ):
        for node_name, node_output in event.items():
            print(f"📍 节点完成: {node_name}")
            if "intent" in node_output:
                intent = node_output["intent"]
                print(f"   主题: {intent.get('topic', '-')}")
                print(f"   范围: {intent.get('scope', '-')}")
                print(f"   深度: {intent.get('depth', '-')}")
            if "outline" in node_output:
                print(f"   大纲: {len(node_output['outline'])} 个章节")
                for i, sec in enumerate(node_output["outline"][:3], 1):
                    print(f"      {i}. {sec.get('title', '-')}")
            if "draft" in node_output:
                print(f"   初稿: {len(node_output['draft'])} 字")
            print()

    print("=== 生成完成 ===")

if __name__ == "__main__":
    asyncio.run(main())