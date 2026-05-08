import asyncio
from src.report.graph import build_report_graph
import uuid

async def main():
    try:
        graph = build_report_graph()
        thread_id = str(uuid.uuid4())
        print("Graph built. Invoking...")
        result = await graph.ainvoke(
            {"user_query": "Test Topic"},
            config={"configurable": {"thread_id": thread_id}}
        )
        print("Success:", result)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
