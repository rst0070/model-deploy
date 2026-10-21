"""HTTP shell: POST /v1/detect, GET /health. Run with `python -m app.main`."""

import io
import os
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

import PIL.Image
import PIL.ImageFile
import PIL.JpegImagePlugin
import PIL.PngImagePlugin
import PIL.WebPImagePlugin
import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.contract import (
    MAX_IMAGE_BYTES,
    DetectError,
    DetectOptions,
    DetectResult,
    ErrorCode,
    ImageSize,
)
from app.detector import Detector
from app.ultralytics_detector import UltralyticsDetector


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _image_plugin(data: bytes) -> type[PIL.ImageFile.ImageFile] | None:
    if data[:3] == b"\xff\xd8\xff":
        return PIL.JpegImagePlugin.JpegImageFile
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return PIL.PngImagePlugin.PngImageFile
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return PIL.WebPImagePlugin.WebPImageFile
    return None


def _open_image(data: bytes) -> PIL.Image.Image:
    # Decode via the format plugin, not PIL.Image.open: ultralytics monkey-patches Image.open
    # to pip-install a HEIF plugin whenever Pillow cannot identify a file.
    plugin = _image_plugin(data)
    try:
        if plugin is None:
            raise ValueError("unsupported format")
        return plugin(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 - decoder errors on untrusted bytes are a zoo
        raise DetectError(
            ErrorCode.invalid_image, "image must be a decodable JPEG, PNG or WebP"
        ) from None


def _parse_options(confidence: str, classes: str | None, names: Sequence[str]) -> DetectOptions:
    try:
        conf = float(confidence)
    except ValueError:
        conf = float("nan")
    if not 0 < conf <= 1:
        raise DetectError(ErrorCode.invalid_option, "confidence must be a number in (0, 1]")
    if classes is None:
        return DetectOptions(confidence=conf)
    labels = tuple(label.strip() for label in classes.split(",") if label.strip())
    unknown = [label for label in labels if label not in names]
    if unknown:
        raise DetectError(
            ErrorCode.unknown_class,
            f"unknown classes {', '.join(unknown)}; valid classes: {', '.join(names)}",
        )
    return DetectOptions(confidence=conf, classes=labels or None)


def create_app(
    load_detector: Callable[[], Detector],
    on_load_failure: Callable[[BaseException], None] | None = None,
) -> FastAPI:
    """`load_detector` runs in a background thread when the app starts (lifespan).
    GET /health -> 503 {"status": "loading"} until it has returned, then 200
    {"status": "ok", "model": <model_id>}. If it raises, /health is 503 {"status": "failed"}
    and never 200 again; main() turns that into a non-zero process exit via `on_load_failure`.
    POST /v1/detect -> 503 {"error": {"code": "not_ready", ...}} while loading."""
    state: dict = {"detector": None, "failed": False}
    infer_lock = threading.Lock()  # one model, one inference at a time

    def load() -> None:
        try:
            state["detector"] = load_detector()
        except BaseException as exc:  # noqa: BLE001 - any failure must become "failed"
            state["failed"] = True
            if on_load_failure is not None:
                on_load_failure(exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Daemon and never joined: a stuck loader must not block shutdown.
        threading.Thread(target=load, daemon=True).start()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(DetectError)
    async def detect_error(_: Request, exc: DetectError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        return _error(500, "internal_error", "internal error")

    @app.get("/health")
    async def health():
        if state["failed"]:
            return JSONResponse({"status": "failed"}, status_code=503)
        detector = state["detector"]
        if detector is None:
            return JSONResponse({"status": "loading"}, status_code=503)
        return {"status": "ok", "model": detector.model_id}

    @app.post("/v1/detect")
    def detect(
        image: Annotated[UploadFile | None, File()] = None,
        confidence: Annotated[str, Form()] = "0.25",
        classes: Annotated[str | None, Form()] = None,
    ):
        detector = state["detector"]
        if detector is None:
            why = "model failed to load" if state["failed"] else "model is loading"
            return _error(503, "not_ready", why)
        if image is None:
            raise DetectError(ErrorCode.missing_image, "multipart field 'image' is required")
        data = image.file.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise DetectError(ErrorCode.image_too_large, f"image exceeds {MAX_IMAGE_BYTES} bytes")
        pil_image = _open_image(data)
        options = _parse_options(confidence, classes, detector.class_names)
        with infer_lock:
            detections = detector.detect(pil_image, options)
        result = DetectResult(detector.model_id, ImageSize(*pil_image.size), detections)
        return asdict(result)

    return app


def main() -> None:
    """Entry for `python -m app.main`. Env: YOLO_DEVICE (default "cuda:0"),
    YOLO_WEIGHTS (default "yolo26x.pt"), YOLO_MODEL_ID (default "yolo26x"), PORT (8000).
    A detector load failure ends the process with exit code 1."""
    device = os.environ.get("YOLO_DEVICE", "cuda:0")
    weights = os.environ.get("YOLO_WEIGHTS", "yolo26x.pt")
    model_id = os.environ.get("YOLO_MODEL_ID", "yolo26x")

    def exit_on_failure(exc: BaseException) -> None:
        print(f"detector load failed on {device}: {exc!r}", file=sys.stderr, flush=True)
        os._exit(1)

    app = create_app(lambda: UltralyticsDetector.load(weights, device, model_id), exit_on_failure)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
