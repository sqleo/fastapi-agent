from typing import Any
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command


async def rollback_to( 
    config: RunnableConfig,    
    target_node: str,
    extra_updates: dict[str, Any] | None = None,) -> Command:
    """
        从 Checkpointer 历史里找到 target_node 执行前的快照，
        用那个快照的 state 覆盖当前 state，再跳回去重跑。
        Args:
            graph:         编译好的 LangGraph 实例
            thread_id:     当前会话 ID
            target_node:   要回滚到的节点名
            extra_updates: 在快照基础上额外覆盖的字段（如新的 user_query）
        
        Raises:
            ValueError: 找不到目标节点的历史快照时
    """
    graph = config["configurable"]["graph"]
    thread_id = config["configurable"]["thread_id"]
    cfg = {"configurable": {"thread_id": thread_id}}
    target_snapshot = None
    # 从历史快照里找到目标节点执行前的状态
    async for snapshot in graph.aget_state_history(cfg):
        if snapshot.next and target_node in snapshot.next:
            target_snapshot = snapshot
            break

    if target_snapshot is None:
        raise ValueError(f"找不到节点 {target_node!r} 执行前的快照")

    update = {**target_snapshot.values, **(extra_updates or {})}
    return Command(goto=target_node, update=update)
