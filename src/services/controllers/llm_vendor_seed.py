"""常见 LLM 厂商市场数据与安装逻辑。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmVendorModel import LlmModelType, LlmVendorModel


def _f(
    key: str,
    label: str,
    *,
    required: bool,
    storage: str = "extra",
    placeholder: str | None = None,
    field_type: str = "text",
) -> dict:
    return {
        "key": key,
        "label": label,
        "required": required,
        "storage": storage,  # column | extra
        "placeholder": placeholder,
        "field_type": field_type,
    }

# 常见厂商模板（平台市场数据，不含敏感信息与 owner_user_id）
COMMON_LLM_VENDORS: tuple[dict, ...] = (
    {
        "code": "openai",
        "name": "OpenAI",
        "description": "通用大模型服务，支持文本、多模态与 embedding。",
        "website_url": "https://openai.com",
        "doc_url": "https://platform.openai.com/docs",
        "base_url": "https://api.openai.com/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding", "Rerank", "VLM", "Moderation", "TTS", "ASR"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
                _f("organization", "Organization", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "anthropic",
        "name": "Anthropic Claude",
        "description": "Claude 系列模型，长上下文能力较强。",
        "website_url": "https://www.anthropic.com",
        "doc_url": "https://docs.anthropic.com",
        "base_url": "https://api.anthropic.com",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "VLM"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "google_gemini",
        "name": "Google Gemini",
        "description": "Google Gemini 系列，支持多模态。",
        "website_url": "https://ai.google.dev",
        "doc_url": "https://ai.google.dev/gemini-api/docs",
        "base_url": "https://generativelanguage.googleapis.com",
        "default_model_type": LlmModelType.MULTIMODAL.value,
        "capabilities": ["LLM", "VLM", "Embedding", "TTS", "ASR"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "deepseek",
        "name": "DeepSeek",
        "description": "DeepSeek Chat/Reasoner 模型服务。",
        "website_url": "https://www.deepseek.com",
        "doc_url": "https://api-docs.deepseek.com",
        "base_url": "https://api.deepseek.com",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "qwen",
        "name": "阿里云百炼 Qwen",
        "description": "阿里云通义千问服务，支持文本与多模态。",
        "website_url": "https://www.aliyun.com/product/bailian",
        "doc_url": "https://help.aliyun.com/zh/model-studio",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding", "Rerank", "TTS", "ASR", "Moderation"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "tencent_cloud",
        "name": "Tencent Cloud",
        "description": "腾讯云模型服务。",
        "website_url": "https://cloud.tencent.com",
        "doc_url": "https://cloud.tencent.com/document/product",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "TTS", "ASR"],
        "config_schema": {
            "fields": [
                _f("model_type", "模型类型", required=True),
                _f("model_name", "模型名称", required=True),
                _f("secret_id", "腾讯云 Secret ID", required=True, field_type="password"),
                _f("secret_key", "腾讯云 Secret Key", required=True, field_type="password"),
            ]
        },
        "status": 1,
    },
    {
        "code": "baidu_yiyan",
        "name": "BaiduYiyan",
        "description": "百度文心一言模型服务。",
        "website_url": "https://cloud.baidu.com",
        "doc_url": "https://cloud.baidu.com/doc/WENXINWORKSHOP",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding", "Rerank"],
        "config_schema": {
            "fields": [
                _f("model_type", "模型类型", required=True),
                _f("model_name", "模型名称", required=True),
                _f("api_key", "一言 API KEY", required=True, storage="column", field_type="password"),
                _f("api_secret", "一言 Secret KEY", required=True, storage="column", field_type="password"),
                _f("max_tokens", "最大 token 数", required=True),
            ]
        },
        "status": 1,
    },
    {
        "code": "volcengine",
        "name": "VolcEngine",
        "description": "火山引擎模型服务。",
        "website_url": "https://www.volcengine.com",
        "doc_url": "https://www.volcengine.com/docs/82379",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding", "Rerank", "TTS", "ASR", "VLM"],
        "config_schema": {
            "fields": [
                _f("model_type", "模型类型", required=True),
                _f("model_name", "模型名称", required=True),
                _f("endpoint_id", "模型 EndpointID", required=True),
                _f("api_key", "火山 ARK_API_KEY", required=True, storage="column", field_type="password"),
                _f("max_tokens", "最大 token 数", required=True),
            ]
        },
        "status": 1,
    },
    {
        "code": "zhipu",
        "name": "智谱 AI",
        "description": "GLM 系列模型服务。",
        "website_url": "https://www.zhipuai.cn",
        "doc_url": "https://open.bigmodel.cn/dev/api",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding", "VLM"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "moonshot",
        "name": "Moonshot Kimi",
        "description": "Kimi 模型服务，适合中文场景。",
        "website_url": "https://www.moonshot.cn",
        "doc_url": "https://platform.moonshot.cn/docs",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "VLM"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "baichuan",
        "name": "百川智能",
        "description": "Baichuan 模型开放平台。",
        "website_url": "https://www.baichuan-ai.com",
        "doc_url": "https://platform.baichuan-ai.com/docs",
        "base_url": "https://api.baichuan-ai.com/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "Embedding"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "minimax",
        "name": "MiniMax",
        "description": "MiniMax 模型服务，支持文本与语音等。",
        "website_url": "https://www.minimaxi.com",
        "doc_url": "https://platform.minimaxi.com/document",
        "base_url": "https://api.minimax.chat/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "TTS", "ASR"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("group_id", "Group ID", required=False),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "jina",
        "name": "Jina AI",
        "description": "Embedding / rerank 能力常用服务商。",
        "website_url": "https://jina.ai",
        "doc_url": "https://jina.ai/embeddings/",
        "base_url": "https://api.jina.ai/v1",
        "default_model_type": LlmModelType.EMBEDDING.value,
        "capabilities": ["Embedding", "Rerank"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "cohere",
        "name": "Cohere",
        "description": "提供 rerank 与文本模型能力。",
        "website_url": "https://cohere.com",
        "doc_url": "https://docs.cohere.com",
        "base_url": "https://api.cohere.com/v1",
        "default_model_type": LlmModelType.RERANK.value,
        "capabilities": ["LLM", "Embedding", "Rerank"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
            ]
        },
        "status": 1,
    },
    {
        "code": "openrouter",
        "name": "OpenRouter",
        "description": "多厂商聚合网关，便于快速切换模型。",
        "website_url": "https://openrouter.ai",
        "doc_url": "https://openrouter.ai/docs",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model_type": LlmModelType.CHAT.value,
        "capabilities": ["LLM", "VLM"],
        "config_schema": {
            "fields": [
                _f("api_key", "API-Key", required=True, storage="column", field_type="password"),
                _f("base_url", "Base-Url", required=False, storage="column"),
                _f("site_url", "Site URL", required=False),
                _f("site_name", "Site Name", required=False),
            ]
        },
        "status": 1,
    },
)

_COMMON_VENDOR_BY_CODE = {x["code"]: x for x in COMMON_LLM_VENDORS}


def list_vendor_marketplace() -> list[dict]:
    """返回平台可展示的厂商市场列表。"""
    out: list[dict] = []
    for item in COMMON_LLM_VENDORS:
        x = dict(item)
        x.setdefault("capabilities", [])
        x.setdefault("config_schema", {"fields": []})
        out.append(x)
    return out


def get_vendor_template(vendor_code: str) -> dict | None:
    """按厂商 code 获取模板。"""
    return _COMMON_VENDOR_BY_CODE.get(vendor_code)


def validate_vendor_patch_by_template(template: dict, merged_data: dict) -> None:
    """按厂商模板校验配置必填项。"""
    schema = template.get("config_schema") or {}
    fields: list[dict] = schema.get("fields") or []
    missing: list[str] = []
    for f in fields:
        if not f.get("required"):
            continue
        key = f["key"]
        storage = f.get("storage", "extra")
        if storage == "column":
            val = merged_data.get(key)
        else:
            val = (merged_data.get("extra_config") or {}).get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(key)
    if missing:
        raise ValueError(f"缺少必填配置项: {', '.join(missing)}")


def vendor_merged_config(vendor: LlmVendorModel) -> dict:
    """与 PATCH 校验一致的合并结构，用于判断是否已配齐必填项。"""
    return {
        "api_key": vendor.api_key,
        "api_secret": vendor.api_secret,
        "base_url": vendor.base_url,
        "organization": vendor.organization,
        "extra_config": dict(vendor.extra_config or {}),
    }


def is_vendor_fully_configured(vendor: LlmVendorModel) -> bool:
    """厂商模板必填项是否已全部填写（用于可选模型列表等）。"""
    template = get_vendor_template(vendor.code)
    if template is None:
        return False
    try:
        validate_vendor_patch_by_template(template, vendor_merged_config(vendor))
    except ValueError:
        return False
    return True


async def list_installed_vendors_for_user(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> list[LlmVendorModel]:
    """返回用户已安装的厂商列表。"""
    stmt = (
        select(LlmVendorModel)
        .where(LlmVendorModel.owner_user_id == owner_user_id)
        .order_by(LlmVendorModel.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def install_vendor_for_user(
    session: AsyncSession,
    *,
    owner_user_id: int,
    vendor_code: str,
) -> LlmVendorModel:
    """为用户安装一个厂商；已安装则返回现有记录。"""
    code = vendor_code.strip()
    template = get_vendor_template(code)
    if template is None:
        raise ValueError(f"不支持的厂商 code: {code}")

    existing_stmt = select(LlmVendorModel).where(
        LlmVendorModel.owner_user_id == owner_user_id,
        LlmVendorModel.code == code,
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    row = LlmVendorModel(
        owner_user_id=owner_user_id,
        code=template["code"],
        name=template["name"],
        description=template.get("description"),
        website_url=template.get("website_url"),
        doc_url=template.get("doc_url"),
        logo_url=template.get("logo_url"),
        base_url=template.get("base_url"),
        api_key=None,
        api_secret=None,
        organization=None,
        default_model_type=template.get("default_model_type"),
        status=template.get("status", 1),
        extra_config={},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row

