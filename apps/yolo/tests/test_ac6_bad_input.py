from tests.helpers import assert_error, detect


def test_ac6_text_file_is_invalid_image(client):
    resp = client.post(
        "/v1/detect", files={"image": ("note.txt", b"hello, not an image", "text/plain")}
    )
    assert_error(resp, 422, "invalid_image")


def test_ac6_no_image_field_is_missing_image(client):
    assert_error(detect(client, image=None, confidence="0.5"), 422, "missing_image")


def test_ac6_oversized_upload_is_image_too_large(client):
    assert_error(detect(client, image=b"\xff" * (21 * 1024 * 1024)), 413, "image_too_large")
