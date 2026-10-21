import time
from collections.abc import Sequence
from pathlib import Path

import PIL.Image
import pytest
from fastapi.testclient import TestClient

pytest.register_assert_rewrite("tests.helpers")

from app.contract import Box, Detection, DetectOptions
from app.main import create_app
from app.ultralytics_detector import UltralyticsDetector

PEOPLE_JPG = Path(__file__).parent / "fixtures" / "people.jpg"

# Known numbers (first entry is the spec's own example) so shape tests can assert an exact echo.
CANNED = [
    Detection("person", 0.91, Box(412.0, 88.5, 655.2, 710.0)),
    Detection("car", 0.40, Box(10.0, 20.0, 30.5, 40.0)),
]


class FakeDetector:
    """Returns its canned list whatever the options are: the shell trusts the port."""

    def __init__(
        self,
        model_id: str = "yolo26x",
        class_names: Sequence[str] = ("person", "bicycle", "car"),
        detections: list[Detection] = CANNED,
    ) -> None:
        self.model_id = model_id
        self.class_names = class_names
        self.detections = detections

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]:
        return list(self.detections)


def wait_ready(client: TestClient, timeout: float) -> None:
    """Poll /health while it says 503 (loading). Any other answer ends the wait, so tests fail
    on their own assertions rather than on this fixture."""
    deadline = time.monotonic() + timeout
    while client.get("/health").status_code == 503 and time.monotonic() < deadline:
        time.sleep(0.05)


@pytest.fixture
def fake_detector() -> FakeDetector:
    return FakeDetector()


@pytest.fixture
def client(fake_detector: FakeDetector):
    with TestClient(create_app(lambda: fake_detector)) as c:
        wait_ready(c, timeout=5)
        yield c


@pytest.fixture(scope="session")
def real_detector() -> UltralyticsDetector:
    return UltralyticsDetector.load("yolo26x.pt", "cpu")


@pytest.fixture(scope="session")
def real_client(real_detector: UltralyticsDetector):
    with TestClient(create_app(lambda: real_detector)) as c:
        wait_ready(c, timeout=120)
        yield c
