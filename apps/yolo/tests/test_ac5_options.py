import pytest

from tests.helpers import assert_error, detect

pytestmark = pytest.mark.xfail(strict=True, reason="AC-5 not implemented")


def test_ac5_confidence_threshold_filters(real_client):
    resp = detect(real_client, confidence="0.9")
    assert resp.status_code == 200, resp.text
    assert all(d["confidence"] >= 0.9 for d in resp.json()["detections"])


def test_ac5_classes_restricts_labels(real_client):
    resp = detect(real_client, classes="person")
    assert resp.status_code == 200, resp.text
    labels = [d["label"] for d in resp.json()["detections"]]
    assert labels and set(labels) == {"person"}


def test_ac5_unknown_class_is_422(client, fake_detector):
    body = assert_error(detect(client, classes="unicorn"), 422, "unknown_class")
    for name in fake_detector.class_names:
        assert name in body["error"]["message"]


def test_ac5_confidence_out_of_range_is_422(client):
    assert_error(detect(client, confidence="1.5"), 422, "invalid_option")


def test_ac5_confidence_not_a_number_is_422(client):
    assert_error(detect(client, confidence="high"), 422, "invalid_option")
