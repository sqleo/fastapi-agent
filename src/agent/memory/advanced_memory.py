"""高级记忆管理：分类存储 + 分层摘要 + 渐进式压缩。"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from .langmem import get_langgraph_store
from utils.llm_init import create_llm
from utils.sql_db import async_session

logger = logging.getLogger("agent.advanced_memory")

MemoryCategory = Literal["facts", "events"]

class MemoryEntry:
    """记忆条目结构。"""
    def __init__(
        self,
        category: MemoryCategory,
        content: str,
        turn_number: int,
        is_summary: bool = False,
        original_turns: Optional[List[int]] = None,
    ):
        self.category = category
        self.content = content
        self.turn_number = turn_number
        self.is_summary = is_summary
        self.original_turns = original_turns or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "content": self.content,
            "turn_number": self.turn_number,
            "is_summary": self.is_summary,
            "original_turns": self.original_turns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            category=data["category"],
            content=data["content"],
            turn_number=data["turn_number"],
            is_summary=data.get("is_summary", False),
            original_turns=data.get("original_turns", []),
        )

class AdvancedMemoryManager:
    """高级记忆管理器，支持可配置策略。"""

    def __init__(
        self,
        user_id: int,
        token_limit: int = 8000,
        categories: list[str] = None,
        classifier: str = "llm",  # "llm" 或自定义函数
        namespace_prefix: tuple[str, ...] = ("user_memories",),
        store=None,
    ):
        self.user_id = user_id
        self.token_limit = token_limit
        self.categories = categories or ["facts", "events"]
        self.classifier = classifier
        self.namespace_prefix = namespace_prefix
        self.store = store if store is not None else get_langgraph_store()
        self.namespace = namespace_prefix + (str(user_id),)

    async def _classify_memory(self, user_text: str, ai_response: str) -> str:
        """分类记忆类型，支持自定义分类器。"""
        if callable(self.classifier):
            return await self.classifier(user_text, ai_response)
        elif self.classifier == "llm":
            async with async_session() as session:
                llm = await create_llm(session, self.user_id, temperature_override=0.0)

            prompt = f"""分析这段对话，判断属于哪类记忆：

对话：
用户: {user_text}
AI: {ai_response}

分类规则：
- facts: 用户个人信息、偏好、事实陈述（如“我喜欢蓝色”、“我叫张三”）
- events: 具体事件、经历、交互历史（如“昨天我去了公园”、“上次你推荐了产品X”）

只回复分类名称：{', '.join(self.categories)}"""

            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            category = response.content.strip().lower()
            # 匹配到支持的类别
            for cat in self.categories:
                if cat in category:
                    return cat
            return self.categories[0]  # 默认第一类
        else:
            return self.categories[0]  # 默认

    async def _summarize_turns(self, turns: List[Dict[str, str]]) -> str:
        """使用 LLM 生成轮次摘要。"""
        async with async_session() as session:
            llm = await create_llm(session, self.user_id, temperature_override=0.0)

        content = "\n".join([f"用户: {t['user']}\nAI: {t['ai']}" for t in turns])
        prompt = f"""请为以下对话生成一个简洁的摘要，保留关键信息：

{content}

摘要："""

        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        return response.content.strip()

    async def _estimate_tokens(self, text: str) -> int:
        """估算 token 数（简单按字符数 / 4 估算）。"""
        return len(text) // 4

    async def _compress_old_memories(self):
        """渐进式压缩：检查总 token，超限时压缩最旧轮次。"""
        if self.store is None:
            logger.warning(
                "AdvancedMemoryManager no custom store available, skipping compression",
            )
            return

        # 获取所有记忆
        all_memories = await self.store.asearch(self.namespace, "", limit=1000)
        if not all_memories:
            return

        # 解析记忆条目
        entries = []
        for mem in all_memories:
            try:
                data = json.loads(mem.value)
                entries.append(MemoryEntry.from_dict(data))
            except:
                continue

        # 按轮次排序
        entries.sort(key=lambda e: e.turn_number)

        # 计算总 token
        total_tokens = sum(await self._estimate_tokens(e.content) for e in entries)

        if total_tokens <= self.token_limit:
            return

        # 压缩策略：优先压缩 6-15 轮的完整对话
        to_compress = []
        for i, entry in enumerate(entries):
            if 6 <= entry.turn_number <= 15 and not entry.is_summary:
                to_compress.append(i)
                if len(to_compress) >= 3:  # 一次压缩 3 轮
                    break

        if not to_compress:
            return

        # 生成摘要
        turns_to_summarize = []
        original_turns = []
        for idx in to_compress:
            entry = entries[idx]
            # 假设 content 是 "用户: xxx\nAI: yyy" 格式
            parts = entry.content.split("\n")
            if len(parts) >= 2:
                user_part = parts[0].replace("用户: ", "")
                ai_part = parts[1].replace("AI: ", "")
                turns_to_summarize.append({"user": user_part, "ai": ai_part})
                original_turns.append(entry.turn_number)

        if turns_to_summarize:
            summary = await self._summarize_turns(turns_to_summarize)
            summary_entry = MemoryEntry(
                category="events",  # 摘要默认归类为事件
                content=summary,
                turn_number=min(original_turns),
                is_summary=True,
                original_turns=original_turns,
            )

            # 删除原条目，添加摘要
            for idx in reversed(to_compress):
                key = f"turn_{entries[idx].turn_number}"
                await self.store.adelete(self.namespace, key)

            await self.store.aput(
                self.namespace,
                f"summary_{min(original_turns)}",
                json.dumps(summary_entry.to_dict())
            )

    async def retrieve_memories(self, query: str, limit: int = 5) -> List[str]:
        """检索相关记忆，支持分层返回。"""
        if self.store is None:
            logger.warning(
                "AdvancedMemoryManager no custom store available, skipping memory retrieval",
            )
            return []

        # 检索所有相关记忆
        raw_memories = await self.store.asearch(self.namespace, query, limit=limit * 2)

        entries = []
        for mem in raw_memories:
            try:
                data = json.loads(mem.value)
                entries.append(MemoryEntry.from_dict(data))
            except:
                continue

        # 分层返回：优先完整对话，其次摘要，最后事实
        result = []
        complete_turns = [e for e in entries if not e.is_summary and e.turn_number <= 5]
        summaries = [e for e in entries if e.is_summary]
        facts = [e for e in entries if e.category == "facts"]

        result.extend([e.content for e in complete_turns[:limit//2]])
        result.extend([e.content for e in summaries[:limit//2]])
        result.extend([e.content for e in facts[:limit//2]])

        return result[:limit]

    async def store_memory(self, user_text: str, ai_response: str, turn_number: int):
        """存储记忆，支持分类和压缩。"""
        if self.store is None:
            logger.warning(
                "AdvancedMemoryManager no custom store available, skipping memory storage",
            )
            return

        # 分类
        category = await self._classify_memory(user_text, ai_response)

        # 创建条目
        content = f"用户: {user_text}\nAI: {ai_response}"
        entry = MemoryEntry(category=category, content=content, turn_number=turn_number)

        # 存储
        key = f"turn_{turn_number}"
        await self.store.aput(self.namespace, key, json.dumps(entry.to_dict()))

        # 压缩检查
        await self._compress_old_memories()
