"""Headless driver for the legacy Fanvil web-config firmware.

Older Fanvil intercoms/phones (e.g. the i10S) run the "Rapid Logic" embedded web
server with the framed ``ConfigManApp`` UI and expose **no JSON API** — remote
configuration must go through the browser app under ``/lines.htm``. That app has
two auth layers and a JS-hashed login, so tools that only speak the JSON API (or
that key off the ``Server:`` banner) mis-identify these units and fail.

This module drives that firmware headlessly:

* **Auth** – HTTP Basic (realm ``VoIP Phone``) *plus* an app session obtained by
  ``GET /key==nonce`` then ``POST /`` with ``encoded = "<user>:" +
  md5("<user>:<pass>:<nonce>")``.
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


class LoginError(RuntimeError):
    """App-session login failed (bad credentials or unexpected page)."""


class BusyError(RuntimeError):
    """Device session pool exhausted (HTTP 503) after retries."""


@dataclass
class SipAccount:
    """Snapshot of one SIP line read from ``/lines.htm``.

    NOTE: Fanvil splits the identity into TWO fields that are easy to confuse —
    ``number`` (``SIP_PhoneNum_R``, the account user placed in From/To/Contact and
    what the PBX AOR matches on) and ``auth_user`` (``SIP_RegUser_R``, the
    authentication/Register name). To re-home a panel to a different extension you
    must change **both** (plus the password); changing only ``auth_user`` leaves it
    registering under the old number and failing authentication.
    """

    number: str | None      # SIP_PhoneNum_R — the account user (From/To/Contact/AOR)
    auth_user: str | None    # SIP_RegUser_R — the authentication / Register name
    primary: str | None
    primary_port: str | None
    backup: str | None
    backup_port: str | None
    failback: bool | None

    @property
    def ext(self) -> str | None:
        """The extension the panel registers as (its SIP number)."""
        return self.number

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "auth_user": self.auth_user,
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
        max_503_retries: int = 6,
        retry_backoff: float = 10.0,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.scheme = scheme
        self.timeout = timeout
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

    def _request(self, path: str, data: dict | None = None) -> str:
        last: Exception | None = None
        for attempt in range(self.max_503_retries + 1):
            r = self._s.post(self._url(path), data=data, timeout=self.timeout) if data else \
                self._s.get(self._url(path), timeout=self.timeout)
            if r.status_code == 503:
                last = BusyError(f"{self.host}: 503 Server Too Busy")
                time.sleep(self.retry_backoff * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        raise last or BusyError(f"{self.host}: 503")

    # -- auth --------------------------------------------------------------
    def login(self) -> None:
        self._request("/")
        nonce = self._request(f"/key==nonce?now={int(time.time() * 1000)}").strip()
        digest = hashlib.md5(f"{self.username}:{self.password}:{nonce}".encode()).hexdigest()
        encoded = f"{self.username}:{digest}"
        self._request("/", {"encoded": encoded, "CurLanguage": "en", "ReturnPage": "/"})
        if "realws.htm" not in self._request("/"):
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
        model = re.search(r"(?i)\b(i[0-9]{2}[A-Za-z]?|[A-Z][0-9]{2,3}[A-Za-z]?)\b", html)
        return DeviceInfo(mac=(macs[0].lower() if macs else None),
                          model=(model.group(1) if model else None))

    # -- SIP account -------------------------------------------------------
    def read_sip(self) -> SipAccount:
        html = self._request("/lines.htm")
        return SipAccount(
            number=_field(html, "SIP_PhoneNum_R"),
            auth_user=_field(html, "SIP_RegUser_R"),
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
        self._s.post(self._url("/lines.htm"), data=body, timeout=self.timeout).raise_for_status()
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

    def set_account(
        self, number: str, *, auth_user: str | None = None, password: str | None = None
    ) -> SipAccount:
        """Re-home the line to a different extension. Sets the SIP ``number``
        (From/To/Contact) **and** the auth user together — set both or the panel
        keeps registering under the old number and fails auth. ``auth_user`` defaults
        to ``number``. Pass ``password`` to set a new secret; omit to keep the current
        one. **Reboot required** afterwards (call :meth:`reboot`) — the SIP identity
        does not switch live.
        """
        changes = {"SIP_PhoneNum_R": number, "SIP_RegUser_R": auth_user or number}
        if password is not None:
            changes["SIP_RegPasswd_R"] = password
        return self.set_fields(changes)

    def reboot(self) -> None:
        """Reboot the device (needed to apply a SIP identity change)."""
        self._s.post(self._url("/reboot.htm"), data={"DefaultReboot": "Reboot"},
                     timeout=self.timeout)


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
