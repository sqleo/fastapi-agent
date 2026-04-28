import asyncio
from typing import cast
from report.llm import create_llm
from report.state import OutlineSection, ReportState, SectionReview
from report.utils.emit_trace_event import emit_trace_event
from langchain_core.prompts import ChatPromptTemplate

multiple_drafts_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告撰写专家。\n"
        "原始用户问题：{user_query}\n"
        "报告主题是：{topic}\n"
        "当前正在撰写 {industry} 行业报告的特定章节。\n"
        "报告总体深度要求：{depth}\n\n"
        "报告范围是：{scope}\n"
        "**格式规范** {output_format}\n"
        "【写作准则】：\n"
        "1. 严格基于提供的【调研摘要】撰写，引用数据需标注来源，不要凭空捏造。\n"
        "2. 语言专业、逻辑清晰、数据翔实。\n"
       "【配图要求】：\n"
        "当你认为某一段文字需要图表或插图来辅助说明时，请在对应的段落下方插入一个配图占位符。\n"
        "占位符必须严格使用以下 XML 格式（必须包含 prompt 和 size 两个属性）：\n"
        '<image_placeholder prompt="这里写具体的、可以直接发给qwen-image-2.0-pro的中文画面描述提示词" size="这里是配图的尺寸" />\n'
        "请严格遵守以下限制条件：\n"
        "- 占位符必须单独成行。\n"
        "- 绝对不要将占位符包裹在 Markdown 代码块（如 ```xml ```）中，必须直接输出纯文本标签。\n"
        "- prompt 属性：请使用丰富、具体的画面描述语言。Qwen擅长文字渲染，如果需要图中包含特定中英文，请用引号明确标注，模型将精准贴合物理材质生成（例如：靛蓝色牌匾上刻着“文字渲染”）。\n"
        "- size 属性：优先从以下官方推荐分辨率中选择其一：'2048*2048' (1:1，默认), '2688*1536' (16:9), '1536*2688' (9:16), '2368*1728' (4:3), '1728*2368' (3:4)。注意中间连接符为 '*'。\n"
        "- 严禁自行伪造或捏造 Markdown 图片链接（如 `![img](http...)`）。\n"
    )),
    ("human", (
        "【本章节撰写任务】\n"
        "章节标题：{title}\n"
        "章节目标：{objective}\n"
        "关键要点：{key_points}\n\n"
        "目标字数：{target_words} 字\n\n"
        "【调研摘要（核心素材）】\n"
        "{content}\n\n"
        "【调研摘要（核心素材）来源】\n"
        "{source}\n\n"
        "请开始撰写该章节正文："

    )),
])


async def writer_node(state: ReportState) -> dict:
    """生成报告内容 (并行撰写)"""
    emit_trace_event(
        "phase",
        {
            "phase": "writing",
            "status": "running",
            "message": "开始并行撰写报告章节",
        },
    )

    if not state.outline:
        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "failed",
                "message": "未发现大纲，无法撰写报告",
            },
        )
        raise ValueError("未发现大纲，无法撰写报告")

    llm = await create_llm("llm")
    chunks = state.research_chunks or []
    intent = state.intent

    async def generate_section(section: OutlineSection) -> SectionReview:
        # 每章只取关联的调研数据
        section_chunks = [c for c in chunks if c.topic_key in (section.evidence_keys or [])]
        # 没有关联数据时降级使用全部
        if not section_chunks:
            section_chunks = chunks
        content_text = "\n".join([f"[{c.topic_key}] {c.content}" for c in section_chunks])
        source_text = "\n".join(list(set([c.source for c in section_chunks if c.source])))

        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "running",
                "task_id": section.section_id,
                "title": section.title,
                "message": f"{section.title} 章节撰写中",
            },
        )

        chain = multiple_drafts_prompt | llm
        response = await chain.ainvoke({
            "user_query": state.user_query,
            "topic": intent.topic if intent else "-",
            "industry": intent.industry if intent else "-",
            "depth": intent.depth if intent else "-",
            "scope": intent.scope if intent else "-",
            "output_format": intent.output_format if intent else "Markdown",
            "content": content_text or "暂无调研摘要",
            "source": source_text or "暂无来源数据",
            "title": section.title,
            "objective": section.objective,
            "key_points": ", ".join(section.key_points) if isinstance(section.key_points, list) else section.key_points,
            "target_words": section.target_words,
        })

        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "completed",
                "task_id": section.section_id,
                "title": section.title,
                "message": f"{section.title} 章节完成",
            },
        )

        return SectionReview(
            section_id=section.section_id,
            content=f"## {section.title}\n\n{response.content}",
        )

    last_review = next(
        (a for a in reversed(state.artifacts or []) if a.get("type") == "review"),
        None,
    )
    revise_ids = set(last_review.get("sections_to_revise", [])) if last_review else set()

    # 首轮写全部；复写轮只写未通过章节
    sections_to_write = (
        [s for s in state.outline if s.section_id in revise_ids]
        if revise_ids
        else list(state.outline)
    )

    total = len(sections_to_write)
    tasks = [generate_section(section) for section in sections_to_write]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    rewritten_reviews: list[SectionReview] = []
    done = 0
    for i, item in enumerate(results):
        if isinstance(item, Exception):
            section = sections_to_write[i]
            emit_trace_event(
                "task",
                {
                    "phase": "writing",
                    "status": "failed",
                    "task_id": section.section_id,
                    "title": section.title,
                    "message": f"{section.title} 章节失败",
                    "error": str(item),
                },
            )
            continue
        rewritten_reviews.append(cast(SectionReview, item))
        done += 1
        emit_trace_event(
            "metric",
            {
                "phase": "writing",
                "done": done,
                "total": total,
                "coverage": round((done / total) * 100, 2) if total else 0,
            },
        )

    # 按 section_id 合并：只替换本轮重写章节，保留其余章节
    merged_reviews_map = {s.section_id: s for s in (state.section_reviews or [])}
    for s in rewritten_reviews:
        merged_reviews_map[s.section_id] = s
    section_reviews = [merged_reviews_map[s.section_id] for s in state.outline if s.section_id in merged_reviews_map]

    print(f"✅ 报告草稿撰写完成 共{done}章（本轮重写）")
    emit_trace_event(
        "artifact",
        {
            "phase": "writing",
            "type": "report_ready",
            "chapter_count": done,
            "word_count": sum(len(s.content) for s in section_reviews),
            "message": f"报告草稿撰写完成，共 {done} 章",
        },
    )

    return {"section_reviews": section_reviews}