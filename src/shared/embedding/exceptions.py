"""嵌入配置相关异常."""


class EmbeddingConfigurationError(RuntimeError):
    """无法从当前策略解析出合法嵌入配置（如未配置 vendor/model）。"""
