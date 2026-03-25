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
        gcc libpq-dev default-libmysqlclient-dev poppler-utils \
        libglib2.0-0 libgomp1 \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY configs/ ./configs/
COPY src/ ./src/

# unstructured-inference 在 PyPI 上依赖 opencv-python；与 headless 并存时卸载 GUI 版易把 cv2 弄丢，故先卸再只装 headless
RUN pip install --no-cache-dir -e . && \
    pip uninstall -y opencv-python opencv-python-headless 2>/dev/null || true && \
    pip install --no-cache-dir "opencv-python-headless>=4.13.0.90" && \
    python -c "import cv2; print('cv2', cv2.__version__)" && \
    python -c "import unstructured_pytesseract; import shutil; assert shutil.which('tesseract'), 'tesseract binary missing'"

# YOLOX 布局模型（与 rich_document_parser 默认路径 /app/llm_model/mms/yolo_x_layout 一致）
COPY llm_model/mms/yolo_x_layout/ /app/llm_model/mms/yolo_x_layout/

RUN mkdir -p static

EXPOSE 8888

CMD ["python", "-m", "services.server"]
