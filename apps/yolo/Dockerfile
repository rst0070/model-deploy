# One image = one model: the yolo26x weights are baked in at build time and the engine never
# downloads at runtime. CUDA torch comes from the base image; the uv.lock pins CPU torch on
# Linux for tests and is deliberately not used here.
FROM pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime

# The base image's Python is Ubuntu's (PEP 668); torch already lives in its dist-packages.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics

# opencv (pulled in by ultralytics) needs libGL and glib at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Same ultralytics pin and the same major versions as apps/yolo/uv.lock.
RUN pip install --no-cache-dir \
    "ultralytics==8.4.183" \
    "fastapi>=0.156,<1" \
    "uvicorn>=0.54,<1" \
    "python-multipart>=0.0.32,<0.1" \
    "pillow>=13,<14"

WORKDIR /app
ADD https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt /app/weights/yolo26x.pt
COPY app ./app

ENV YOLO_WEIGHTS=/app/weights/yolo26x.pt \
    YOLO_DEVICE=cuda:0 \
    YOLO_MODEL_ID=yolo26x

EXPOSE 8000
CMD ["python", "-m", "app.main"]
