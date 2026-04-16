from llama_index.core import Document
from pathlib import Path

async def load_md_file(file_path: str) -> list[Document]:
    """以低内存占用的方式加载 Markdown 文件。 """
    source_path = Path(file_path)
    if not source_path.exists():
        print(f"⚠️ 文件不存在: {file_path}")
        return []
    print(f"正在流式加载文档: {source_path.name}...")
    content_parts = []
    # 设置 1MB 的缓冲区
    BUFFER_SIZE = 1024 * 1024 
    
    try:
        # 1. 流式读取文件内容并分段暂存
        with open(source_path, "r", encoding="utf-8") as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                content_parts.append(chunk)
        
        # 2. 合并内容并创建 Document 对象
        full_text = "".join(content_parts)
        doc = Document(
            text=full_text,
            metadata={
                "file_name": source_path.name,
                "file_path": str(source_path),
                "extension": source_path.suffix
            }
        )
        
        print(f"✅ 文档加载完成: {source_path.name}")
        return [doc]

    except Exception as e:
        print(f"❌ 加载文件 {file_path} 时发生错误: {e}")
        return []