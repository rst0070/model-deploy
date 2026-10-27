"""Request options, results and error codes. No vendor types."""

from dataclasses import dataclass
from enum import StrEnum

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DETECTIONS = 300
MAX_BATCH_IMAGES = 16


@dataclass(frozen=True)
class DetectOptions:
    confidence: float = 0.25  # 0 < confidence <= 1
    classes: tuple[str, ...] | None = None  # None = all classes


@dataclass(frozen=True)
class Box:
    """Original-image pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: Box


@dataclass(frozen=True)
class ImageSize:
    width: int
    height: int


@dataclass(frozen=True)
class DetectResult:
    model: str
    image: ImageSize
    detections: list[Detection]


@dataclass(frozen=True)
class BatchResult:
    model: str
    results: list[DetectResult]  # one per image, in the order the images were sent


class ErrorCode(StrEnum):
    missing_image = "missing_image"
    invalid_image = "invalid_image"
    image_too_large = "image_too_large"
    invalid_option = "invalid_option"
    unknown_class = "unknown_class"
    too_many_images = "too_many_images"
    busy = "busy"


_STATUS: dict[ErrorCode, int] = {
    ErrorCode.missing_image: 422,
    ErrorCode.invalid_image: 422,
    ErrorCode.image_too_large: 413,
    ErrorCode.invalid_option: 422,
    ErrorCode.unknown_class: 422,
    ErrorCode.too_many_images: 422,
    ErrorCode.busy: 429,
}


class DetectError(Exception):
    def __init__(self, code: ErrorCode, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.index = index  # 0-based image of a batch request at fault, if any

    @property
    def status(self) -> int:
        return _STATUS[self.code]
