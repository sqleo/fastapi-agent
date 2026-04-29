from typing import List
import yaml
import importlib
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill, SkillMetadata

class YamlSkill(BaseSkill):
    """通过 YAML 配置文件定义的 Skill"""

    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path
        with open(yaml_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name=self._data["name"],
            display_name=self._data["display_name"],
            description=self._data["description"],
            enabled=self._data.get("enabled", True),
        )

    def get_tools(self) -> List[BaseTool]:
        tools = []
        for import_path in self._data.get("tools", []):
            try:
                mod_name, obj_name = import_path.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                tool_obj = getattr(mod, obj_name)
                tools.append(tool_obj)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to load tool {import_path} from YAML {self.yaml_path}: {e}"
                )
        return tools
