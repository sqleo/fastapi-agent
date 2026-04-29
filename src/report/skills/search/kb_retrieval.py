from typing import List
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill, SkillMetadata
from report.tool.kb_search import kb_search

class KBRetrievalSkill(BaseSkill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="kb_search",
            display_name="知识库检索",
            description="从内部知识库中检索相关文档和信息。"
        )

    def get_tools(self) -> List[BaseTool]:
        return [kb_search]
