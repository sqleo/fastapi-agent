from typing import Any

from langgraph.types import Command, interrupt
from infra.langgraph.control import build_payload, parse_decision, rollback_to
from report.state import ReportState
from langchain_core.runnables import RunnableConfig

_ALLOWED = ["confirm", "revise", "replan"]


def _has_meaningful_value(value: Any) -> bool:
    """仅在用户确实提供了有效修改值时才覆盖状态。"""
    if value is None:
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True

async def human_review_node(
    state: ReportState, config: RunnableConfig
) -> dict[str, Any] | Command:
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
            config=config,  
            target_node="planner",
            extra_updates={"user_query": decision.updates["new_query"]}
            if decision.updates.get("new_query") else None,
        )
    result: dict = {"human_decision": decision.payload}
    
    # 提取更新内容 (兼容直接传值或嵌套在 updates 键中的结构)
    updates = decision.updates.get("updates", decision.updates)
    
    if decision.action == "revise" and _has_meaningful_value(updates.get("outline")):
        result["outline"] = updates["outline"]
    
    return result


_ALLOWED_INTENT = ["confirm", "revise"]

async def human_review_intent_node(state: ReportState, config: RunnableConfig) -> dict:
    """人工审核节点，供用户对生成的意图进行确认和修改"""
    payload = build_payload(
        message="请确认报告意图",
        data={"intent": state.intent.model_dump() if state.intent else {}},
        options=_ALLOWED_INTENT,
        metadata={"node_name": "human_review_intent"},
    )
    raw = interrupt(payload.model_dump())
    decision = parse_decision(raw, allowed_actions=_ALLOWED_INTENT)
    result: dict = {"human_decision": decision.payload}
    
    # 提取更新内容
    updates = decision.updates.get("updates", decision.updates)
    
    if decision.action == "revise" and _has_meaningful_value(updates.get("intent")):
        result["intent"] = updates["intent"]
        
    return result