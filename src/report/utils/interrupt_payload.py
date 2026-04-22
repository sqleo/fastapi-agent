from typing import Optional


async def interrupt_payload(graph, config) -> Optional[dict]:
    """
    解析 interrupt 中自定义的中断数据，返回给前端。
    约定：
      - 如果 state_snapshot.next 存在且包含 'human_review'，则查找自定义中断数据。
      - 优先返回 state_snapshot.values['interrupt_payload']，否则返回 None。
    """
    state_snapshot = await graph.aget_state(config)
    has_next = len(state_snapshot.next) > 0
    is_human_required = any(len(task.interrupts) > 0 for task in state_snapshot.tasks)
    if has_next and is_human_required:
        # 确定是人机交互中断
        interrupt_obj = state_snapshot.tasks[0].interrupts[0]
        custom_value = interrupt_obj.value
        
        return {
            "type": "interrupt",
            "message": custom_value.get("message", "需要用户输入"),
            "data": custom_value.get("data", {}),
            "options": custom_value.get("options", []),
            "metadata": custom_value.get("metadata", {}),
       }
    elif has_next:
        # 可能是因为 recursion_limit 到了或者其他异常情况导致的暂停
        return {
            "type": "error",
            "message": "生成过程中发生了意外中断，请稍后重试 ",
            "options": ["retry"],
        }