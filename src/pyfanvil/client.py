"""Minimal Fanvil HTTP/XMLService client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from .network import NetworkConfig, build_network_xml

AuthMode = Literal["auto", "digest", "basic", "none"]


@dataclass(frozen=True)
class FanvilResponse:
    """A small, serializable response object."""

    ok: bool
    status_code: int | None
    url: str
    server: str = ""
    www_authenticate: str = ""
    body_prefix: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "url": self.url,
            "server": self.server,
            "www_authenticate": self.www_authenticate,
            "body_prefix": self.body_prefix,
            "error": self.error,
        }


class FanvilClient:
    """HTTP client for Fanvil XMLService operations."""

    def __init__(
        self,
        host: str,
        *,
        username: str = "admin",
        password: str = "",
        scheme: str = "http",
        timeout: float = 10.0,
        verify_tls: bool = False,
        auth: AuthMode = "auto",
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.scheme = scheme
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.auth = auth

    @property
    def xml_service_url(self) -> str:
        return f"{self.scheme}://{self.host}/xmlService"

    def build_static_network_xml(self, config: NetworkConfig) -> str:
        return build_network_xml(config)

    def apply_static_network(self, config: NetworkConfig) -> FanvilResponse:
        return self.post_xml(self.build_static_network_xml(config))

    def post_xml(self, xml: str) -> FanvilResponse:
        auth_obj = None
        if self.auth == "basic":
            auth_obj = HTTPBasicAuth(self.username, self.password)
        elif self.auth in ("auto", "digest"):
            auth_obj = HTTPDigestAuth(self.username, self.password)

        try:
            response = requests.post(
                self.xml_service_url,
                data=xml.encode("utf-8"),
                headers={
                    "Content-Type": "application/xml",
                    "User-Agent": "pyfanvil/0.1",
                },
                auth=auth_obj,
                timeout=self.timeout,
                verify=self.verify_tls,
            )
            return FanvilResponse(
                ok=200 <= response.status_code < 300,
                status_code=response.status_code,
                url=self.xml_service_url,
                server=response.headers.get("Server", ""),
                www_authenticate=response.headers.get("WWW-Authenticate", ""),
                body_prefix=response.text[:512],
            )
        except Exception as exc:
            return FanvilResponse(
                ok=False,
                status_code=None,
                url=self.xml_service_url,
                error=f"{type(exc).__name__}: {exc}",
            )
