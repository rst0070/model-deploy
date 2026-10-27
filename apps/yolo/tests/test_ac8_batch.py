"""AC-8 of rst0070/rtsp-dashboard#61: POST /v1/detect/batch (test_ac4..7 belong to another issue)."""

from fastapi.testclient import TestClient

from tests.conftest import PEOPLE_JPG
from tests.helpers import assert_error, detect, plain_png

RED = "rst0070/rtsp-dashboard#61 AC-8: /v1/detect/batch not implemented yet"

PEOPLE = PEOPLE_JPG.read_bytes()
TEXT = b"hello, not an image"
OVERSIZED = b"\xff" * (21 * 1024 * 1024)  # over MAX_IMAGE_BYTES (20 MiB)


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "text/plain"


def detect_batch(client: TestClient, images: list[bytes], **fields: str):
    files = [("image", (f"img{i}", data, _mime(data))) for i, data in enumerate(images)]
    return client.post("/v1/detect/batch", files=files, data=fields)


def _assert_batch_equals_singles(client: TestClient, images: list[bytes]) -> None:
    resp = detect_batch(client, images)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"model", "results"}
    assert body["model"] == "yolo26x"
    assert len(body["results"]) == len(images)
    for i, data in enumerate(images):
        single = detect(client, image=data)
        assert single.status_code == 200, single.text
        assert body["results"][i] == single.json(), f"results[{i}] differs from /v1/detect"


def test_ac8_batch_results_equal_single_calls_in_order(real_client):
    _assert_batch_equals_singles(real_client, [PEOPLE, plain_png(), PEOPLE])


def test_ac8_batch_results_equal_single_calls_with_mixed_sizes(real_client):
    # The contract says results[i] equals the single-image answer unconditionally, so a
    # blank of another size than people.jpg (1280x720) must not shift the people boxes.
    _assert_batch_equals_singles(real_client, [PEOPLE, plain_png(320, 240), PEOPLE])


def test_ac8_no_image_is_missing_image(client):
    assert_error(detect_batch(client, [], confidence="0.5"), 422, "missing_image")


def test_ac8_seventeen_images_is_too_many_images(client):
    assert_error(detect_batch(client, [plain_png(32, 32)] * 17), 422, "too_many_images")


def test_ac8_text_file_second_is_invalid_image_index_1(client):
    body = assert_error(detect_batch(client, [PEOPLE, TEXT, PEOPLE]), 422, "invalid_image")
    assert body["error"]["index"] == 1


def test_ac8_oversized_second_is_image_too_large_index_1(client):
    images = [plain_png(32, 32), OVERSIZED, plain_png(32, 32)]
    body = assert_error(detect_batch(client, images), 413, "image_too_large")
    assert body["error"]["index"] == 1


def test_ac8_unknown_class_applies_to_batch(client):
    assert_error(detect_batch(client, [PEOPLE, PEOPLE], classes="unicorn"), 422, "unknown_class")
