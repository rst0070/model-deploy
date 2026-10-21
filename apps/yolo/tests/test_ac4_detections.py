import pytest

from app.contract import MAX_DETECTIONS
from tests.helpers import detect, plain_png

pytestmark = pytest.mark.xfail(strict=True, reason="AC-4 not implemented")


def test_ac4_response_echoes_detector_result(client):
    resp = detect(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "yolo26x"
    assert body["image"] == {"width": 1280, "height": 720}
    assert body["detections"] == [
        {
            "label": "person",
            "confidence": 0.91,
            "box": {"x1": 412.0, "y1": 88.5, "x2": 655.2, "y2": 710.0},
        },
        {
            "label": "car",
            "confidence": 0.40,
            "box": {"x1": 10.0, "y1": 20.0, "x2": 30.5, "y2": 40.0},
        },
    ]


def test_ac4_people_fixture_detections_are_sound(real_client):
    resp = detect(real_client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image"] == {"width": 1280, "height": 720}
    dets = body["detections"]
    assert 1 <= len(dets) <= MAX_DETECTIONS
    for d in dets:
        b = d["box"]
        assert 0 <= b["x1"] < b["x2"] <= 1280
        assert 0 <= b["y1"] < b["y2"] <= 720
        assert 0 < d["confidence"] <= 1
    confs = [d["confidence"] for d in dets]
    assert confs == sorted(confs, reverse=True)
    assert "person" in {d["label"] for d in dets}


def test_ac4_plain_image_has_no_detections(real_client):
    resp = detect(real_client, image=plain_png())
    assert resp.status_code == 200, resp.text
    assert resp.json()["detections"] == []
