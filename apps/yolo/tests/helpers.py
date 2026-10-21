import io

import httpx
import PIL.Image
from fastapi.testclient import TestClient

from tests.conftest import PEOPLE_JPG


def detect(client: TestClient, image: bytes | None = PEOPLE_JPG.read_bytes(), **fields: str):
    files = {} if image is None else {"image": ("people.jpg", image, "image/jpeg")}
    return client.post("/v1/detect", files=files, data=fields)


def plain_png(width: int = 1280, height: int = 720) -> bytes:
    buf = io.BytesIO()
    PIL.Image.new("RGB", (width, height), (90, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def assert_error(resp: httpx.Response, status: int, code: str) -> dict:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert "Traceback" not in resp.text and "ultralytics" not in resp.text
    return body
