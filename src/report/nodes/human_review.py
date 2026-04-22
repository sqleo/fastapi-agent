from langgraph.types import interrupt
from report.control.interrupt import build_payload, parse_decision
from report.control.time_travel import rollback_to
from report.state import ReportState
from langchain_core.runnables import RunnableConfig

_ALLOWED = ["confirm", "revise", "replan"]

async def human_review_node(state: ReportState, config: RunnableConfig) -> dict:
    """人工审核节点，供用户对生成的大纲报告内容进行审核和修改。"""
    payload = build_payload(
        message="请确认报告大纲",
        data={"outline": state.outline or []},
        options=_ALLOWED,
        metadata={"node_name": "human_review"},
    )
    raw = interrupt(payload.model_dump())
    decision = parse_decision(raw, allowed_actions=_ALLOWED)
    # 如果用户选择重新规划（replan），则回滚到 planner 节点并重跑
    if decision.action == "replan":
        return await rollback_to(
            config=config,        # 直接透传，不需要自己解析
            target_node="planner",
            extra_updates={"user_query": decision.updates["new_query"]}
            if decision.updates.get("new_query") else None,
        )
    result: dict = {"human_decision": decision.payload}
    if decision.action == "revise" and "updated_outline" in decision.updates:
        result["outline"] = decision.updates["updated_outline"]
    return result
