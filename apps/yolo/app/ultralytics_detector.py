"""The only module that imports ultralytics (or torch)."""

import os
from collections.abc import Sequence

import PIL.Image
import torch
from ultralytics import YOLO

from app.contract import MAX_DETECTIONS, Box, Detection, DetectOptions


class UltralyticsDetector:
    """Satisfies Detector. Turns the vendor result into contract Detections."""

    def __init__(self, model: YOLO, device: str, model_id: str) -> None:
        self._model = model
        self._device = device
        self.model_id = model_id
        self.class_names: Sequence[str] = [model.names[i] for i in range(len(model.names))]

    @classmethod
    def load(
        cls, weights: str | os.PathLike, device: str, model_id: str = "yolo26x"
    ) -> "UltralyticsDetector":
        """Load weights onto `device`, run one warm-up inference there. Raises if the device
        is unavailable (e.g. device="cuda:0" on a CPU box). Never falls back to another device."""
        # Prove the device works before any weights are read or downloaded.
        torch.zeros(1).to(torch.device(device))
        model = YOLO(str(weights))
        model.to(device)
        detector = cls(model, device, model_id)
        detector.detect(PIL.Image.new("RGB", (640, 640)), DetectOptions())  # warm-up
        return detector

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]:
        class_ids = None
        if options.classes is not None:
            class_ids = [self.class_names.index(name) for name in options.classes]
        result = self._model.predict(
            image,
            conf=options.confidence,
            classes=class_ids,
            device=self._device,
            verbose=False,
        )[0]
        width, height = image.size
        detections: list[Detection] = []
        boxes = result.boxes
        # xyxy is already in original-image pixels; clamp defensively to the image bounds.
        for (x1, y1, x2, y2), conf, cls in zip(
            boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), strict=True
        ):
            box = Box(
                x1=min(max(x1, 0.0), width),
                y1=min(max(y1, 0.0), height),
                x2=min(max(x2, 0.0), width),
                y2=min(max(y2, 0.0), height),
            )
            if box.x1 < box.x2 and box.y1 < box.y2:
                detections.append(Detection(self.class_names[int(cls)], float(conf), box))
        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections[:MAX_DETECTIONS]
