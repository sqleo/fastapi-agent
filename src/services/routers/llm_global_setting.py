"""用户全局模型设置路由。"""

from fastapi import APIRouter, HTTPException, Query, status

from schemas.llm_global_setting_schema import (
    AvailableModelItem,
    LlmGlobalSettingCompletion,
    LlmGlobalSettingItem,
    LlmGlobalSettingUpdateRequest,
)
from services.controllers.llm_available_models_controller import (
    list_available_models_for_user,
    normalize_capability,
)
from services.controllers.llm_global_setting_controller import (
    get_global_setting_owned,
    update_global_setting_owned,
)
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/llm/settings", tags=["LLM Settings"])

_VALID_CAPS = frozenset(
    {"LLM", "Embedding", "Rerank", "VLM", "ASR", "TTS", "Moderation"},
)


def _to_item(x) -> LlmGlobalSettingItem:
    completion = LlmGlobalSettingCompletion(
        chat=bool(x.chat_vendor_id and x.chat_model),
        embedding=bool(x.embedding_vendor_id and x.embedding_model),
        multimodal=bool(x.multimodal_vendor_id and x.multimodal_model),
        rerank=bool(x.rerank_vendor_id and x.rerank_model),
        asr=bool(getattr(x, "asr_vendor_id", None) and getattr(x, "asr_model", None)),
        tts=bool(getattr(x, "tts_vendor_id", None) and getattr(x, "tts_model", None)),
    )
    return LlmGlobalSettingItem(
        owner_user_id=x.owner_user_id,
        chat_vendor_id=x.chat_vendor_id,
        chat_model=x.chat_model,
        embedding_vendor_id=x.embedding_vendor_id,
        embedding_model=x.embedding_model,
        multimodal_vendor_id=x.multimodal_vendor_id,
        multimodal_model=x.multimodal_model,
        rerank_vendor_id=x.rerank_vendor_id,
        rerank_model=x.rerank_model,
        asr_vendor_id=getattr(x, "asr_vendor_id", None),
        asr_model=getattr(x, "asr_model", None),
        tts_vendor_id=getattr(x, "tts_vendor_id", None),
        tts_model=getattr(x, "tts_model", None),
        completion=completion,
        is_complete=bool(completion.chat and completion.embedding),
    )


@router.get(
    "/available-models",
    response_model=SuccessResponse[list[AvailableModelItem]],
    summary="可选模型列表（已安装且已配置厂商）",
)
async def available_models(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    capability: str | None = Query(
        default=None,
        description="能力筛选：LLM / Embedding / Rerank / VLM / ASR / TTS / Moderation；不传则返回全部能力下的选项",
    ),
) -> SuccessResponse[list[AvailableModelItem]]:
    """供「设置默认模型」下拉里使用：仅包含模板必填已填的已安装厂商，且按能力过滤。"""
    cap: str | None = None
    if capability is not None and capability.strip():
        cap = normalize_capability(capability)
        if cap not in _VALID_CAPS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"不支持的 capability: {capability}，允许: {', '.join(sorted(_VALID_CAPS))}",
            )
    rows = await list_available_models_for_user(
        session,
        owner_user_id=current_user.id,
        capability=cap,
    )
    payload = [AvailableModelItem.model_validate(x) for x in rows]
    return ok(payload, message="查询成功")


@router.get(
    "/global",
    response_model=SuccessResponse[LlmGlobalSettingItem],
    summary="获取我的全局模型设置",
)
async def get_global_setting(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[LlmGlobalSettingItem]:
    row = await get_global_setting_owned(session, owner_user_id=current_user.id)
    return ok(_to_item(row), message="查询成功")


@router.patch(
    "/global",
    response_model=SuccessResponse[LlmGlobalSettingItem],
    summary="更新我的全局模型设置",
)
async def patch_global_setting(
    body: LlmGlobalSettingUpdateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[LlmGlobalSettingItem]:
    row = await update_global_setting_owned(
        session,
        owner_user_id=current_user.id,
        patch=body.model_dump(exclude_unset=True),
    )
    return ok(_to_item(row), message="更新成功")

