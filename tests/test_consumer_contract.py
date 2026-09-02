"""Consumer-contract tests for pyfanvil's public API.

Pins the exports and mocked HTTP behavior consumed through
``uniqueos/devices/services/fanvil_sdk.py``. No live device is contacted.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

import pyfanvil
from pyfanvil import FanvilClient, FanvilWebConfig, LoginError


class TestPublicApiContract:
    """Pin the names that fanvil_sdk.py re-exports."""

    def test_boundary_critical_names_are_exported(self) -> None:
        required = {"FanvilClient", "LoginError"}

        assert required <= set(pyfanvil.__all__)
        assert all(getattr(pyfanvil, name) is not None for name in required)


class TestPostXmlContract:
    """Pin the XML client's typed, non-raising response behavior."""

    def test_successful_response_returns_transport_details(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        response = Mock(
            status_code=204,
            headers={
                "Server": "synthetic-fanvil",
                "WWW-Authenticate": "Digest synthetic-challenge",
            },
            text="configuration accepted",
        )
        post = Mock(return_value=response)
        monkeypatch.setattr(requests, "post", post)
        client = FanvilClient(
            "device.example.invalid",
            username="operator",
            password="synthetic-password",
            timeout=3.0,
        )

        result = client.post_xml("<setNetwork />")

        assert result.ok is True
        assert result.status_code == 204
        assert result.url == "http://device.example.invalid/xmlService"
        assert result.server == "synthetic-fanvil"
        assert result.www_authenticate == "Digest synthetic-challenge"
        assert result.body_prefix == "configuration accepted"
        assert result.error == ""
        post.assert_called_once()
        assert post.call_args.kwargs["data"] == b"<setNetwork />"
        assert post.call_args.kwargs["timeout"] == 3.0

    def test_request_exception_returns_failed_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raise_request_exception(*args: object, **kwargs: object) -> None:
            raise requests.RequestException("simulated network failure")

        monkeypatch.setattr(requests, "post", raise_request_exception)
        client = FanvilClient("device.example.invalid")

        result = client.post_xml("<setNetwork />")

        assert result.ok is False
        assert result.status_code is None
        assert result.url == "http://device.example.invalid/xmlService"
        assert result.error == "RequestException: simulated network failure"


class TestLoginErrorContract:
    """Pin the exported error raised when app-session login is rejected."""

    def test_missing_session_marker_raises_login_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        responses = iter(["", "synthetic-nonce", "", "<html>login</html>"])
        client = FanvilWebConfig(
            "device.example.invalid",
            "operator",
            "synthetic-password",
        )
        monkeypatch.setattr(client, "_request", lambda *args, **kwargs: next(responses))

        with pytest.raises(LoginError, match="app-session login failed"):
            client.login()
