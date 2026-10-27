"""HTTP shell: POST /v1/detect(/batch), GET /health. Run with `python -m app.main`."""

import io
import os
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from typing import Annotated

import PIL.Image
import PIL.ImageFile
import PIL.JpegImagePlugin
import PIL.PngImagePlugin
import PIL.WebPImagePlugin
import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contract import (
    MAX_BATCH_IMAGES,
    MAX_IMAGE_BYTES,
    BatchResult,
    DetectError,
    DetectOptions,
    DetectResult,
    ErrorCode,
    ImageSize,
)
from app.detector import Detector, detect_each
from app.ultralytics_detector import UltralyticsDetector

BUSY_RETRY_AFTER_S = 1  # an inference takes well under a second, so the wait clears by then


def _error(
    status: int,
    code: str,
    message: str,
    index: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict = {"code": code, "message": message}
    if index is not None:
        error["index"] = index
    return JSONResponse({"error": error}, status_code=status, headers=headers)


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
        im = plugin(io.BytesIO(data))  # header only, nothing decoded yet
    except Exception:  # noqa: BLE001 - decoder errors on untrusted bytes are a zoo
        raise DetectError(
            ErrorCode.invalid_image, "image must be a decodable JPEG, PNG or WebP"
        ) from None
    # Constructing the plugin bypasses the decompression-bomb check Image.open would run, so
    # reject on the header-declared size before .convert allocates width*height*3 bytes.
    width, height = im.size
    max_pixels = PIL.Image.MAX_IMAGE_PIXELS
    if max_pixels is not None and width * height > max_pixels:
        raise DetectError(ErrorCode.invalid_image, "image has too many pixels")
    try:
        return im.convert("RGB")
    except Exception:  # noqa: BLE001
        raise DetectError(
            ErrorCode.invalid_image, "image must be a decodable JPEG, PNG or WebP"
        ) from None


def _read_image(upload: UploadFile) -> PIL.Image.Image:
    data = upload.file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise DetectError(ErrorCode.image_too_large, f"image exceeds {MAX_IMAGE_BYTES} bytes")
    return _open_image(data)


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
    POST /v1/detect(/batch) -> 503 {"error": {"code": "not_ready", ...}} while loading, and
    429 busy once YOLO_MAX_WAITING (env, read here, default 8) requests already wait for the
    model behind the one in inference."""
    state: dict = {"detector": None, "failed": False, "waiting": 0}
    max_waiting = int(os.environ.get("YOLO_MAX_WAITING", "8"))
    infer_lock = threading.Lock()  # one model, one inference at a time
    waiting_lock = threading.Lock()  # guards state["waiting"]

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

    @contextmanager
    def model_turn() -> Iterator[None]:
        """Hold the model for one inference. Refuse busy at once, without waiting for the
        model, when max_waiting requests are already waiting for it."""
        with waiting_lock:
            free = infer_lock.acquire(blocking=False)
            if not free:
                if state["waiting"] >= max_waiting:
                    raise DetectError(ErrorCode.busy, "model is busy; retry later")
                state["waiting"] += 1
        if not free:
            infer_lock.acquire()
            with waiting_lock:
                state["waiting"] -= 1
        try:
            yield
        finally:
            infer_lock.release()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(DetectError)
    async def detect_error(_: Request, exc: DetectError) -> JSONResponse:
        headers = {"Retry-After": str(BUSY_RETRY_AFTER_S)} if exc.code == ErrorCode.busy else None
        return _error(exc.status, exc.code, exc.message, exc.index, headers)

    @app.exception_handler(RequestValidationError)
    async def multipart_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep the Contract's error shape and never echo FastAPI's `detail` (it can carry the
        # rejected input, including a SpooledTemporaryFile repr).
        errors = exc.errors()
        loc = tuple(errors[0].get("loc", ())) if errors else ()
        # ("body", field), or ("body", "image", index) for a batch's repeated image fields.
        field = loc[1] if len(loc) > 1 else None
        if field == "image":
            index = loc[2] if len(loc) > 2 and isinstance(loc[2], int) else None
            return _error(
                422, ErrorCode.invalid_image, "multipart field 'image' must be a file", index
            )
        if field in ("confidence", "classes"):
            return _error(422, ErrorCode.invalid_option, f"multipart field '{field}' must be text")
        return _error(422, ErrorCode.invalid_option, "malformed multipart request")

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
        pil_image = _read_image(image)
        options = _parse_options(confidence, classes, detector.class_names)
        with model_turn():
            detections = detector.detect(pil_image, options)
        result = DetectResult(detector.model_id, ImageSize(*pil_image.size), detections)
        return asdict(result)

    @app.post("/v1/detect/batch")
    def detect_batch(
        image: Annotated[list[UploadFile] | None, File()] = None,
        confidence: Annotated[str, Form()] = "0.25",
        classes: Annotated[str | None, Form()] = None,
    ):
        detector = state["detector"]
        if detector is None:
            why = "model failed to load" if state["failed"] else "model is loading"
            return _error(503, "not_ready", why)
        if not image:
            raise DetectError(ErrorCode.missing_image, "multipart field 'image' is required")
        if len(image) > MAX_BATCH_IMAGES:
            raise DetectError(
                ErrorCode.too_many_images, f"at most {MAX_BATCH_IMAGES} 'image' fields per request"
            )
        pil_images: list[PIL.Image.Image] = []
        for index, upload in enumerate(image):
            try:
                pil_images.append(_read_image(upload))
            except DetectError as exc:
                raise DetectError(exc.code, exc.message, index) from None
        options = _parse_options(confidence, classes, detector.class_names)
        with model_turn():
            per_image = detect_each(detector, pil_images, options)
        results = [
            DetectResult(detector.model_id, ImageSize(*im.size), detections)
            for im, detections in zip(pil_images, per_image, strict=True)
        ]
        return asdict(BatchResult(detector.model_id, results))

    return app


def main() -> None:
    """Entry for `python -m app.main`. Env: YOLO_DEVICE (default "cuda:0"),
    YOLO_WEIGHTS (default "yolo26x.pt"), YOLO_MODEL_ID (default "yolo26x"), PORT (8000),
    YOLO_MAX_WAITING (default 8: requests that may wait for the model before 429 busy).
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
