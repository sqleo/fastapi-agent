FROM python:3.13-slim

WORKDIR /app

# 国内镜像：apt（Debian）+ pip（PyPI），构建时可覆盖：
#   docker build --build-arg APT_MIRROR=... --build-arg PIP_INDEX_URL=...
ARG APT_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN sed -i \
    -e "s|http://deb.debian.org/debian-security|http://${APT_MIRROR}/debian-security|g" \
    -e "s|http://deb.debian.org/debian|http://${APT_MIRROR}/debian|g" \
    /etc/apt/sources.list.d/debian.sources

ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

# 与本地 `PYTHONPATH=src` 一致：保证 `services`、`middlewares`、`utils` 等同级包可被解析
#（不依赖 editable 安装是否已包含全部包名）
ENV PYTHONPATH=/app/src

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc libpq-dev default-libmysqlclient-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY configs/ ./configs/
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

RUN mkdir -p static

EXPOSE 8888

CMD ["python", "-m", "services.server"]
