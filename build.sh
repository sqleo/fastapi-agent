#!/bin/bash
set -e

echo "=========================================="
echo "  一键构建所有 Docker 镜像"
echo "=========================================="

# 1. 构建 LangGraph Platform 镜像
echo ""
echo "[1/3] 构建 LangGraph Agent 镜像..."
langgraph build -t langgraph-agent
echo "  ✅ LangGraph 镜像构建完成: langgraph-agent:latest"

# 2. 构建 FastAPI 业务服务镜像
echo ""
echo "[2/3] 构建 FastAPI 服务镜像..."
docker compose build fastapi
echo "  ✅ FastAPI 镜像构建完成"

# 3. 检查 .env 文件
echo ""
echo "[3/3] 检查环境配置..."
if [ ! -f .env ]; then
    echo "  ⚠️  未检测到 .env 文件，正在从 .env.example 复制..."
    cp .env.example .env
    echo "  📝 请编辑 .env 文件，填入 API Key 等敏感配置"
fi

echo ""
echo "=========================================="
echo "  ✅ 所有镜像构建完成！"
echo "=========================================="
echo ""
echo "启动命令："
echo ""
echo "  # 全部本地部署（所有中间件都用容器）："
echo "  docker compose --profile postgres --profile redis --profile mysql --profile milvus up -d"
echo ""
echo "  # 仅数据库本地，其余用第三方："
echo "  docker compose --profile postgres --profile redis up -d"
echo ""
echo "  # 全部使用第三方（修改 .env 中对应变量）："
echo "  docker compose up -d"
echo ""
echo "  # 查看日志："
echo "  docker compose logs -f"
echo ""
echo "  # 停止所有服务："
echo "  docker compose --profile postgres --profile redis --profile mysql --profile milvus down"
echo ""
echo "可选 profile：postgres | redis | mysql | milvus"
echo "按需组合，未启用的 profile 通过 .env 配置第三方地址"
echo ""
