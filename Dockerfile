# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONPATH=/app/src
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先只复制锁文件：依赖不变时 Docker 可复用下面这一层，不必重复下载几百 MB 轮子
COPY pyproject.toml uv.lock ./

# BuildKit 缓存：同一台机器多次 build 时复用已下载的 wheel（需启用 DOCKER_BUILDKIT=1）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY configs/ ./configs/
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p static

EXPOSE 8888

CMD ["python", "-m", "services.server"]
