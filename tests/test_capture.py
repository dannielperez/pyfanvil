from unittest.mock import patch

from pyfanvil.capture import capture_rtsp_frame


def test_capture_rtsp_frame_returns_jpeg_bytes():
    completed = type("Completed", (), {"returncode": 0, "stdout": b"jpeg"})()
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
    assert "secret" not in result.error
