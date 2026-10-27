"""The Detector port: image + options -> detections."""

from collections.abc import Sequence
from typing import Protocol

import PIL.Image

from app.contract import Detection, DetectOptions


class Detector(Protocol):
    model_id: str  # e.g. "yolo26x"
    class_names: Sequence[str]  # the model's label names, in class-id order

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]: ...


class BatchDetector(Detector, Protocol):
    """A Detector that can run several images in one inference."""

    def detect_batch(
        self, images: Sequence[PIL.Image.Image], options: DetectOptions
    ) -> list[list[Detection]]:
        """One list per image, in order; each equals detect(image, options)."""
        ...


def detect_each(
    detector: Detector, images: Sequence[PIL.Image.Image], options: DetectOptions
) -> list[list[Detection]]:
    """The detector's own batch call when it has one, else one detect() per image."""
    detect_batch = getattr(detector, "detect_batch", None)
    if detect_batch is not None:
        return detect_batch(images, options)
    return [detector.detect(image, options) for image in images]
