import asyncio
import logging
import re

from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event
from report.utils.qwen_image_tool import qwen_image_tool

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 1
semaphore = asyncio.Semaphore(MAX_CONCURRENT)



async def process_section_images(section):
    """处理单个章节内的所有图片"""
    content = section.content
    pattern = r'<image_placeholder\s+prompt="([^"]+)"\s+size="([^"]+)"\s*/>'

    matches = list(re.finditer(pattern, content))

    if not matches:
        return section
    
    new_content = content
    for match in matches:
        original_tag = match.group(0)
        
        # 1. 直接提取 prompt 和 size
        img_description = match.group(1).strip()
        img_size = match.group(2).strip()
            
        # 2. 构造发给 Qwen 的详细提示词
        full_prompt = f"一张专业风格的商业报告配图，主题是：{img_description}。风格：扁平化插画，蓝色调，科技感。"
        
        # 3. 并发生成图片
        async with semaphore:
            logger.info(f"[{section.section_id}] 正在生成图片: {img_description[:15]}... 尺寸: {img_size}")
            img_url = await qwen_image_tool(full_prompt, img_size)
        # 4. 替换文本
        if img_url:
            # 替换占位符为标准的 Markdown 图片语法
            replacement = f"\n\n![{img_description}]({img_url})\n"
            new_content = new_content.replace(original_tag, replacement)
        else:
            new_content = new_content.replace(original_tag, f"\n> *(配图生成失败：{img_description})*\n")

    return section.model_copy(update={"content": new_content})

async def illustrator_node(state: ReportState) -> dict:
    """生成报告插图"""
    logger.info("=== 进入 Illustrator Node (并行配图阶段) ===")
    emit_trace_event(
        "phase",
        {
            "phase": "illustration",
            "status": "running",
            "message": "正在生成报告插图",
        },
    )
    if not state.section_reviews:
        logger.warning("没有发现 section_reviews，跳过配图节点。")
        return {"section_reviews": state.section_reviews}
    # 为每个章节创建一个处理任务
    tasks = [process_section_images(section) for section in state.section_reviews]

    # 并发执行所有章节的配图任务
    updated_sections = await asyncio.gather(*tasks, return_exceptions=True)
    safe_sections = []
    for index, result in enumerate(updated_sections):
        if isinstance(result, Exception):
            section = state.section_reviews[index]
            logger.exception("[%s] 配图任务失败，保留原文内容: %s", section.section_id, result)
            safe_sections.append(section)
        else:
            safe_sections.append(result)
    
    logger.info("=== 所有章节配图处理完成 ===")
    emit_trace_event(
        "phase",
        {
            "phase": "illustration",
            "status": "completed",
            "message": "报告插图生成完成",
        },
    )
    
    # 返回更新后的状态
    return {"section_reviews": list(safe_sections)}