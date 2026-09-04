"""Headless driver for the legacy Fanvil web-config firmware.

Older Fanvil intercoms/phones (e.g. the i10S) run the "Rapid Logic" embedded web
server with the framed ``ConfigManApp`` UI and expose **no JSON API** — remote
configuration must go through the browser app under ``/lines.htm``. That app has
two auth layers and a JS-hashed login, so tools that only speak the JSON API (or
that key off the ``Server:`` banner) mis-identify these units and fail.

This module drives that firmware headlessly:

* **Auth** – HTTP Basic (realm ``VoIP Phone``) *plus* an app session obtained
  from either the legacy ``GET /key==nonce`` endpoint or the nonce embedded in
  the login form used by X-series phone firmware. Both submit ``encoded =
  "<user>:" + md5("<user>:<pass>:<nonce>")``. Legacy firmware also requires
  the nonce in its ``auth`` cookie. The wrapper replays the login form's own
  ``ReturnPage`` value so firmware variants receive the value they advertise.
* **Read** – ``GET /lines.htm`` (server-side-filled form fields such as
  ``SIP_RegUser_R``, ``SIP_RegAddr_R``, ``SIP_BackupAddr_R``).
* **Write** – a faithful *full-form replay*: re-POST every field of the ``sipForm``
  with its current value, changing only the target(s), adding ``DefaultSubmit=Apply``
  and base64-encoding password fields as ``"$EP^%39]" + base64(value)`` — byte-for-byte
  what the browser sends on **Apply**, so the masked-password placeholder is treated
  as "unchanged" and registration survives.
* **Single session** – the firmware serves very few sessions and returns HTTP 503
  ("Server Too Busy") once the pool is exhausted, so every session **logs out** and
  ``_request`` backs off on 503. Use the context manager to guarantee logout.

No device addresses, credentials or SIP servers are baked in — the caller supplies
them, keeping this wrapper generic.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import math
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser

import requests
from requests.auth import HTTPBasicAuth

#: password fields are posted as this prefix + base64(value) (from the app's comm.js)
ENCODE_PREFIX = "$EP^%39]"

#: Fanvil-registered MAC OUIs — the *reliable* way to identify these units
#: (the ``Server:`` banner and page markup are shared with other Rapid Logic gear).
FANVIL_OUIS = ("0c:38:3e", "00:a8:59")

_SIP_ANCHOR = "SIP_RegAddr_R"  # a field unique to the SIP account form (``sipForm``)
_SIP_TRANSPORTS = {"udp": "0", "tcp": "1"}
_AUTHENTICATED_PAGE_MARKERS = ("realws.htm", "currentstat.htm")


class LoginError(RuntimeError):
    """App-session login failed (bad credentials or unexpected page)."""


class BusyError(RuntimeError):
    """Device session pool exhausted (HTTP 503) after retries."""


@dataclass
class SipAccount:
    """Snapshot of one SIP line read from ``/lines.htm``."""

    ext: str | None
    primary: str | None
    primary_port: str | None
    backup: str | None
    backup_port: str | None
    failback: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ext": self.ext,
            "primary": self.primary,
            "primary_port": self.primary_port,
            "backup": self.backup,
            "backup_port": self.backup_port,
            "failback": self.failback,
        }


@dataclass
class DeviceInfo:
    """Identity read from ``/information.htm`` (model + MAC)."""

    mac: str | None
    model: str | None

    @property
    def is_fanvil(self) -> bool:
        mac = (self.mac or "").lower()
        return any(mac.startswith(oui) for oui in FANVIL_OUIS)


class _FormFields(HTMLParser):
    """Collect the submittable fields of the ``<form>`` containing ``anchor``."""

    def __init__(self, anchor: str) -> None:
        super().__init__()
        self._anchor = anchor
        self.fields: list[tuple[str, str, str]] = []  # (name, value, type)
        self._cur: list[tuple[str, str, str]] | None = None
        self._sel: str | None = None
        self._picked = False

    def handle_starttag(self, tag: str, attrs):  # noqa: ANN001
        a = {k: (v or "") for k, v in attrs}
        if tag == "form":
            self._cur = []
        elif tag == "input" and self._cur is not None:
            name = a.get("name")
            if not name:
                return
            typ = (a.get("type") or "text").lower()
            if typ in ("checkbox", "radio"):
                if "checked" in a:
                    self._cur.append((name, a.get("value", "on"), typ))
            elif typ == "button":
                return
            else:
                self._cur.append((name, _unescape(a.get("value", "")), typ))
        elif tag == "select" and self._cur is not None:
            self._sel = a.get("name")
            self._picked = False
            self._cur.append((self._sel, "", "select"))
        elif tag == "option" and self._sel is not None and "selected" in a and not self._picked:
            for i in range(len(self._cur) - 1, -1, -1):
                if self._cur[i][0] == self._sel and self._cur[i][2] == "select":
                    self._cur[i] = (self._sel, a.get("value", ""), "select")
                    break
            self._picked = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._sel = None
        elif tag == "form" and self._cur is not None:
            if any(n == self._anchor for n, *_ in self._cur):
                self.fields = self._cur
            self._cur = None


def _unescape(s: str) -> str:
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')


def _field(html: str, name: str) -> str | None:
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html) or re.search(
        rf'value="([^"]*)"[^>]*name="{re.escape(name)}"', html
    )
    return m.group(1) if m else None


def _checked(html: str, name: str) -> bool:
    m = re.search(rf'name="{re.escape(name)}"[^>]*>', html)
    return bool(m and re.search(r"\bchecked\b", m.group(0), re.I))


def _is_authenticated_page(html: str) -> bool:
    """Recognize authenticated shells used across Fanvil firmware families."""
    return any(marker in html for marker in _AUTHENTICATED_PAGE_MARKERS) or bool(
        re.search(r"<frameset\b", html, re.I)
    )


class FanvilWebConfig:
    """Headless session against the legacy Fanvil web-config firmware.

    Example::

        with FanvilWebConfig("10.0.0.5", "admin", "secret") as dev:
            info = dev.identify()
            acct = dev.read_sip()
            dev.set_sip_server(primary="10.254.250.11", backup="34.194.159.36")
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        scheme: str = "http",
        timeout: float = 10.0,
        total_timeout: float | None = None,
        max_503_retries: int = 2,
        retry_backoff: float = 5.0,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.scheme = scheme
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        if not 0 <= max_503_retries <= 2:
            raise ValueError("max_503_retries must be between 0 and 2")
        if not math.isfinite(retry_backoff) or not 0 <= retry_backoff <= 5:
            raise ValueError("retry_backoff must be finite and between 0 and 5 seconds")
        self.timeout = min(timeout, 30.0)
        if total_timeout is not None and (not math.isfinite(total_timeout) or total_timeout <= 0):
            raise ValueError("total_timeout must be a positive finite number")
        self._deadline = (
            time.monotonic() + min(total_timeout, 30.0) if total_timeout is not None else None
        )
        self.max_503_retries = max_503_retries
        self.retry_backoff = retry_backoff
        self._s = requests.Session()
        self._s.auth = HTTPBasicAuth(username, password)
        self._logged_in = False

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> FanvilWebConfig:
        self.login()
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.logout()

    # -- transport ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.host}{path}"

    def _request_timeout(self) -> float:
        if self._deadline is None:
            return self.timeout
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout(f"{self.host}: operation timeout")
        return min(self.timeout, remaining)

    def _request(self, path: str, data: dict | None = None) -> str:
        last: Exception | None = None
        for attempt in range(self.max_503_retries + 1):
            timeout = self._request_timeout()
            r = (
                self._s.post(self._url(path), data=data, timeout=timeout)
                if data
                else self._s.get(self._url(path), timeout=timeout)
            )
            if r.status_code == 503:
                last = BusyError(f"{self.host}: 503 Server Too Busy")
                if attempt < self.max_503_retries:
                    delay = self.retry_backoff * (attempt + 1)
                    if self._deadline is not None:
                        delay = min(delay, max(0.0, self._deadline - time.monotonic()))
                    if delay > 0:
                        time.sleep(delay)
                continue
            r.raise_for_status()
            return r.text
        raise last or BusyError(f"{self.host}: 503")

    # -- auth --------------------------------------------------------------
    def login(self) -> None:
        landing_page = self._request("/")
        embedded_nonce = _field(landing_page, "nonce")
        if embedded_nonce:
            nonce = embedded_nonce
            payload = {
                "nonce": nonce,
                "URL": _field(landing_page, "URL") or "/",
                "LOG_Language": _field(landing_page, "LOG_Language") or "0",
                "goto": _field(landing_page, "goto") or "Logon",
            }
        else:
            nonce = self._request(f"/key==nonce?now={int(time.time() * 1000)}")[:16]
            self._s.cookies.set("auth", nonce, path="/")
            payload = {"ReturnPage": _field(landing_page, "ReturnPage") or ""}

        digest = hashlib.md5(f"{self.username}:{self.password}:{nonce}".encode()).hexdigest()
        payload["encoded"] = f"{self.username}:{digest}"
        response = self._request("/", payload)
        if not _is_authenticated_page(response):
            response = self._request("/")
        if not _is_authenticated_page(response):
            raise LoginError(f"{self.host}: app-session login failed")
        self._logged_in = True

    def logout(self) -> None:
        if not self._logged_in:
            return
        # logout is best-effort — never mask the real error
        with contextlib.suppress(Exception):
            self._request("/", {"DefaultLogout": "Logout"})
        self._logged_in = False

    # -- identity ----------------------------------------------------------
    def identify(self) -> DeviceInfo:
        html = self._request("/information.htm")
        macs = re.findall(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", html)
        labeled_model = re.search(
            r'id=["\']XSTR_LBL_INFO_MODEL["\'][^>]*>.*?</span>\s*:?\s*</td>'
            r"\s*<td[^>]*>\s*([^<]+)",
            html,
            re.I | re.S,
        )
        fallback_model = re.search(r"(?i)\b(i[0-9]{2}[A-Za-z]?|[A-Z][0-9]{2,3}[A-Za-z]?)\b", html)
        return DeviceInfo(
            mac=(macs[0].lower() if macs else None),
            model=(
                _unescape(labeled_model.group(1).strip())
                if labeled_model
                else (fallback_model.group(1) if fallback_model else None)
            ),
        )

    # -- SIP account -------------------------------------------------------
    def read_sip(self) -> SipAccount:
        html = self._request("/lines.htm")
        return SipAccount(
            ext=_field(html, "SIP_RegUser_R"),
            primary=_field(html, "SIP_RegAddr_R"),
            primary_port=_field(html, "SIP_RegPort_R"),
            backup=_field(html, "SIP_BackupAddr_R"),
            backup_port=_field(html, "SIP_BackupPort_R"),
            failback=_checked(html, "SIP_EnableFailback_RW"),
        )

    def set_fields(self, changes: dict[str, str]) -> SipAccount:
        """Apply ``changes`` (field name -> value) to the SIP form via full-form
        replay, then return the re-read account. Only the given fields change.
        """
        parser = _FormFields(_SIP_ANCHOR)
        parser.feed(self._request("/lines.htm"))
        if not parser.fields:
            raise RuntimeError(f"{self.host}: SIP form not found on /lines.htm")
        body = build_replay_body(parser.fields, changes)
        self._s.post(
            self._url("/lines.htm"),
            data=body,
            timeout=self._request_timeout(),
        ).raise_for_status()
        return self.read_sip()

    def set_sip_server(
        self,
        primary: str,
        *,
        backup: str | None = None,
        primary_port: str = "5060",
        backup_port: str = "5060",
    ) -> SipAccount:
        """Set the primary SIP server and (optionally) the backup/failover server.

        Pass ``backup=""`` to clear the backup (single-path). The firmware's own
        failover/failback behaviour (``SIP_EnableFailback_RW``) is left as-is.
        """
        changes = {"SIP_RegAddr_R": primary, "SIP_RegPort_R": primary_port}
        if backup is not None:
            changes["SIP_BackupAddr_R"] = backup
            if backup:
                changes["SIP_BackupPort_R"] = backup_port
        return self.set_fields(changes)

    @staticmethod
    def validate_sip_account(account: int) -> None:
        """Validate that this firmware facade can address ``account`` safely."""
        if account != 1:
            raise ValueError("legacy Fanvil web configuration supports SIP account 1 only")

    def set_sip_account(
        self,
        *,
        account: int = 1,
        server: str,
        port: str = "5060",
        username: str,
        password: str,
        transport: str = "udp",
    ) -> SipAccount:
        """Apply one SIP account using vendor-neutral values.

        Fanvil form field names and transport encodings stay inside this wrapper;
        callers never need to know the legacy firmware's wire representation.

        The currently supported legacy ``/lines.htm`` form exposes account 1
        without an account-qualified write target.  Refuse account 2 instead
        of silently overwriting account 1; a firmware-verified selector must be
        added before account 2 can be mutated through this facade.
        """
        self.validate_sip_account(account)
        normalized_transport = transport.lower()
        try:
            transport_value = _SIP_TRANSPORTS[normalized_transport]
        except KeyError as exc:
            raise ValueError(f"unsupported SIP transport: {transport}") from exc

        return self.set_fields(
            {
                "SIP_RegAddr_R": server,
                "SIP_RegPort_R": port,
                "SIP_RegUser_R": username,
                "SIP_RegPasswd_R": password,
                "SIP_Transport_RW": transport_value,
            }
        )


def build_replay_body(
    fields: list[tuple[str, str, str]], changes: dict[str, str]
) -> list[tuple[str, str]]:
    """Build the full-form-replay POST body from parsed ``fields`` (name, value,
    type), applying ``changes`` and encoding password fields exactly as the
    browser does (``ENCODE_PREFIX`` + base64). ``DefaultSubmit=Apply`` is appended
    if absent. Pure function — the core write logic, kept testable without a device.
    """
    body: list[tuple[str, str]] = []
    for name, value, typ in fields:
        if name in changes:
            value = changes[name]
        if typ == "password" and value:
            value = ENCODE_PREFIX + base64.b64encode(value.encode()).decode()
        body.append((name, value))
    if not any(n == "DefaultSubmit" for n, _ in body):
        body.append(("DefaultSubmit", "Apply"))
    return body


def is_fanvil_mac(mac: str | None) -> bool:
    """True if ``mac`` belongs to a Fanvil OUI (the reliable vendor check)."""
    m = (mac or "").lower().replace("-", ":")
    return any(m.startswith(oui) for oui in FANVIL_OUIS)
