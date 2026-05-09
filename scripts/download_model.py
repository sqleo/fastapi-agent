# 可选脚本：下载 BAAI/bge-small-zh-v1.5。当前默认嵌入走 DB「LLM 全局设置」HTTP /embeddings，一般不跑本脚本。
import os

from huggingface_hub import snapshot_download

# 创建 model 文件夹（如果不存在）
model_dir = "./model/BAAI/bge-small-zh-v1.5"
os.makedirs(model_dir, exist_ok=True)

HF_MIRROR = "https://hf-mirror.com"

print("正在下载 BAAI/bge-small-zh-v1.5 到 ./model/BAAI/bge-small-zh-v1.5 ...")
print(f"使用镜像: {HF_MIRROR}")
print("模型大小约 133 MB，请耐心等待...")

snapshot_download(
    repo_id="BAAI/bge-small-zh-v1.5",
    local_dir=model_dir,
    endpoint=HF_MIRROR,
)
print("下载完成！模型已保存在：", model_dir)
