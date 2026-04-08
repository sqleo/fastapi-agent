"""LLM 厂商市场与我的厂商相关 Schema。"""

from pydantic import BaseModel, Field


class VendorMarketplaceItem(BaseModel):
    """平台厂商市场项（未安装前展示）。"""

    code: str = Field(..., description="厂商代码")
    name: str = Field(..., description="厂商名称")
    description: str | None = Field(default=None, description="厂商说明")
    website_url: str | None = Field(default=None, description="官网地址")
    doc_url: str | None = Field(default=None, description="文档地址")
    logo_url: str | None = Field(default=None, description="Logo 地址")
    base_url: str | None = Field(default=None, description="默认 API Base URL")
    default_model_type: str | None = Field(default=None, description="默认模型类型")
    capabilities: list[str] = Field(default_factory=list, description="支持能力标签")
    config_schema: dict | None = Field(default=None, description="厂商动态配置字段定义")
    status: int = Field(default=1, description="状态：1 启用，0 禁用")


class InstalledVendorItem(BaseModel):
    """用户已安装厂商项（可进入配置）。"""

    id: int = Field(..., description="已安装厂商记录 id")
    code: str = Field(..., description="厂商代码")
    name: str = Field(..., description="厂商名称")
    description: str | None = Field(default=None, description="厂商说明")
    website_url: str | None = Field(default=None, description="官网地址")
    doc_url: str | None = Field(default=None, description="文档地址")
    logo_url: str | None = Field(default=None, description="Logo 地址")
    base_url: str | None = Field(default=None, description="厂商基础 URL")
    default_model_type: str | None = Field(default=None, description="默认模型类型")
    capabilities: list[str] = Field(default_factory=list, description="支持能力标签")
    config_schema: dict | None = Field(default=None, description="厂商动态配置字段定义")
    extra_config: dict | None = Field(default=None, description="厂商私有配置数据")
    status: int = Field(..., description="状态：1 启用，0 禁用")


class VendorUpdateRequest(BaseModel):
    """更新已安装厂商请求体（厂商级配置）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100, description="展示名称")
    description: str | None = Field(default=None, description="厂商说明")
    website_url: str | None = Field(default=None, max_length=255, description="官网地址")
    doc_url: str | None = Field(default=None, max_length=255, description="文档地址")
    logo_url: str | None = Field(default=None, max_length=255, description="Logo 地址")
    base_url: str | None = Field(default=None, max_length=255, description="厂商基础 URL")
    api_key: str | None = Field(default=None, max_length=512, description="厂商通用 API Key")
    api_secret: str | None = Field(default=None, max_length=512, description="厂商通用 API Secret")
    organization: str | None = Field(default=None, max_length=255, description="厂商组织信息")
    default_model_type: str | None = Field(default=None, max_length=50, description="默认模型类型")
    extra_config: dict | None = Field(default=None, description="厂商私有字段配置")
    status: int | None = Field(default=None, description="状态：1 启用，0 禁用")

