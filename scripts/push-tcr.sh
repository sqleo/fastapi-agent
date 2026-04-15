#!/usr/bin/env bash
# 构建 LangGraph + FastAPI 镜像并推送到腾讯云 TCR（命名空间 sqliu）。
#
# 使用前请先执行：
#   docker login ccr.ccs.tencentyun.com --username=1274628288
#
# 执行方式：./scripts/push-tcr.sh
# 可选环境变量：
#   IMAGE_TAG=yourtag          默认 latest
#   DOCKER_DEFAULT_PLATFORM=linux/arm64   （Apple Silicon 或 ARM 服务器时使用）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REGISTRY="ccr.ccs.tencentyun.com"
TAG="${IMAGE_TAG:-latest}"

export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"
echo "==> 目标平台: ${DOCKER_DEFAULT_PLATFORM}"

DEST_PREFIX="${REGISTRY}/sqliu"

echo "==> 开始构建镜像..."

# ====================== 构建 LangGraph 镜像 ======================
echo "==> 正在构建 LangGraph 镜像 (使用 Dockerfile.langgraph) ..."
DOCKER_BUILDKIT=1 docker build \
  --platform "${DOCKER_DEFAULT_PLATFORM}" \
  -f Dockerfile.langgraph \
  -t langgraph-agent:latest \
  .

# ====================== 构建 FastAPI 镜像 ======================
# FastAPI 构建使用 docker-compose.dev.yml（如需改用其它 compose 文件，改下方 -f 路径即可）
echo "==> 正在构建 FastAPI 镜像 (使用 Dockerfile.fastapi) ..."
DOCKER_BUILDKIT=1 docker compose \
  -f docker-compose.dev.yml \
  build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  fastapi

# 获取与 compose 服务 fastapi 对应的镜像名：优先使用显式 image，否则为 <项目名>-fastapi
FASTAPI_LOCAL="$(
  docker compose -f docker-compose.dev.yml config --format json 2>/dev/null \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
s = d.get('services', {}).get('fastapi') or {}
img = s.get('image')
if img:
    print(img)
else:
    proj = d.get('name') or 'compose'
    print(f'{proj}-fastapi')
"
)"

if [[ -z "${FASTAPI_LOCAL}" ]]; then
  echo "错误：无法获取 FastAPI 镜像名称，请确认 docker-compose.dev.yml 中有 fastapi 服务" >&2
  exit 1
fi

echo "==> 构建完成"
echo "    LangGraph 本地镜像: langgraph-agent:latest"
echo "    FastAPI   本地镜像: ${FASTAPI_LOCAL}"

# ====================== 打标签 ======================
echo "==> 打标签并准备推送到 TCR ..."
docker tag langgraph-agent:latest "${DEST_PREFIX}/langgraph-agent:${TAG}"
docker tag "${FASTAPI_LOCAL}" "${DEST_PREFIX}/fastapi:${TAG}"

# ====================== 推送 ======================
echo "==> 开始推送镜像到 ${DEST_PREFIX} ..."
docker push "${DEST_PREFIX}/langgraph-agent:${TAG}"
docker push "${DEST_PREFIX}/fastapi:${TAG}"

echo "========================================"
echo "✅ 推送完成！"
echo ""
echo "在生产环境的 docker-compose.prod.yml 中可使用以下镜像："
echo "  langgraph:"
echo "    image: ${DEST_PREFIX}/langgraph-agent:${TAG}"
echo ""
echo "  fastapi:"
echo "    image: ${DEST_PREFIX}/fastapi:${TAG}"
echo ""
echo "提示：生产环境建议去掉 build: 部分，只保留 image: （更快更稳定）"