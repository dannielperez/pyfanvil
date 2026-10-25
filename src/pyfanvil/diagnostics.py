"""Bounded native log downloads; consumers own encryption and retention."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class DiagnosticArtifact:
    kind: str
    mac: str
    model: str
    firmware: str
    sha256: str
    data: bytes = field(repr=False)


async def download_log(url, *, username, password, cookies, max_bytes, timeout_seconds):
    """An overall deadline also bounds a slow-drip streaming response."""
    async with asyncio.timeout(timeout_seconds):
        async with httpx.AsyncClient(
            auth=(username, password),
            cookies=cookies,
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ValueError("Native log export failed")
                if response.headers.get("content-type", "").split(";")[0] not in {
                    "application/octet",
                    "application/octet-stream",
                    "text/plain",
                }:
                    raise ValueError("Unexpected native log content type")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > max_bytes:
                        raise ValueError("Native log exceeds size limit")
                    data.extend(chunk)
                if (
                    not data
                    or b"<html" in data[:1024].lower()
                    or b"<!doctype" in data[:1024].lower()
                ):
                    raise ValueError("Empty or HTML native log response")
                return bytes(data)


def export_system_log(client, *, expected_mac, max_bytes=1024 * 1024):
    if not expected_mac or not 1 <= max_bytes <= 8 * 1024 * 1024:
        raise ValueError("Expected identity and bounded size are required")
    before = client.identify()
    if not before.mac or before.mac.casefold() != expected_mac.casefold():
        raise ValueError("Hardware identity does not match")
    page = client._request("/tools.htm")
    if "cgi-bin/syslog?type=syslog" not in page:
        raise ValueError("Native log export is not advertised")
    data = asyncio.run(
        download_log(
            client._url("/cgi-bin/syslog?type=syslog"),
            username=client.username,
            password=client.password,
            cookies=client._s.cookies,
            max_bytes=max_bytes,
            timeout_seconds=min(15, client._request_timeout()),
        )
    )
    after = client.identify()
    if after.mac != before.mac:
        raise ValueError("Hardware identity changed during export")
    return DiagnosticArtifact(
        kind="system_log",
        mac=before.mac,
        model=before.model or "",
        firmware=before.firmware_version or "",
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )
