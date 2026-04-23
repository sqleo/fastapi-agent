import logging
from typing import Any, Optional

logger = logging.getLogger("report.interrupt_payload")


async def interrupt_payload(graph, config) -> Optional[dict]:
    """
    解析 interrupt 中自定义的中断数据，返回给前端。
    约定：
      - 如果 state_snapshot.next 存在且包含 'human_review'，则查找自定义中断数据。
      - 优先返回 state_snapshot.values['interrupt_payload']，否则返回 None。
    """
    try:
        state_snapshot = await graph.aget_state(config)
        
        # 检查状态是否存在
        if state_snapshot is None:
            logger.warning("无法获取状态快照，thread_id 可能不存在")
            return {
                "type": "error",
                "message": "会话状态不存在，请重新生成报告",
                "options": ["retry"],
            }
        
        # 检查是否有待执行的节点
        has_next = state_snapshot.next is not None and len(state_snapshot.next) > 0
        
        if not has_next:
            # 没有待执行节点，说明流程已完成
            return None
        
        # 检查是否有人工审核节点
        if "human_review" in state_snapshot.next:
            # 尝试从 values 中获取中断数据
            values = state_snapshot.values or {}
            
            # 检查是否有中断 payload 在 values 中
            if "interrupt_payload" in values:
                payload = values["interrupt_payload"]
                return {
                    "type": "interrupt",
                    "message": payload.get("message", "需要用户输入"),
                    "data": payload.get("data", {}),
                    "options": payload.get("options", []),
                    "metadata": payload.get("metadata", {}),
                }
            
            # 尝试从 checkpoint 的 metadata 中获取中断信息
            # LangGraph 的中断信息通常存储在 channel 中
            return {
                "type": "interrupt",
                "message": "请确认报告大纲",
                "data": values.get("outline", []),
                "options": ["confirm", "revise", "replan"],
                "metadata": {"node_name": "human_review"},
            }
        
        # 其他情况，可能是 recursion_limit 或其他原因导致的暂停
        return {
            "type": "error",
            "message": "生成过程中发生了意外中断，请稍后重试",
            "options": ["retry"],
        }
        
    except Exception as e:
        logger.exception("解析中断数据时发生错误: %s", e)
        return {
            "type": "error",
            "message": f"获取中断信息失败: {str(e)}",
            "options": ["retry"],
        }
