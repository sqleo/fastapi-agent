"""工具元数据装饰器。

因 LangChain Tool 多为 Pydantic 模型，无法动态挂属性，可见性记在模块内注册表（按 ``name``）。
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

# 显式标记为 False 的工具 name；未出现则视为对前端暴露（True）
_EXPOSE_TO_CLIENT_BY_NAME: dict[str, bool] = {}


def hidden_from_client(target: T) -> T:
    """不向 ``GET /agent/tools`` 暴露；仍参与 Agent，且与用户开关自动合并。

    写在 ``@tool`` **上方**::

        @hidden_from_client
        @tool
        def my_tool(...): ...

    第三方创建的 ``BaseTool``：``hidden_from_client(tool_obj)``。
    """
    name = getattr(target, "name", None)
    if name is not None:
        _EXPOSE_TO_CLIENT_BY_NAME[str(name)] = False
    return target


def is_exposed_to_client_named(tool_name: str) -> bool:
    """按工具名判断是否对前端展示（默认 True）。"""
    return _EXPOSE_TO_CLIENT_BY_NAME.get(tool_name, True)


def is_exposed_to_client(tool: object) -> bool:
    """按工具对象判断是否对前端展示。"""
    name = getattr(tool, "name", None)
    if name is None:
        return True
    return is_exposed_to_client_named(str(name))
