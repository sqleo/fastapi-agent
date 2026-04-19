from __future__ import annotations

import shutil
from pathlib import Path

from modelscope import snapshot_download

MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
MODEL_DIR = Path("./model/Qwen/Qwen3-Reranker-0.6B")
CACHE_DIR = Path("./model/.modelscope_cache")


def _clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_flat(src: Path, dst: Path) -> None:
    """把 src 目录内容平铺复制到 dst（仅本次下载脚本使用）。"""
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def main() -> None:
	print(f"准备下载: {MODEL_ID}")
	print(f"目标目录: {MODEL_DIR.resolve()}")
	print(f"缓存目录: {CACHE_DIR.resolve()}")

	MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
	CACHE_DIR.mkdir(parents=True, exist_ok=True)

	# 先下载到独立缓存目录，避免后续清空目标目录时删掉下载源
	resolved = Path(
		snapshot_download(
			MODEL_ID,
			cache_dir=str(CACHE_DIR),
		)
	)

	print(f"ModelScope 返回目录: {resolved}")
	if not resolved.exists():
		raise FileNotFoundError(f"ModelScope 返回目录不存在：{resolved}")

	source_dir = resolved
	if not ((source_dir / "model.safetensors").exists() or (source_dir / "pytorch_model.bin").exists()):
		# ModelScope 常见结构：.../Qwen/Qwen3-Reranker-0.6B
		candidate = resolved / "Qwen" / "Qwen3-Reranker-0.6B"
		if candidate.exists():
			source_dir = candidate
		else:
			raise FileNotFoundError(
				f"未找到权重文件：{resolved}（也未找到 {candidate}）"
			)

	_clean_dir(MODEL_DIR)
	_copy_flat(source_dir, MODEL_DIR)

	if not ((MODEL_DIR / "model.safetensors").exists() or (MODEL_DIR / "pytorch_model.bin").exists()):
		raise FileNotFoundError(f"下载后仍缺少权重文件：{MODEL_DIR}")

	print("下载完成 ✅")
	print("权重文件已就位：", MODEL_DIR)


if __name__ == "__main__":
    main()
