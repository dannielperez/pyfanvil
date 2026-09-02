"""Consumer-contract tests for pyfanvil's public API.

Pins the exact names and behavior that
``uniqueos/devices/services/fanvil_sdk.py`` (the boundary seam) depends on:
``FanvilClient``/``FanvilResponse`` for XML-service posts and ``LoginError``
for the legacy web-config auth failure path. All HTTP is mocked in-process —
no network.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

import pyfanvil
from pyfanvil import FanvilClient, FanvilResponse, FanvilWebConfig, LoginError


class TestPublicApiContract:
    """Pin the names fanvil_sdk.py re-exports."""

    def test_boundary_critical_names_are_exported(self) -> None:
        required = {"FanvilClient", "LoginError"}
        assert required <= set(pyfanvil.__all__)
        assert all(getattr(pyfanvil, name) is not None for name in required)

    def test_login_error_is_a_runtime_error(self) -> None:
        assert issubclass(LoginError, RuntimeError)


class TestFanvilClientPostXml:
    """Pin FanvilClient.post_xml()'s never-raise, typed-response contract."""

    def test_post_xml_2xx_returns_ok_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = FanvilClient("phone.example", username="admin", password="pw")
        fake_response = Mock(
            status_code=200,
            headers={"Server": "Fanvil-httpd", "WWW-Authenticate": ""},
            text="<xml>ok</xml>",
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        result = client.post_xml("<xml/>")

        assert isinstance(result, FanvilResponse)
        assert result.ok is True
        assert result.status_code == 200
        assert result.body_prefix == "<xml>ok</xml>"
        assert result.server == "Fanvil-httpd"

    def test_post_xml_non_2xx_returns_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = FanvilClient("phone.example", username="admin", password="pw")
        fake_response = Mock(status_code=403, headers={}, text="forbidden")
        monkeypatch.setattr(requests, "post", lambda *a, **k: fake_response)

        result = client.post_xml("<xml/>")

        assert result.ok is False
        assert result.status_code == 403

    def test_post_xml_never_raises_on_network_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise requests.RequestException("simulated network failure")

        client = FanvilClient("phone.example", username="admin", password="pw")
        monkeypatch.setattr(requests, "post", _raise)

        result = client.post_xml("<xml/>")

        assert result.ok is False
        assert result.status_code is None
        assert "RequestException" in result.error


class TestFanvilWebConfigLogin:
    """Pin FanvilWebConfig.login()'s LoginError failure path."""

    def test_login_raises_login_error_when_app_session_probe_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FanvilWebConfig("phone.example", "admin", "secret")
        # "/" probe, nonce fetch, POST encoded creds, final "/" probe -> missing realws.htm
        responses = iter(["", "deadbeef", "", "<html>login failed</html>"])
        monkeypatch.setattr(client, "_request", lambda *a, **k: next(responses))

        with pytest.raises(LoginError, match="app-session login failed"):
            client.login()

    def test_login_succeeds_when_final_probe_contains_realws(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FanvilWebConfig("phone.example", "admin", "secret")
        responses = iter(["", "deadbeef", "", "<html>...realws.htm...</html>"])
        monkeypatch.setattr(client, "_request", lambda *a, **k: next(responses))

        client.login()

        assert client._logged_in is True
