import frontmatter
import importlib
from typing import List
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill, SkillMetadata

class MdSkill(BaseSkill):
    """通过 Markdown (带 YAML Front Matter) 配置文件定义的 Skill"""

    def __init__(self, md_path: str):
        self.md_path = md_path
        self._post = frontmatter.load(md_path)

    def metadata(self) -> SkillMetadata:
        # 优先使用 Front Matter 的 description，如果没有则使用 MD 的正文
        description = self._post.get("description")
        if not description and self._post.content:
            description = self._post.content.strip()
            
        return SkillMetadata(
            name=self._post["name"],
            display_name=self._post["display_name"],
            description=description or "无描述",
            enabled=self._post.get("enabled", True),
        )

    def get_tools(self) -> List[BaseTool]:
        tools = []
        for import_path in self._post.get("tools", []):
            try:
                mod_name, obj_name = import_path.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                tool_obj = getattr(mod, obj_name)
                tools.append(tool_obj)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to load tool {import_path} from MD {self.md_path}: {e}"
                )
        return tools
