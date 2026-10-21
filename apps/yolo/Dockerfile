# One image = one model: the yolo26x weights are baked in at build time and the engine never
# downloads at runtime. Every package comes from apps/yolo/uv.lock, the same lock the tests run
# against; the only difference is the torch build (`cu126` extra here, `cpu` in tests).
FROM ghcr.io/astral-sh/uv:0.7.21-python3.11-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    YOLO_CONFIG_DIR=/tmp/ultralytics

# opencv (pulled in by ultralytics) needs libGL and glib at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# --frozen fails the build if uv.lock is out of date with pyproject.toml.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra cu126 && rm -rf /root/.cache/uv
ENV PATH=/app/.venv/bin:$PATH

ADD https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt /app/weights/yolo26x.pt
COPY app ./app

ENV YOLO_WEIGHTS=/app/weights/yolo26x.pt \
    YOLO_DEVICE=cuda:0 \
    YOLO_MODEL_ID=yolo26x

EXPOSE 8000
CMD ["python", "-m", "app.main"]
