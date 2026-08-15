import time
from unittest.mock import patch

import httpx
import pytest

from pyfanvil.capture import (
    MAX_FRAME_BYTES,
    capture_http_preview_frame,
    capture_rtsp_frame,
)


def test_capture_rtsp_frame_returns_jpeg_bytes():
    completed = type(
        "Completed",
        (),
        {"returncode": 0, "stdout": b"jpeg", "stderr": b""},
    )()
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("pyfanvil.capture.subprocess.run", return_value=completed) as run,
    ):
        result = capture_rtsp_frame("rtsp://user:pass@example.invalid/confirmed")

    assert result.ok is True
    assert result.image_bytes == b"jpeg"
    assert run.call_args.kwargs["timeout"] == 10


def test_capture_rtsp_frame_degrades_when_ffmpeg_is_missing():
    with patch("pyfanvil.capture.shutil.which", return_value=None):
        result = capture_rtsp_frame("rtsp://example.invalid/confirmed")

    assert result.ok is False
    assert result.error == "ffmpeg is not installed"


def test_capture_rtsp_frame_returns_sanitized_timeout():
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch(
            "pyfanvil.capture.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired("ffmpeg", 10),
        ),
    ):
        result = capture_rtsp_frame("rtsp://user:secret@example.invalid/confirmed")

    assert result.ok is False
    assert result.error == "RTSP frame capture timed out"
    assert result.error_kind == "timeout"
    assert "secret" not in result.error


def test_capture_rtsp_frame_classifies_authentication_without_exposing_diagnostics():
    completed = type(
        "Completed",
        (),
        {
            "returncode": 1,
            "stdout": b"",
            "stderr": b"method DESCRIBE failed: 401 Unauthorized password=secret",
        },
    )()
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("pyfanvil.capture.subprocess.run", return_value=completed),
    ):
        result = capture_rtsp_frame("rtsp://user:secret@example.invalid/confirmed")

    assert result.error_kind == "authentication"
    assert result.error == "RTSP authentication failed"
    assert "secret" not in result.error


def test_capture_rtsp_frame_classifies_missing_path():
    completed = type(
        "Completed",
        (),
        {"returncode": 1, "stdout": b"", "stderr": b"404 Not Found"},
    )()
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("pyfanvil.capture.subprocess.run", return_value=completed),
    ):
        result = capture_rtsp_frame("rtsp://example.invalid/wrong")

    assert result.error_kind == "path"
    assert result.error == "RTSP stream path was not found"


def test_capture_rtsp_frame_degrades_when_ffmpeg_cannot_spawn():
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("pyfanvil.capture.subprocess.run", side_effect=OSError("spawn failed")),
    ):
        result = capture_rtsp_frame("rtsp://example.invalid/confirmed")

    assert result.error_kind == "unavailable"
    assert result.error == "RTSP capture process is unavailable"


def test_capture_rtsp_frame_rejects_oversized_output():
    completed = type(
        "Completed",
        (),
        {
            "returncode": 0,
            "stdout": b"x" * (MAX_FRAME_BYTES + 1),
            "stderr": b"",
        },
    )()
    with (
        patch("pyfanvil.capture.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("pyfanvil.capture.subprocess.run", return_value=completed) as run,
    ):
        result = capture_rtsp_frame("rtsp://example.invalid/confirmed")

    assert result.error_kind == "oversized"
    assert result.image_bytes == b""
    assert str(MAX_FRAME_BYTES + 1) in run.call_args.args[0]


def _transport(handler):
    return httpx.MockTransport(handler)


def test_capture_http_preview_extracts_first_digest_authenticated_jpeg():
    requests = []

    def handler(request):
        requests.append(request)
        if "Authorization" not in request.headers:
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Digest realm="fanvil", nonce="abc", qop="auth", algorithm=MD5'
                    ),
                },
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"},
            stream=httpx.ByteStream(
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                b"\xff\xd8first\xff\xd9\r\n--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n\xff\xd8second\xff\xd9"
            ),
        )

    result = capture_http_preview_frame(
        "192.0.2.10",
        "camera-user",
        "camera-password",
        timeout=1,
        _transport=_transport(handler),
    )

    assert result.ok is True
    assert result.image_bytes == b"\xff\xd8first\xff\xd9"
    assert result.content_type == "multipart/x-mixed-replace"
    assert requests[-1].url == httpx.URL("http://192.0.2.10/cgi-bin/video?")
    assert "camera-password" not in str(requests[-1].url)


def test_capture_http_preview_supports_explicit_basic_auth():
    def handler(request):
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, stream=httpx.ByteStream(b"\xff\xd8jpeg\xff\xd9"))

    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        auth_mode="basic",
        timeout=1,
        _transport=_transport(handler),
    )

    assert result.ok is True
    assert result.image_bytes == b"\xff\xd8jpeg\xff\xd9"


@pytest.mark.parametrize("status", [401, 403])
def test_capture_http_preview_classifies_authentication(status):
    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        timeout=1,
        _transport=_transport(lambda _request: httpx.Response(status)),
    )

    assert result.ok is False
    assert result.error_kind == "authentication"
    assert "secret" not in result.error


def test_capture_http_preview_rejects_non_jpeg_stream():
    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        auth_mode="basic",
        timeout=1,
        _transport=_transport(
            lambda _request: httpx.Response(
                200,
                stream=httpx.ByteStream(b"raw h264 stream"),
            ),
        ),
    )

    assert result.ok is False
    assert result.error_kind == "invalid_image"


def test_capture_http_preview_bounds_first_frame_bytes():
    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        auth_mode="basic",
        timeout=1,
        max_bytes=1024,
        _transport=_transport(
            lambda _request: httpx.Response(
                200,
                stream=httpx.ByteStream(
                    b"\xff\xd8" + (b"x" * 1024) + b"\xff\xd9",
                ),
            ),
        ),
    )

    assert result.ok is False
    assert result.error_kind == "image_too_large"


def test_capture_http_preview_rejects_jpeg_after_oversized_preamble():
    oversized_preamble = b"x" * (64 * 1024 + 1)

    def handler(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            stream=httpx.ByteStream(oversized_preamble + b"\xff\xd8small\xff\xd9"),
        )

    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        auth_mode="basic",
        timeout=1,
        _transport=_transport(handler),
    )

    assert result.ok is False
    assert result.error_kind == "invalid_image"


def test_capture_http_preview_stops_a_drip_fed_stream_at_total_deadline():
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.03)
            yield b"\xff\xd8partial"

    result = capture_http_preview_frame(
        "camera.local",
        "user",
        "secret",
        auth_mode="basic",
        timeout=0.02,
        _transport=_transport(
            lambda _request: httpx.Response(200, stream=SlowStream()),
        ),
    )

    assert result.ok is False
    assert result.error_kind == "timeout"


def test_capture_http_preview_validates_endpoint_inputs():
    with pytest.raises(ValueError, match="host"):
        capture_http_preview_frame("http://camera.local", "user", "secret")
    with pytest.raises(ValueError, match="credentials"):
        capture_http_preview_frame("camera.local", "", "")
