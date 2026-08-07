from unittest.mock import patch

from pyfanvil.capture import MAX_FRAME_BYTES, capture_rtsp_frame


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
