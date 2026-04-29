from typing import List
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill, SkillMetadata
from report.tool.data_query import data_query

class DataAnalysisSkill(BaseSkill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="data_query",
            display_name="数据查询",
            description="查询结构化数据，进行数据分析。"
        )

    def get_tools(self) -> List[BaseTool]:
        return [data_query]
