import logging
import os

import httpx
logger = logging.getLogger("report.graph")

# 阿里云百炼多模态生成原生接口
NATIVE_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
SUPPORTED_IMAGE_SIZES = {
    "2048*2048",
    "2688*1536",
    "1536*2688",
    "2368*1728",
    "1728*2368",
    # 兼容历史占位符尺寸，避免旧内容直接失败
    "1024*1024",
    "1024*768",
    "768*1024",
}

async def qwen_image_tool(prompt: str, size: str = "1024*1024") -> str:
    """
    通过原生 HTTP 调用 qwen-image，失败时返回空字符串而非抛异常。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        logger.error("环境变量 DASHSCOPE_API_KEY 未设置，跳过本次配图")
        return ""

    normalized_size = (size or "").strip()
    if normalized_size not in SUPPORTED_IMAGE_SIZES:
        logger.warning("不支持的图片尺寸 `%s`，已回退到 1024*1024", normalized_size)
        normalized_size = "1024*1024"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    json_data = {
        "model": "qwen-image-2.0-pro",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        { "text": prompt }
                    ]
                }
            ]
        },
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "size": normalized_size,
            "negative_prompt": "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，画面具有AI感。构图混乱。文字模糊，扭曲，拼写错误。"
        }
    }
    custom_limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    try:
        logger.info("发送生图请求: %s... 尺寸: %s", prompt[:30], normalized_size)
        async with httpx.AsyncClient(trust_env=False, limits=custom_limits, timeout=120.0) as client:
            response = await client.post(NATIVE_API_URL, headers=headers, json=json_data)

        if response.status_code != 200:
            error_payload = {}
            try:
                error_payload = response.json()
            except Exception:
                error_payload = {}

            if error_payload:
                logger.error(
                    "API 调用失败: HTTP %s, request_id=%s, code=%s, message=%s",
                    response.status_code,
                    error_payload.get("request_id"),
                    error_payload.get("code"),
                    error_payload.get("message"),
                )
            else:
                logger.error("API 调用失败: HTTP %s - %s", response.status_code, response.text)
            return ""

        result = response.json()
        image_url = (
            result.get("output", {})
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", [{}])[0]
            .get("image")
        )
        if image_url:
            return image_url

        logger.error("解析 API 响应失败: %s", result)
        return ""
    except Exception as e:
        logger.exception("生图请求异常: %s", e)
        return ""