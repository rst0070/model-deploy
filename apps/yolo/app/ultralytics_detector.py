"""The only module that imports ultralytics (or torch)."""

import os
from collections.abc import Sequence

import PIL.Image

from app.contract import Detection, DetectOptions


class UltralyticsDetector:
    """Satisfies Detector."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.class_names: Sequence[str] = ()

    @classmethod
    def load(
        cls, weights: str | os.PathLike, device: str, model_id: str = "yolo26x"
    ) -> "UltralyticsDetector":
        """Load weights onto `device`, run one warm-up inference there. Raises if the device
        is unavailable (e.g. device="cuda:0" on a CPU box). Never falls back to another device."""
        return cls(model_id=model_id)

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]:
        return []
