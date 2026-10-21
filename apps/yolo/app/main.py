"""HTTP shell: POST /v1/detect, GET /health. Run with `python -m app.main`."""

import os
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI

from app.detector import Detector
from app.ultralytics_detector import UltralyticsDetector


def create_app(load_detector: Callable[[], Detector]) -> FastAPI:
    """`load_detector` runs in a background thread when the app starts (lifespan).
    GET /health -> 503 {"status": "loading"} until it has returned, then 200
    {"status": "ok", "model": <model_id>}. If it raises, /health is 503 {"status": "failed"}
    and never 200 again; main() turns that into a non-zero process exit.
    POST /v1/detect -> 503 {"error": {"code": "not_ready", ...}} while loading."""
    return FastAPI()


def main() -> None:
    """Entry for `python -m app.main`. Env: YOLO_DEVICE (default "cuda:0"),
    YOLO_WEIGHTS (default "yolo26x.pt"), YOLO_MODEL_ID (default "yolo26x"), PORT (8000)."""
    device = os.environ.get("YOLO_DEVICE", "cuda:0")
    weights = os.environ.get("YOLO_WEIGHTS", "yolo26x.pt")
    model_id = os.environ.get("YOLO_MODEL_ID", "yolo26x")
    app = create_app(lambda: UltralyticsDetector.load(weights, device, model_id))
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
