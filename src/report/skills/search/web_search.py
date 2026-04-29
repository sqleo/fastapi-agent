from typing import List
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill, SkillMetadata
from report.tool.web_search import web_search

class WebSearchSkill(BaseSkill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="web_search",
            display_name="网络搜索",
            description="使用网络搜索工具进行查询，获取最新信息。"
        )

    def get_tools(self) -> List[BaseTool]:
        return [web_search]
