import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FakeDetector, wait_ready
from tests.helpers import detect

APP_DIR = Path(__file__).parents[1]


def test_ac7_health_is_503_until_weights_are_loaded():
    loaded = threading.Event()

    def load():
        loaded.wait()
        return FakeDetector()

    with TestClient(create_app(load)) as c:
        resp = c.get("/health")
        assert resp.status_code == 503, resp.text
        assert resp.json() == {"status": "loading"}
        loaded.set()
        wait_ready(c, timeout=5)
        resp = c.get("/health")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok", "model": "yolo26x"}


def test_ac7_detect_is_503_not_ready_while_loading():
    release = threading.Event()
    try:
        with TestClient(create_app(lambda: release.wait() and FakeDetector())) as c:
            resp = detect(c)
            assert resp.status_code == 503, resp.text
            assert resp.json()["error"]["code"] == "not_ready"
    finally:
        release.set()


def test_ac7_health_is_503_failed_when_load_raises():
    def load():
        raise RuntimeError("device unavailable")

    with TestClient(create_app(load)) as c:
        wait_ready(c, timeout=5)
        resp = c.get("/health")
        assert resp.status_code == 503, resp.text
        assert resp.json() == {"status": "failed"}


def test_ac7_unavailable_device_exits_nonzero_and_never_healthy():
    torch = pytest.importorskip("torch")
    if torch.cuda.is_available():
        pytest.skip("this box has a GPU; cuda:0 is available")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "YOLO_DEVICE": "cuda:0", "YOLO_WEIGHTS": "yolo26x.pt", "PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], env=env, cwd=APP_DIR)
    saw_200, answered_at, exited = False, None, False
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                exited = True
                break
            try:
                saw_200 |= (
                    httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200
                )
                answered_at = answered_at or time.monotonic()
            except httpx.HTTPError:
                pass
            # Once the server answers at all, a failed load must turn into an exit promptly.
            if answered_at and time.monotonic() - answered_at > 15:
                break
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert exited, "process kept serving instead of exiting at startup"
    assert proc.returncode != 0
    assert not saw_200


def test_ac7_only_the_adapter_imports_the_vendor():
    vendor = re.compile(r"^\s*(?:from|import)\s+(?:ultralytics|torch)\b", re.MULTILINE)
    offenders = [p.name for p in (APP_DIR / "app").glob("*.py") if vendor.search(p.read_text())]
    assert set(offenders) <= {"ultralytics_detector.py"}, offenders
