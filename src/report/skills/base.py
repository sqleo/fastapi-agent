from abc import ABC, abstractmethod
from typing import Any, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel

class SkillMetadata(BaseModel):
    """Skill 元数据"""
    name: str                    # 唯一标识: "web_search", "kb_rag", etc.
    display_name: str            # 展示名: "网络搜索"
    description: str             # 描述: 供 LLM 选择用
    enabled: bool = True         # 是否启用

class BaseSkill(ABC):
    """Skill 基类"""

    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """返回 Skill 元数据"""
        pass

    @abstractmethod
    def get_tools(self) -> List[BaseTool]:
        """返回该 Skill 提供的 Tool 列表"""
        pass

