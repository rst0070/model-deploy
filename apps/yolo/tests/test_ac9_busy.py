"""AC-9 of rst0070/rtsp-dashboard#61: 429 busy (test_ac4..7 belong to another issue).

YOLO_MAX_WAITING is read when create_app() is called, so each test sets it beforehand."""

import threading
import time
from collections.abc import Callable

import httpx
import PIL.Image
import pytest
from fastapi.testclient import TestClient

from app.contract import Detection, DetectOptions
from app.main import create_app
from tests.conftest import wait_ready
from tests.helpers import assert_error, plain_png

RED = "rst0070/rtsp-dashboard#61 AC-9: 429 busy not implemented yet"

HOLD_LIMIT = 10.0  # seconds; a held detector lets go on its own after this, so nothing hangs
SMALL_PNG = plain_png(64, 64)


class HeldDetector:
    """Blocks inside detect() until `release` is set. `entered` is set once inference starts."""

    def __init__(self) -> None:
        self.model_id = "yolo26x"
        self.class_names = ("person", "bicycle", "car")
        self.entered = threading.Event()
        self.release = threading.Event()

    def detect(self, image: PIL.Image.Image, options: DetectOptions) -> list[Detection]:
        self.entered.set()
        self.release.wait(timeout=HOLD_LIMIT)
        return []


class Sent:
    """One request sent from its own thread; records the response and how long it took."""

    def __init__(self, call: Callable[[], httpx.Response]) -> None:
        self.resp: httpx.Response | None = None
        self.exc: BaseException | None = None
        self.elapsed: float | None = None
        self._call = call
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        start = time.monotonic()
        try:
            self.resp = self._call()
        except BaseException as exc:  # noqa: BLE001 - surfaced through outcome()
            self.exc = exc
        self.elapsed = time.monotonic() - start

    def done(self) -> bool:
        return not self._thread.is_alive()

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)

    def outcome(self) -> str:
        if not self.done():
            return "still waiting"
        if self.exc is not None:
            return repr(self.exc)
        return f"{self.resp.status_code} {self.resp.text}"


def send_detect(client: TestClient) -> httpx.Response:
    return client.post("/v1/detect", files={"image": ("a.png", SMALL_PNG, "image/png")})


def send_batch(client: TestClient) -> httpx.Response:
    files = [("image", (f"img{i}.png", SMALL_PNG, "image/png")) for i in range(2)]
    return client.post("/v1/detect/batch", files=files)


ENDPOINTS = pytest.mark.parametrize("send", [send_detect, send_batch], ids=["detect", "batch"])


def _assert_busy(sent: Sent) -> None:
    sent.join(1.0)
    assert sent.done(), "request was held instead of being answered within 1 s"
    assert sent.exc is None, repr(sent.exc)
    assert sent.elapsed < 1.0
    assert_error(sent.resp, 429, "busy")
    retry_after = sent.resp.headers.get("Retry-After")
    assert retry_after is not None and retry_after.isdigit(), retry_after
    assert int(retry_after) >= 1


def _assert_ok(sent: Sent) -> None:
    assert sent.done(), "held request never finished"
    assert sent.exc is None, repr(sent.exc)
    assert sent.resp.status_code == 200, sent.resp.text


def _refused_after_waiting(monkeypatch, max_waiting: str | None, waiting: int, send) -> None:
    """Hold one request inside inference, queue `waiting` more, then expect the next one to be
    refused busy at once, and every held request to finish 200 once inference is released."""
    if max_waiting is None:
        monkeypatch.delenv("YOLO_MAX_WAITING", raising=False)
    else:
        monkeypatch.setenv("YOLO_MAX_WAITING", max_waiting)
    detector = HeldDetector()
    app = create_app(lambda: detector)
    with TestClient(app) as client:
        wait_ready(client, timeout=5)
        held: list[Sent] = []
        try:
            first = Sent(lambda: send(client))
            held.append(first)
            reached = detector.entered.wait(2.0)
            assert reached, f"request 1 never reached inference: {first.outcome()}"
            for _ in range(waiting):
                held.append(Sent(lambda: send(client)))
            time.sleep(0.3)  # let the waiting requests reach the wait for the model
            for i, sent in enumerate(held):
                assert not sent.done(), f"request {i + 1} answered while held: {sent.outcome()}"
            extra = Sent(lambda: send(client))
            held.append(extra)
            _assert_busy(extra)
        finally:
            detector.release.set()
            for sent in held:
                sent.join(HOLD_LIMIT)
        for sent in held[:-1]:
            _assert_ok(sent)


@ENDPOINTS
def test_ac9_request_beyond_max_waiting_is_busy(monkeypatch, send):
    _refused_after_waiting(monkeypatch, "1", waiting=1, send=send)


def test_ac9_default_max_waiting_is_8(monkeypatch):
    # Env unset: 1 in inference plus 8 waiting are all served; only the 10th is refused.
    _refused_after_waiting(monkeypatch, None, waiting=8, send=send_detect)
