#!/usr/bin/env bash
# 构建 LangGraph + FastAPI 镜像并推送到腾讯云 TCR（命名空间 sqliu）。
#
# 使用前 docker login（密码见控制台「访问凭证」）：
#   docker login ccr.ccs.tencentyun.com --username=1274628288
#
# 执行：./scripts/push-tcr.sh
#
# 可选：IMAGE_TAG（默认 latest）
# 腾讯云 CVM 多为 x86：默认按 linux/amd64 构建；若服务器是 ARM 可设 DOCKER_DEFAULT_PLATFORM=linux/arm64

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REGISTRY="ccr.ccs.tencentyun.com"
TAG="${IMAGE_TAG:-latest}"

export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"
echo "==> 目标平台: ${DOCKER_DEFAULT_PLATFORM}（与腾讯云 x86 实例一致；Apple Silicon 下构建会较慢）"

echo "==> LangGraph 镜像: langgraph-agent:latest"
# 末尾参数透传给 docker build，保证与服务器架构一致
uv run langgraph build -t langgraph-agent:latest -- --platform "${DOCKER_DEFAULT_PLATFORM}"

echo "==> FastAPI 业务镜像（与 Dockerfile 一致）"
DOCKER_BUILDKIT=1 docker compose build fastapi

FASTAPI_LOCAL_LINE="$(docker compose config --images | grep -E -- '-fastapi$' | head -1 || true)"
if [[ -z "${FASTAPI_LOCAL_LINE}" ]]; then
  echo "无法从 docker compose 解析本地 FastAPI 镜像名，请确认在项目根目录执行且 compose 服务名为 fastapi。" >&2
  exit 1
fi
if [[ "${FASTAPI_LOCAL_LINE}" != *:* ]]; then
  FASTAPI_LOCAL="${FASTAPI_LOCAL_LINE}:latest"
else
  FASTAPI_LOCAL="${FASTAPI_LOCAL_LINE}"
fi

DEST_PREFIX="${REGISTRY}/sqliu"
echo "==> 打标签 -> ${DEST_PREFIX}/...:${TAG}"
docker tag langgraph-agent:latest "${DEST_PREFIX}/langgraph-agent:${TAG}"
docker tag "${FASTAPI_LOCAL}" "${DEST_PREFIX}/fastapi:${TAG}"

echo "==> 推送（需已 docker login ${REGISTRY}）"
docker push "${DEST_PREFIX}/langgraph-agent:${TAG}"
docker push "${DEST_PREFIX}/fastapi:${TAG}"

echo "完成。服务器 docker-compose 里可把镜像改为："
echo "  langgraph: image: ${DEST_PREFIX}/langgraph-agent:${TAG}"
echo "  fastapi:   image: ${DEST_PREFIX}/fastapi:${TAG}（并去掉或保留 build: . 二选一）"
