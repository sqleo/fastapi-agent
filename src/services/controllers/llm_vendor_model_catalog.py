"""各厂商可选模型 id 静态目录（用于默认模型下拉；与已配置厂商组合）。"""

from __future__ import annotations

# vendor code -> list of { "model_id", "label" (optional), "capabilities": [...] }
VENDOR_MODEL_CATALOG: dict[str, list[dict]] = {
    "openai": [
        {"model_id": "gpt-4.1", "label": "GPT-4.1", "capabilities": ["LLM", "VLM"]},
        {"model_id": "gpt-4o", "label": "GPT-4o", "capabilities": ["LLM", "VLM"]},
        {"model_id": "gpt-4o-mini", "label": "GPT-4o mini", "capabilities": ["LLM", "VLM"]},
        {"model_id": "text-embedding-3-large", "label": "text-embedding-3-large", "capabilities": ["Embedding"]},
        {"model_id": "text-embedding-3-small", "label": "text-embedding-3-small", "capabilities": ["Embedding"]},
    ],
    "anthropic": [
        {"model_id": "claude-3-5-sonnet-20241022", "label": "Claude 3.5 Sonnet", "capabilities": ["LLM", "VLM"]},
        {"model_id": "claude-3-opus-20240229", "label": "Claude 3 Opus", "capabilities": ["LLM", "VLM"]},
    ],
    "google_gemini": [
        {"model_id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "capabilities": ["LLM", "VLM"]},
        {"model_id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro", "capabilities": ["LLM", "VLM"]},
        {"model_id": "text-embedding-004", "label": "text-embedding-004", "capabilities": ["Embedding"]},
    ],
    "deepseek": [
        {"model_id": "deepseek-chat", "label": "DeepSeek Chat", "capabilities": ["LLM"]},
        {"model_id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "capabilities": ["LLM"]},
    ],
    "qwen": [
        {"model_id": "qwen-turbo", "label": "Qwen Turbo", "capabilities": ["LLM"]},
        {"model_id": "qwen-plus", "label": "Qwen Plus", "capabilities": ["LLM"]},
        {"model_id": "qwen-vl-plus", "label": "Qwen VL Plus", "capabilities": ["LLM", "VLM"]},
        {"model_id": "text-embedding-v4", "label": "text-embedding-v4", "capabilities": ["Embedding"]},
        {"model_id": "Qwen/Qwen3-Reranker-0.6B", "label": "Qwen3 Reranker 0.6B", "capabilities": ["Rerank"]},
        {"model_id": "Qwen/Qwen3-Reranker-4B", "label": "Qwen3 Reranker 4B", "capabilities": ["Rerank"]},
        {"model_id": "Qwen/Qwen3-Reranker-8B", "label": "Qwen3 Reranker 8B", "capabilities": ["Rerank"]}
    ],
    "zhipu": [
        {"model_id": "glm-4-plus", "label": "GLM-4 Plus", "capabilities": ["LLM"]},
        {"model_id": "glm-4v", "label": "GLM-4V", "capabilities": ["LLM", "VLM"]},
        {"model_id": "embedding-3", "label": "Embedding-3", "capabilities": ["Embedding"]},
    ],
    "moonshot": [
        {"model_id": "moonshot-v1-8k", "label": "Moonshot v1 8k", "capabilities": ["LLM"]},
        {"model_id": "moonshot-v1-32k", "label": "Moonshot v1 32k", "capabilities": ["LLM"]},
    ],
    "baichuan": [
        {"model_id": "Baichuan4-Turbo", "label": "Baichuan4 Turbo", "capabilities": ["LLM"]},
    ],
    "minimax": [
        {"model_id": "abab6.5s-chat", "label": "abab6.5s-chat", "capabilities": ["LLM"]},
        {"model_id": "speech-2.5-hd", "label": "语音合成（示例）", "capabilities": ["TTS"]},
    ],
    "jina": [
        {"model_id": "jina-embeddings-v3", "label": "jina-embeddings-v3", "capabilities": ["Embedding"]},
        {"model_id": "jina-reranker-v2", "label": "jina-reranker-v2", "capabilities": ["Rerank"]},
    ],
    "cohere": [
        {"model_id": "command-r-plus", "label": "command-r-plus", "capabilities": ["LLM"]},
        {"model_id": "embed-english-v3.0", "label": "embed-english-v3.0", "capabilities": ["Embedding"]},
        {"model_id": "rerank-english-v3.0", "label": "rerank-english-v3.0", "capabilities": ["Rerank"]},
    ],
    "openrouter": [
        {"model_id": "openai/gpt-4o", "label": "OpenAI GPT-4o (via OpenRouter)", "capabilities": ["LLM", "VLM"]},
        {"model_id": "anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet (via OpenRouter)", "capabilities": ["LLM", "VLM"]},
    ],
    "tencent_cloud": [],
    "baidu_yiyan": [],
    "volcengine": [],
}

# extra_config.model_type -> 能力标签（用于单模型配置类厂商）
_MODEL_TYPE_TO_CAPS: dict[str, list[str]] = {
    "chat": ["LLM"],
    "embedding": ["Embedding"],
    "speech2text": ["ASR"],
    "speech_to_text": ["ASR"],
    "tts": ["TTS"],
    "rerank": ["Rerank"],
    "multimodal": ["LLM", "VLM"],
}


def capabilities_for_extra_model(vendor_code: str, extra: dict) -> list[str]:
    """从厂商私有配置推断该条实例对应的能力标签。"""
    mt = (extra.get("model_type") or "").strip().lower()
    if mt in _MODEL_TYPE_TO_CAPS:
        return _MODEL_TYPE_TO_CAPS[mt]
    return []
