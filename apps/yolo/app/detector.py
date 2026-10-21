"""The Detector port: image + options -> detections."""

from collections.abc import Sequence
from typing import Protocol

import PIL.Image

from app.contract import Detection, DetectOptions


class Detector(Protocol):
    model_id: str  # e.g. "yolo26x"
    class_names: Sequence[str]  # the model's label names, in class-id order

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]: ...
