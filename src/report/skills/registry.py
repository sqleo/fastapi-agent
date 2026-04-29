from typing import Dict, List
from langchain_core.tools import BaseTool
from report.skills.base import BaseSkill

class SkillRegistry:
    """Skill 注册中心 — 管理所有已注册的 Skill"""

    _skills: Dict[str, BaseSkill] = {}
    _discovered = False

    @classmethod
    def register(cls, skill: BaseSkill) -> None:
        meta = skill.metadata()
        cls._skills[meta.name] = skill

    @classmethod
    def get(cls, name: str) -> BaseSkill | None:
        return cls._skills.get(name)

    @classmethod
    def list_enabled(cls) -> List[BaseSkill]:
        return [s for s in cls._skills.values() if s.metadata().enabled]

    @classmethod
    def get_all_tools(cls) -> List[BaseTool]:
        tools = []
        for skill in cls.list_enabled():
            tools.extend(skill.get_tools())
        return tools

    @classmethod
    def auto_discover(cls, package_path: str = "report.skills") -> None:
        """自动发现并注册所有继承自 BaseSkill 的插件"""
        if cls._discovered:
            return
        
        import importlib
        import pkgutil
        import inspect
        
        try:
            pkg = importlib.import_module(package_path)
            # walk_packages 可以递归扫描子文件夹
            for _, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                # 排除基础架构模块
                if module_name.split('.')[-1] in ("base", "registry", "yaml_skill", "md_skill"):
                    continue
                # 跳过单纯的包目录（__init__.py）
                if is_pkg:
                    continue
                    
                module = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                        # 避免重复注册相同的 Skill
                        skill_instance = obj()
                        meta_name = skill_instance.metadata().name
                        if meta_name not in cls._skills:
                            cls.register(skill_instance)
            
            # 扫描 YAML 文件
            from pathlib import Path
            from report.skills.yaml_skill import YamlSkill
            
            pkg_dir = Path(pkg.__path__[0])
            for yaml_file in pkg_dir.rglob("*.yaml"):
                try:
                    skill_instance = YamlSkill(str(yaml_file))
                    meta_name = skill_instance.metadata().name
                    if meta_name not in cls._skills:
                        cls.register(skill_instance)
                except Exception as yaml_e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to load YAML skill {yaml_file}: {yaml_e}")
            
            # 扫描 Markdown 文件
            from report.skills.md_skill import MdSkill
            for md_file in pkg_dir.rglob("*.md"):
                try:
                    skill_instance = MdSkill(str(md_file))
                    meta_name = skill_instance.metadata().name
                    if meta_name not in cls._skills:
                        cls.register(skill_instance)
                except Exception as md_e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to load MD skill {md_file}: {md_e}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Skill auto-discover failed: {e}")
            
        cls._discovered = True
