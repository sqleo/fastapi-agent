"""根据 Markdown 中图片前后的文本片段，用 LLM 生成插图 alt 说明。"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from configs.ai_config import ai_config
from utils.llm_init import create_llm

logger = logging.getLogger(__name__)

# 仅处理解析产物中的占位链接：空 alt + 路径含 _assets/images/
_IMG_EMPTY_ALT_RE = re.compile(r"!\[\]\(\s*([^)\s]+)\s*\)")


def _is_parsed_asset_url(url: str) -> bool:
    u = url.replace("\\", "/")
    return "_assets/images/" in u


def _context_around(md: str, start: int, end: int, *, radius: int) -> str:
    a = max(0, start - radius)
    b = min(len(md), end + radius)
    return md[a:b].strip()


def _stringify_message_content(msg: object) -> str:
    """兼容 LangChain / OpenAI 兼容接口返回的 str 或 content block 列表。"""
    raw = getattr(msg, "content", None)
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
                else:
                    parts.append(str(block))
            else:
                t = getattr(block, "text", None)
                parts.append(t if isinstance(t, str) else str(block))
        return "".join(parts)
    return str(raw)


def _strip_llm_noise(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    s = re.sub(r"^(描述|说明|Alt|alt)(文本)?[：:]\s*", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("\"'「」")
    return s


def _sanitize_alt(text: str, *, max_len: int) -> str:
    s = _strip_llm_noise(text)
    s = re.sub(r"\s+", " ", s)
    s = s.replace("]", "").replace("[", "")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _llm_alt_enabled(platform_code: str) -> bool:
    if platform_code not in ai_config:
        return False
    return True


async def enrich_markdown_image_alts_with_llm(
    md: str,
    *,
    platform_code: str = "deepseek",
    context_radius: int = 800,
    max_alt_len: int = 100,
    max_llm_tokens: int = 256,
    max_concurrency: int = 3,
) -> tuple[str, dict[str, str]]:
    """
    为正文里 ``![](…_assets/images/…)`` 生成 ``![描述](同一url)``。

    返回 (新 Markdown, 原始文件名 -> alt)，便于写入 ``KbExtractedImageModel.alt_text``。
    未配置 API Key 或调用失败时保持 ``![](…)``，对应字典可能缺项。
    """
    if not md:
        return md, {}

    if not _llm_alt_enabled(platform_code):
        logger.warning(
            "未生成图片 deepseek 没有配置仍为空。"
        )
        return md, {}

    matches: list[tuple[int, int, str]] = []
    for m in _IMG_EMPTY_ALT_RE.finditer(md):
        url = m.group(1).strip()
        if not _is_parsed_asset_url(url):
            continue
        matches.append((m.start(), m.end(), url))

    if not matches:
        return md, {}

    llm = create_llm(platform_code, temperature=0.2, max_tokens=max_llm_tokens)
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _one_alt(start: int, end: int) -> str:
        ctx = _context_around(md, start, end, radius=context_radius)
        prompt = (
            "你是文档编辑。下面是一段 Markdown 节选，其中含有一张图片链接（路径中带 _assets/images/）。"
            "请结合前后文字，用一句简短中文概括该图在文中的含义，作为图片 alt（无障碍描述）。\n"
            "只输出这一句描述本身：不要引号、不要序号、不要 markdown、不要复述链接。\n\n"
            f"---\n{ctx}\n---"
        )
        async with sem:
            try:
                resp = await llm.ainvoke([HumanMessage(content=prompt)])
                raw = _stringify_message_content(resp)
                return _sanitize_alt(raw, max_len=max_alt_len)
            except Exception as e:
                logger.warning("图片 alt LLM 调用失败: %s", e)
                return ""

    alts = await asyncio.gather(*[_one_alt(s, e) for s, e, _ in matches])

    if matches and not any(alts):
        logger.warning(
            "本次共 %d 处解析图片链接，但 LLM 未得到任何有效 alt（请查密钥、网络、base_url 与模型名）。",
            len(matches),
        )

    fname_to_alt: dict[str, str] = {}
    parts: list[str] = []
    last = 0
    for (start, end, url), alt in zip(matches, alts, strict=True):
        parts.append(md[last:start])
        fname = url.rsplit("/", 1)[-1]
        if alt:
            parts.append(f"![{alt}]({url})")
            fname_to_alt[fname] = alt
        else:
            parts.append(f"![]({url})")
        last = end
    parts.append(md[last:])
    return "".join(parts), fname_to_alt
