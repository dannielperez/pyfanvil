"""Vendor-neutral helpers for Fanvil device RTSP stream addresses."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class RTSPStreamConfig:
    """Connection details for one operator-confirmed Fanvil RTSP stream.

    Fanvil firmware displays the effective main/sub-stream URLs in its camera
    settings. The path therefore stays explicit instead of being inferred from
    a model name. The rendered URL contains credentials and is intended only
    for immediate capture; callers must not persist or log it.
    """

    host: str
    path: str
    username: str = ""
    password: str = ""
    port: int = 554


def build_rtsp_url(config: RTSPStreamConfig) -> str:
    """Build an authenticated RTSP URL for an operator-confirmed stream."""
    host = config.host.strip()
    if not host:
        raise ValueError("RTSP host is required")
    if not 1 <= config.port <= 65535:
        raise ValueError("RTSP port must be between 1 and 65535")
    path = config.path.strip()
    if not path:
        raise ValueError("RTSP path is required")
    if not path.startswith("/"):
        path = f"/{path}"
    credentials = ""
    if config.username:
        credentials = quote(config.username, safe="")
        if config.password:
            credentials += f":{quote(config.password, safe='')}"
        credentials += "@"
    return f"rtsp://{credentials}{host}:{config.port}{path}"
