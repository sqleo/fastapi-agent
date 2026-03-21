FROM python:3.13-slim

WORKDIR /app

# 与本地 `PYTHONPATH=src` 一致：保证 `services`、`middlewares`、`utils` 等同级包可被解析
#（不依赖 editable 安装是否已包含全部包名）
ENV PYTHONPATH=/app/src

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev default-libmysqlclient-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY configs/ ./configs/
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

RUN mkdir -p static

EXPOSE 8888

CMD ["python", "-m", "services.server"]
