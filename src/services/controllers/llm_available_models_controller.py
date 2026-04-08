"""已安装且已配置厂商下的可选模型列表（供全局默认模型下拉）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from services.controllers.llm_vendor_model_catalog import (
    VENDOR_MODEL_CATALOG,
    capabilities_for_extra_model,
)
from services.controllers.llm_vendor_seed import (
    get_vendor_template,
    is_vendor_fully_configured,
    list_installed_vendors_for_user,
)

# 与前端筛选标签一致（大小写不敏感）
_CANON_CAP = {
    "llm": "LLM",
    "embedding": "Embedding",
    "rerank": "Rerank",
    "vlm": "VLM",
    "asr": "ASR",
    "tts": "TTS",
    "moderation": "Moderation",
}


def normalize_capability(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    k = raw.strip().lower()
    return _CANON_CAP.get(k, raw.strip())


def _make_value(vendor_id: int, model_id: str) -> str:
    """下拉 value：vendor_id 与 model_id 组合（model_id 内勿含 |）。"""
    return f"{vendor_id}|{model_id}"


def _iter_options_for_vendor(
    vendor: LlmVendorModel,
    capability: str,
) -> list[dict]:
    """单个已配置厂商在指定能力下的可选模型项。"""
    template = get_vendor_template(vendor.code)
    if template is None:
        return []
    caps = template.get("capabilities") or []
    if capability not in caps:
        return []

    out: list[dict] = []
    code = vendor.code
    name = vendor.name

    # 1) 静态目录
    for row in VENDOR_MODEL_CATALOG.get(code, []):
        mids = row.get("model_id")
        if not mids:
            continue
        row_caps = row.get("capabilities") or []
        if capability not in row_caps:
            continue
        mid = str(mids)
        label = row.get("label") or mid
        out.append(
            {
                "vendor_id": vendor.id,
                "vendor_code": code,
                "vendor_name": name,
                "model_id": mid,
                "label": f"{name} · {label}",
                "capability": capability,
                "value": _make_value(vendor.id, mid),
            }
        )

    # 2) 厂商私有 extra 中单模型（百度/腾讯/火山等）
    extra = dict(vendor.extra_config or {})
    model_name = extra.get("model_name")
    if model_name and str(model_name).strip():
        mid = str(model_name).strip()
        inferred = capabilities_for_extra_model(code, extra)
        if not inferred:
            inferred = caps
        if capability in inferred:
            out.append(
                {
                    "vendor_id": vendor.id,
                    "vendor_code": code,
                    "vendor_name": name,
                    "model_id": mid,
                    "label": f"{name} · {mid}",
                    "capability": capability,
                    "value": _make_value(vendor.id, mid),
                }
            )

    # 去重（同 vendor + model_id）
    seen: set[tuple[int, str]] = set()
    unique: list[dict] = []
    for item in out:
        k = (item["vendor_id"], item["model_id"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    return unique


async def list_available_models_for_user(
    session: AsyncSession,
    *,
    owner_user_id: int,
    capability: str | None,
) -> list[dict]:
    """返回当前用户已安装且模板必填已齐的厂商下、指定能力的可选模型列表。"""
    cap = normalize_capability(capability)
    vendors = await list_installed_vendors_for_user(session, owner_user_id=owner_user_id)
    result: list[dict] = []
    for v in vendors:
        if not is_vendor_fully_configured(v):
            continue
        if cap is None:
            template = get_vendor_template(v.code)
            if not template:
                continue
            for c in template.get("capabilities") or []:
                result.extend(_iter_options_for_vendor(v, c))
        else:
            result.extend(_iter_options_for_vendor(v, cap))
    return result
