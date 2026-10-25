import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from pyfanvil import diagnostics


@pytest.mark.parametrize(
    "body,content_type,status,valid",
    [
        (b"native log records", "application/octet", 200, True),
        (b"<html>login</html>", "application/octet", 200, False),
        (b"", "text/plain", 200, False),
        (b"data", "text/html", 200, False),
        (b"data", "application/octet", 302, False),
        (b"x" * 33, "application/octet", 200, False),
    ],
)
def test_download_validates_and_bounds(monkeypatch, body, content_type, status, valid):
    actual_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            status,
            content=body,
            headers={"content-type": content_type},
        )
    )
    monkeypatch.setattr(
        diagnostics.httpx,
        "AsyncClient",
        lambda **kw: actual_client(
            transport=transport,
            **kw,
        ),
    )
    coroutine = diagnostics.download_log(
        "http://device.example/cgi-bin/syslog?type=syslog",
        username="u",
        password="p",
        cookies={},
        max_bytes=32,
        timeout_seconds=1,
    )
    if valid:
        assert asyncio.run(coroutine) == body
    else:
        with pytest.raises(ValueError):
            asyncio.run(coroutine)


def test_export_rejects_replaced_device_and_hides_bytes(monkeypatch):
    info = SimpleNamespace(mac="00:11:22:33:44:55", model="i16S", firmware_version="test")
    client = Mock(username="u", password="p")
    client.identify.return_value = info
    client._request.return_value = 'href="cgi-bin/syslog?type=syslog"'
    client._request_timeout.return_value = 10
    monkeypatch.setattr(diagnostics, "download_log", AsyncMock(return_value=b"private log"))
    artifact = diagnostics.export_system_log(client, expected_mac=info.mac)
    assert artifact.data == b"private log"
    assert "private log" not in repr(artifact)
    client.identify.side_effect = [info, SimpleNamespace(mac="different")]
    with pytest.raises(ValueError, match="changed"):
        diagnostics.export_system_log(client, expected_mac=info.mac)


def test_download_has_overall_deadline(monkeypatch):
    actual_client = httpx.AsyncClient

    async def stall(request):
        await asyncio.sleep(1)
        return httpx.Response(200, content=b"log")

    monkeypatch.setattr(
        diagnostics.httpx,
        "AsyncClient",
        lambda **kw: actual_client(
            transport=httpx.MockTransport(stall),
            **kw,
        ),
    )
    with pytest.raises(TimeoutError):
        asyncio.run(
            diagnostics.download_log(
                "http://device.example/log",
                username="u",
                password="p",
                cookies={},
                max_bytes=32,
                timeout_seconds=0.01,
            )
        )
