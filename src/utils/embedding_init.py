"""Embedding 工厂：百炼兼容 ``/v1/embeddings`` 与 OpenAI 一致，使用 ``input`` + 可选 ``dimensions``。"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from configs.ai_config import ai_config
from configs.env import env_config


class DashScopeCompatibleEmbeddings(Embeddings):
    """
    直接 POST 百炼 ``compatible-mode/v1/embeddings``。

    官方说明与 OpenAI 一致：JSON 使用 ``input``（str 或 list[str]）、``encoding_format``，
    ``text-embedding-v4`` 还可传 ``dimensions``。单请求最多 10 条文本（v4 限制）。
    参考：https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        dimensions: int | None = 1024,
        timeout: float = 120.0,
        batch_size: int = 10,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.dimensions = dimensions
        self.timeout = timeout
        self.batch_size = max(1, min(batch_size, 10))
        self._url = f"{self.base_url}/embeddings"

    def _parse_response(self, body: dict[str, Any]) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list):
            raise ValueError(f"嵌入接口返回异常（无 data 列表）: {body}")
        items = sorted(data, key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]

    def _post(self, input_payload: str | list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_payload,
            "encoding_format": "float",
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(self._url, json=payload, headers=headers)
            if r.is_error:
                raise RuntimeError(
                    f"百炼 embeddings HTTP {r.status_code}: {r.text[:2000]}"
                ) from None
            return self._parse_response(r.json())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [t if (t or "").strip() else " " for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(cleaned), self.batch_size):
            batch = cleaned[i : i + self.batch_size]
            inp: str | list[str] = batch[0] if len(batch) == 1 else batch
            out.extend(self._post(inp))
        return out

    def embed_query(self, text: str) -> list[float]:
        t = (text or "").strip() or " "
        return self._post(t)[0]


def create_embeddings(platform_code: str = "qwen-embedding", dimensions: int = 1024):
    """
    百炼 ``text-embedding-v4``：用 ``DashScopeCompatibleEmbeddings``（标准 ``input`` 体）。
    其它模型用 ``OpenAIEmbeddings``。
    """
    if platform_code not in ai_config:
        raise ValueError(f"Invalid platform code: {platform_code}")
    platform_config = ai_config[platform_code]
    key = (platform_config.get("api_key") or env_config.llm_deepseek_api_key or "").strip()
    if not key:
        raise ValueError(f"平台 {platform_code!r} 未配置 API Key")

    model = platform_config["model"]
    base_url = platform_config["base_url"]

    if model == "text-embedding-v4":
        return DashScopeCompatibleEmbeddings(
            model=model,
            api_key=key,
            base_url=base_url,
            dimensions=dimensions,
        )

    return OpenAIEmbeddings(
        model=model,
        api_key=key,
        base_url=base_url,
        dimensions=dimensions,
    )
