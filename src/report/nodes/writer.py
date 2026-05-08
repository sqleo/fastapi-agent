import asyncio
from typing import Optional, cast
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
        "3. 直接输出正文段落，绝对不要在开头输出章节标题或编号（例如不要出现“### 第一章 某某”）。系统会在外部自动拼接标题。\n"
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
        "{revision_feedback}"
        "请开始撰写该章节正文："
    )),
])


async def writer_node(state: ReportState) -> dict:
    """生成报告内容 (并行撰写)"""
    emit_trace_event(
        "stage",
        {
            "phase": "writing",
            "status": "running",
            "message": "开始并行撰写报告章节",
        },
    )

    if not state.outline:
        raise ValueError("未发现大纲，无法撰写报告")

    llm = await create_llm("llm")
    chunks = state.research_chunks or []
    intent = state.intent

    async def generate_section(
        section: OutlineSection,
        prev_review: Optional[SectionReview] = None,
    ) -> SectionReview:
        # 每章只取关联的调研数据
        section_chunks = [c for c in chunks if c.topic_key in (section.evidence_keys or [])]
        # 没有关联数据时降级使用全部
        if not section_chunks:
            section_chunks = chunks
        content_text = "\n".join(
            f"[{c.topic_key}][{getattr(c, 'source_type', 'web')}] {c.content}"
            for c in section_chunks
        )
        source_text = "\n".join(list(set([c.source for c in section_chunks if c.source])))

        # 构建审核反馈（仅重写轮次时注入）
        revision_feedback = ""
        if prev_review and (prev_review.issues or prev_review.suggestions):
            lines = ["【上轮审核反馈 — 重写时必须针对性改进以下问题】"]
            if prev_review.issues:
                lines.append("❌ 问题：")
                lines.extend(f"  • {issue}" for issue in prev_review.issues)
            if prev_review.suggestions:
                lines.append("💡 改进建议：")
                lines.extend(f"  • {sug}" for sug in prev_review.suggestions)
            revision_feedback = "\n".join(lines) + "\n\n"

        emit_trace_event(
            "section_update",
            {
                "phase": "writing",
                "section_id": section.section_id,
                "title": section.title,
                "status": "writing",
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
            "revision_feedback": revision_feedback,
        })

        emit_trace_event(
            "section_update",
            {
                "phase": "writing",
                "section_id": section.section_id,
                "title": section.title,
                "status": "done",
                "content_preview": response.content[:400],
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
    
    is_first_round = last_review is None
    revise_ids = set()

    if is_first_round:
        sections_to_write = list(state.outline)
    else:
        revise_ids = set(last_review.get("sections_to_revise", []))
        if not revise_ids and state.section_reviews:
            # 如果整体没通过但没有单章不及格，则重写得分最低的章节
            sorted_reviews = sorted(state.section_reviews, key=lambda x: x.score or 0)
            lowest_score = sorted_reviews[0].score or 0
            revise_ids = {s.section_id for s in sorted_reviews if (s.score or 0) <= lowest_score}
            
        sections_to_write = [s for s in state.outline if s.section_id in revise_ids]

    # 构建上轮审核反馈映射，用于指导重写
    prev_reviews_map: dict[str, SectionReview] = {
        s.section_id: s for s in (state.section_reviews or [])
    }

    total = len(sections_to_write)
    tasks = [
        generate_section(
            section,
            prev_review=prev_reviews_map.get(section.section_id) if revise_ids else None,
        )
        for section in sections_to_write
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    rewritten_reviews: list[SectionReview] = []
    done = 0
    for i, item in enumerate(results):
        section = sections_to_write[i]
        if isinstance(item, Exception):
            print(f"❌ 撰写章节 {section.section_id} ({section.title}) 失败: {item}")
            rewritten_reviews.append(
                SectionReview(
                    section_id=section.section_id,
                    content=f"## {section.title}\n\n[该章节生成失败，等待重写：{str(item)}]",
                    score=0
                )
            )
            continue
        rewritten_reviews.append(cast(SectionReview, item))
        done += 1
        emit_trace_event(
            "progress",
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

    return {"section_reviews": section_reviews}

