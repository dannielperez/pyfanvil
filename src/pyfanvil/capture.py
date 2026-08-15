"""Bounded RTSP frame capture for Fanvil device-owned camera streams."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Literal

import httpx

MAX_FRAME_BYTES = 10 * 1024 * 1024
MAX_HTTP_PREVIEW_BYTES = 8 * 1024 * 1024
DEFAULT_HTTP_PREVIEW_PATH = "/cgi-bin/video"
_HTTP_AUTH_PHASES = 8
_MAX_MULTIPART_PREAMBLE_BYTES = 64 * 1024
_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"

HTTPPreviewAuthMode = Literal["digest", "basic"]


@dataclass(frozen=True, slots=True)
class RTSPFrame:
    """Typed result for one single-frame RTSP capture attempt."""

    ok: bool
    image_bytes: bytes = b""
    error: str = ""
    error_kind: str = ""


@dataclass(frozen=True, slots=True)
class HTTPPreviewFrame:
    """Typed first-JPEG result from Fanvil's documented HTTP preview stream."""

    ok: bool
    image_bytes: bytes = b""
    content_type: str = ""
    error: str = ""
    error_kind: str = ""


def _http_preview_failure(kind: str) -> HTTPPreviewFrame:
    messages = {
        "authentication": "HTTP preview authentication failed",
        "http_error": "HTTP preview request failed",
        "image_too_large": "HTTP preview frame exceeds the size limit",
        "invalid_image": "HTTP preview did not return a JPEG frame",
        "timeout": "HTTP preview request timed out",
        "unavailable": "HTTP preview is temporarily unavailable",
    }
    return HTTPPreviewFrame(
        ok=False,
        error=messages[kind],
        error_kind=kind,
    )


def capture_http_preview_frame(  # noqa: PLR0913 - explicit bounded endpoint/auth contract
    host: str,
    username: str,
    password: str,
    *,
    scheme: str = "http",
    port: int | None = None,
    auth_mode: HTTPPreviewAuthMode = "digest",
    timeout: float = 3.0,
    max_bytes: int = MAX_HTTP_PREVIEW_BYTES,
    verify_tls: bool = False,
    _transport: httpx.BaseTransport | None = None,
) -> HTTPPreviewFrame:
    """Extract the first JPEG from Fanvil's documented HTTP preview stream.

    Credentials never enter the URL or result. The byte cap bounds both a
    multipart JPEG frame and a non-JPEG stream; one monotonic deadline spans
    authentication, headers, and streamed content.
    """
    normalized_host = host.strip()
    if (
        not normalized_host
        or "://" in normalized_host
        or any(character in normalized_host for character in "/@?#")
    ):
        raise ValueError("HTTP preview host is invalid")
    if scheme not in {"http", "https"}:
        raise ValueError("HTTP preview scheme is invalid")
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    if (
        isinstance(effective_port, bool)
        or not isinstance(effective_port, int)
        or not 1 <= effective_port <= 65_535
    ):
        raise ValueError("HTTP preview port is invalid")
    if not username.strip() or not password:
        raise ValueError("HTTP preview credentials are incomplete")
    if auth_mode not in {"digest", "basic"}:
        raise ValueError("HTTP preview authentication mode is invalid")
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 30:
        raise ValueError("HTTP preview timeout is invalid")
    if max_bytes < 1024:
        raise ValueError("HTTP preview byte limit is invalid")

    operation_timeout = max(0.001, timeout / _HTTP_AUTH_PHASES)
    content_deadline = time.monotonic() + timeout - operation_timeout
    auth = (
        httpx.DigestAuth(username, password)
        if auth_mode == "digest"
        else httpx.BasicAuth(username, password)
    )
    url = httpx.URL(
        scheme=scheme,
        host=normalized_host,
        port=effective_port,
        path=DEFAULT_HTTP_PREVIEW_PATH,
        query=b"",
    )
    try:
        with (
            httpx.Client(
                auth=auth,
                timeout=operation_timeout,
                follow_redirects=False,
                verify=verify_tls,
                transport=_transport,
            ) as client,
            client.stream("GET", url) as response,
        ):
            if time.monotonic() >= content_deadline:
                return _http_preview_failure("timeout")
            if response.status_code in {401, 403}:
                return _http_preview_failure("authentication")
            if response.status_code != 200:
                return _http_preview_failure("http_error")

            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            buffer = bytearray()
            jpeg_started = False
            for chunk in response.iter_bytes():
                if time.monotonic() >= content_deadline:
                    return _http_preview_failure("timeout")
                buffer.extend(chunk)
                if not jpeg_started:
                    start = buffer.find(_JPEG_START)
                    if start >= 0:
                        del buffer[:start]
                        jpeg_started = True
                    elif len(buffer) > _MAX_MULTIPART_PREAMBLE_BYTES:
                        return _http_preview_failure("invalid_image")
                if jpeg_started:
                    end = buffer.find(_JPEG_END, len(_JPEG_START))
                    if end >= 0:
                        image = bytes(buffer[: end + len(_JPEG_END)])
                        if len(image) > max_bytes:
                            return _http_preview_failure("image_too_large")
                        return HTTPPreviewFrame(
                            ok=True,
                            image_bytes=image,
                            content_type=content_type,
                        )
                    if len(buffer) > max_bytes:
                        return _http_preview_failure("image_too_large")
    except httpx.TimeoutException:
        return _http_preview_failure("timeout")
    except httpx.HTTPError:
        return _http_preview_failure("unavailable")
    return _http_preview_failure("invalid_image")


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
