"""ingestion 流水线异常。"""


class IngestionError(Exception):
    """解析流水线基础错误。"""


class UnsupportedDocumentError(IngestionError):
    """当前扩展名未在工厂白名单内，或工程内未实现对应解析器。"""
