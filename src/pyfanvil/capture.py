"""Bounded RTSP frame capture for Fanvil device-owned camera streams."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

MAX_FRAME_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RTSPFrame:
    """Typed result for one single-frame RTSP capture attempt."""

    ok: bool
    image_bytes: bytes = b""
    error: str = ""
    error_kind: str = ""


def _capture_failure(stderr: bytes) -> RTSPFrame:
    """Map ffmpeg diagnostics to bounded, credential-free failure kinds."""
    diagnostic = stderr.decode("utf-8", errors="ignore").lower()
    if "401 unauthorized" in diagnostic or "authentication" in diagnostic:
        return RTSPFrame(
            ok=False,
            error="RTSP authentication failed",
            error_kind="authentication",
        )
    if "404 not found" in diagnostic or "method describe failed: 404" in diagnostic:
        return RTSPFrame(
            ok=False,
            error="RTSP stream path was not found",
            error_kind="path",
        )
    if "timed out" in diagnostic or "timeout" in diagnostic:
        return RTSPFrame(
            ok=False,
            error="RTSP frame capture timed out",
            error_kind="timeout",
        )
    return RTSPFrame(
        ok=False,
        error="RTSP frame capture failed",
        error_kind="capture_failed",
    )


def capture_rtsp_frame(rtsp_url: str, *, timeout: int = 5) -> RTSPFrame:
    """Capture one JPEG frame with ffmpeg without logging the credential URL."""
    timeout = max(1, min(timeout, 30))
    if not shutil.which("ffmpeg"):
        return RTSPFrame(
            ok=False,
            error="ffmpeg is not installed",
            error_kind="unavailable",
        )

    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(timeout * 1_000_000),
        "-i",
        rtsp_url,
        "-frames:v",
        "1",
        "-fs",
        str(MAX_FRAME_BYTES + 1),
        "-f",
        "image2",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RTSPFrame(
            ok=False,
            error="RTSP frame capture timed out",
            error_kind="timeout",
        )
    except (OSError, subprocess.SubprocessError):
        return RTSPFrame(
            ok=False,
            error="RTSP capture process is unavailable",
            error_kind="unavailable",
        )
    if result.returncode != 0 or not result.stdout:
        return _capture_failure(result.stderr)
    if len(result.stdout) > MAX_FRAME_BYTES:
        return RTSPFrame(
            ok=False,
            error="RTSP frame exceeds the size limit",
            error_kind="oversized",
        )
    return RTSPFrame(ok=True, image_bytes=result.stdout)
