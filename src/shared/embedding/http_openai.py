"""OpenAI 兼容 ``/v1/embeddings`` HTTP 客户端（httpx）。

参数来自数据库解析的 ``EmbeddingConfig``（``llm_global_setting`` + ``llm_vendor``）。
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.embedding.config import EmbeddingConfig


class HttpOpenAIEmbeddings:
    """OpenAI 兼容的 embeddings HTTP 客户端。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        dimensions: int | None = 1024,
        timeout: float = 120.0,
        batch_size: int | None = None,
    ) -> None:
        """初始化请求参数与批大小。"""
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.dimensions = dimensions
        self.timeout = timeout
        if batch_size is not None:
            self.batch_size = max(1, batch_size)
        elif model == "text-embedding-v4":
            self.batch_size = 10
        else:
            self.batch_size = 100
        self._url = f"{self.base_url}/embeddings"

    @classmethod
    def from_config(cls, config: EmbeddingConfig) -> HttpOpenAIEmbeddings:
        """由 ``llm_global_setting`` + ``llm_vendor`` 解析得到的配置构造客户端。"""
        return cls(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            dimensions=config.dimensions,
        )

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
                    f"embeddings HTTP {r.status_code}: {r.text[:2000]}"
                ) from None
            return self._parse_response(r.json())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文档文本。"""
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
        """嵌入单条查询文本。"""
        t = (text or "").strip() or " "
        return self._post(t)[0]
