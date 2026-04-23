import json
from typing import Any


def sse_json(obj: dict[str, Any]) -> str:
    """将对象转换为 SSE 格式的 JSON 字符串"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

def safe_serialize(obj):
    """安全地将对象转换为可 JSON 序列化的形式，支持 Pydantic 模型和常见数据结构。"""
    if obj is None:
        return None
    
    # 针对 Pydantic v2 模型
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode='json')
        except Exception:
            # 回退到普通 dump
            return obj.model_dump()
            
    # 针对 Pydantic v1 模型
    if hasattr(obj, "dict"):
        return obj.dict()
    
    if isinstance(obj, (list, tuple, set)):
        return [safe_serialize(i) for i in obj]
    
    if isinstance(obj, dict):
        return {str(k): safe_serialize(v) for k, v in obj.items()}
    
    # 基本类型直接返回
    if isinstance(obj, (str, int, float, bool)):
        return obj
        
    # 其他类型尝试转字符串
    try:
        json.dumps(obj)
        return obj
    except (TypeError, OverflowError):
        return str(obj)