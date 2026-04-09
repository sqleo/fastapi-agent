"""服务注入型中间件。

这里存放强依赖外部服务（数据库、LLM 初始化、配置等）的中间件。
与纯技术型 middleware/ 区分开来，职责更清晰。
"""

from .llm import inject_llm_from_global_settings

__all__ = ["inject_llm_from_global_settings"]
