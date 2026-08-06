"""Bounded RTSP frame capture for Fanvil device-owned camera streams."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RTSPFrame:
    """Typed result for one single-frame RTSP capture attempt."""

    ok: bool
    image_bytes: bytes = b""
    error: str = ""


def capture_rtsp_frame(rtsp_url: str, *, timeout: int = 5) -> RTSPFrame:
    """Capture one JPEG frame with ffmpeg without logging the credential URL."""
    timeout = max(1, min(timeout, 30))
    if not shutil.which("ffmpeg"):
        return RTSPFrame(ok=False, error="ffmpeg is not installed")

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
        return RTSPFrame(ok=False, error="RTSP frame capture timed out")
    if result.returncode != 0 or not result.stdout:
        return RTSPFrame(ok=False, error="RTSP frame capture failed")
    return RTSPFrame(ok=True, image_bytes=result.stdout)
