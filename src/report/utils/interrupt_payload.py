import logging
from typing import Optional

from infra.langgraph.control.interrupt import extract_interrupt_payload_from_state

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
        
        payload = extract_interrupt_payload_from_state(state_snapshot)
        if payload:
            return payload

        # 仍有 next 但未提取到 interrupt value，给出可定位信息
        return {
            "type": "error",
            "message": f"生成过程中发生了意外中断，next = {list(state_snapshot.next or [])}",
            "options": ["retry"],
        }
        
    except Exception as e:
        logger.exception("解析中断数据时发生错误: %s", e)
        return {
            "type": "error",
            "message": f"获取中断信息失败: {str(e)}",
            "options": ["retry"],
        }
