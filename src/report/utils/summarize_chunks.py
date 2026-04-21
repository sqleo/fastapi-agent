from langchain_core.prompts import ChatPromptTemplate

summarize_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个信息提炼专家。\n"
        "请将以下多条调研内容合并，提炼成一段简洁的摘要（150字以内）。\n"
        "保留关键数据、核心观点，去除冗余和重复信息。\n"
        "直接输出摘要文本，不要加标题或前缀。"
    )),
    ("human", "调研主题：{topic_key}\n\n原始内容：\n{raw_content}"),
])


async def summarize_chunks_by_topic(chunks: list[dict], llm) -> str:
    """对 research_chunks 按 topic_key 分组，逐组调用 LLM 摘要，返回拼接后的汇总文本。

    Args:
        chunks: ReportState.research_chunks，每个元素是 dict，含 topic_key / content / source
        llm: 已初始化的 LLM 实例

    Returns:
        格式化的摘要字符串，按主题分段
    """
    if not chunks:
        return "暂无调研数据"

    # 按 topic_key 分组
    topic_map: dict[str, list[str]] = {}
    for chunk in chunks:
        key = chunk.get("topic_key", "general")
        topic_map.setdefault(key, []).append(chunk.get("content", ""))

    chain = summarize_prompt | llm

    summary_parts: list[str] = []
    for topic_key, contents in topic_map.items():
        raw_content = "\n---\n".join(contents)
        response = await chain.ainvoke({
            "topic_key": topic_key,
            "raw_content": raw_content,
        })
        summary_parts.append(f"[{topic_key}]\n{response.content.strip()}")

    return "\n\n".join(summary_parts)
