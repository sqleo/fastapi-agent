from __future__ import annotations

import os

from huggingface_hub import snapshot_download

MODEL_ID = "Casually/uie-nano"
MODEL_DIR = "./model/Casually/uie-nano"
HF_MIRROR = "https://hf-mirror.com"


def main() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)

    print(f"正在下载 {MODEL_ID} 到 {MODEL_DIR} ...")
    print(f"使用镜像: {HF_MIRROR}")
    print("模型较小，请稍候...")

    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=MODEL_DIR,
        endpoint=HF_MIRROR,
    )

    print("下载完成！模型已保存在：", MODEL_DIR)


if __name__ == "__main__":
    main()
