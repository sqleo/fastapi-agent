"""对话轮次切分与粗略 token 估计（用于短期窗口与压缩触发）。"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def approx_tokens(text: str) -> int:
    """中英混合粗略估计：约 4 字符一 token。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def message_text(m: BaseMessage) -> str:
    c = getattr(m, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(c or "")


def split_system_and_rest(messages: list[BaseMessage]) -> tuple[list[BaseMessage], list[BaseMessage]]:
    system: list[BaseMessage] = []
    rest: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system.append(m)
        else:
            rest.append(m)
    return system, rest


def segment_turns(rest: list[BaseMessage]) -> list[list[BaseMessage]]:
    """按「一轮 = 一条 Human 起至下一条 Human 之前」切段（含中间 Tool / AI）。"""
    turns: list[list[BaseMessage]] = []
    current: list[BaseMessage] = []
    for m in rest:
        if isinstance(m, HumanMessage) and current:
            turns.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        turns.append(current)
    return turns


def estimate_messages_tokens(messages: list[BaseMessage]) -> int:
    return sum(approx_tokens(message_text(m)) for m in messages)


def last_user_query(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return message_text(m).strip()
    return ""


def take_last_turns(
    messages: list[BaseMessage],
    *,
    max_turns: int,
) -> list[BaseMessage]:
    """保留全部 System，再保留最近 ``max_turns`` 轮（不足则全保留）。"""
    system, rest = split_system_and_rest(messages)
    if max_turns <= 0:
        return system
    turns = segment_turns(rest)
    kept = turns[-max_turns:]
    flat: list[BaseMessage] = []
    for t in kept:
        flat.extend(t)
    return system + flat


def format_turns_for_summary(turns: list[list[BaseMessage]]) -> str:
    lines: list[str] = []
    for i, turn in enumerate(turns, 1):
        lines.append(f"--- 轮次 {i} ---")
        for m in turn:
            role = m.type if hasattr(m, "type") else m.__class__.__name__
            body = message_text(m).strip()
            if body:
                lines.append(f"[{role}] {body[:2000]}")
    return "\n".join(lines)
