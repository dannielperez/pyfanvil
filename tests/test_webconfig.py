"""Offline tests for the legacy Fanvil web-config driver (no device needed)."""

import base64
import hashlib
from unittest.mock import Mock

import pytest

from pyfanvil import DeviceInfo, FanvilWebConfig, is_fanvil_mac
from pyfanvil.webconfig import (
    ENCODE_PREFIX,
    _checked,
    _field,
    _FormFields,
    build_replay_body,
)

# A trimmed sample of the ``sipForm`` served by /lines.htm.
SAMPLE_FORM = """
<form name="sipLineForm" method="post"><input type="hidden" name="line" value="0"></form>
<form name="sipForm" method="post">
  <input type="text" name="SIP_RegUser_R" value="3102">
  <input type="text" name="SIP_RegAddr_R" value="10.0.0.1">
  <input type="text" name="SIP_RegPort_R" value="5060">
  <input type="text" name="SIP_BackupAddr_R" value="9.9.9.9">
  <input type="password" name="SIP_RegPasswd_R" value="****">
  <input type="checkbox" name="SIP_EnableFailback_RW" value="ON" CHECKED>
  <input type="checkbox" name="SIP_Disabled_RW" value="ON">
  <select name="SIP_Transport_RW">
    <option value="0">UDP</option><option value="1" selected>TCP</option>
  </select>
  <input type="submit" name="DefaultSubmit" value="Apply">
</form>
"""


def test_is_fanvil_mac():
    assert is_fanvil_mac("0c:38:3e:74:09:84")
    assert is_fanvil_mac("0C-38-3E-74-09-84")  # dash-separated, upper
    assert is_fanvil_mac("00:a8:59:11:22:33")
    assert not is_fanvil_mac("aa:bb:cc:dd:ee:ff")
    assert not is_fanvil_mac(None)


def test_device_info_is_fanvil():
    assert DeviceInfo(mac="0c:38:3e:00:00:01", model="i10S").is_fanvil
    assert not DeviceInfo(mac="ff:ff:ff:00:00:01", model="?").is_fanvil


def test_identify_reads_slash_separated_model_from_information_label():
    client = FanvilWebConfig("phone.example", "admin", "secret")
    client._request = Mock(
        return_value="""
        <tr>
          <td><span id="XSTR_LBL_INFO_MODEL">Model</span>:</td>
          <td>X3S/X3SP</td>
        </tr>
        <tr><td>MAC</td><td>0c:38:3e:00:00:01</td></tr>
        """
    )

    info = client.identify()

    assert info.model == "X3S/X3SP"
    assert info.is_fanvil is True


def test_field_and_checked_readers():
    assert _field(SAMPLE_FORM, "SIP_RegAddr_R") == "10.0.0.1"
    assert _field(SAMPLE_FORM, "SIP_BackupAddr_R") == "9.9.9.9"
    assert _checked(SAMPLE_FORM, "SIP_EnableFailback_RW") is True
    assert _checked(SAMPLE_FORM, "SIP_Disabled_RW") is False


def test_form_parser_collects_only_submittable_fields():
    parser = _FormFields("SIP_RegAddr_R")
    parser.feed(SAMPLE_FORM)
    by_name = {n: v for n, v, _ in parser.fields}
    assert by_name["SIP_RegUser_R"] == "3102"
    assert "SIP_EnableFailback_RW" in by_name  # checked checkbox kept
    assert "SIP_Disabled_RW" not in by_name  # unchecked dropped (browser parity)
    assert by_name["SIP_Transport_RW"] == "1"  # selected <option> value


def test_build_replay_body_changes_only_target_and_encodes_password():
    parser = _FormFields("SIP_RegAddr_R")
    parser.feed(SAMPLE_FORM)
    body = build_replay_body(parser.fields, {"SIP_BackupAddr_R": ""})
    d = dict(body)
    # only the backup changed; primary untouched
    assert d["SIP_BackupAddr_R"] == ""
    assert d["SIP_RegAddr_R"] == "10.0.0.1"
    # password field re-encoded exactly like the browser (prefix + base64)
    assert d["SIP_RegPasswd_R"] == ENCODE_PREFIX + base64.b64encode(b"****").decode()
    # Apply submit preserved
    assert d["SIP_DefaultSubmit" if "SIP_DefaultSubmit" in d else "DefaultSubmit"] == "Apply"


def test_build_replay_body_appends_apply_when_missing():
    fields = [("SIP_RegAddr_R", "1.2.3.4", "text")]
    body = build_replay_body(fields, {})
    assert ("DefaultSubmit", "Apply") in body


def test_set_sip_account_maps_neutral_values_to_firmware_fields():
    client = FanvilWebConfig("phone.example", "admin", "secret")
    client.set_fields = Mock()

    client.set_sip_account(
        account=1,
        server="pbx.example",
        username="1001",
        password="sip-secret",
        transport="TCP",
    )

    client.set_fields.assert_called_once_with(
        {
            "SIP_RegAddr_R": "pbx.example",
            "SIP_RegPort_R": "5060",
            "SIP_RegUser_R": "1001",
            "SIP_RegPasswd_R": "sip-secret",
            "SIP_Transport_RW": "1",
        }
    )


def test_set_sip_account_refuses_unverified_second_account():
    client = FanvilWebConfig("phone.example", "admin", "secret")
    client.set_fields = Mock()

    with pytest.raises(ValueError, match="account 1 only"):
        client.set_sip_account(
            account=2,
            server="pbx.example",
            username="1002",
            password="sip-secret",
        )

    client.set_fields.assert_not_called()


def test_set_sip_account_rejects_unsupported_transport():
    client = FanvilWebConfig("phone.example", "admin", "secret")

    with pytest.raises(ValueError, match="unsupported SIP transport"):
        client.set_sip_account(
            server="pbx.example",
            username="1001",
            password="sip-secret",
            transport="tls",
        )


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_client_rejects_unbounded_timeout(timeout):
    with pytest.raises(ValueError, match="timeout must be a positive finite number"):
        FanvilWebConfig("phone.example", "admin", "secret", timeout=timeout)


@pytest.mark.parametrize("total_timeout", [0, -1, float("inf"), float("nan")])
def test_client_rejects_invalid_total_timeout(total_timeout):
    with pytest.raises(ValueError, match="total_timeout must be a positive finite number"):
        FanvilWebConfig(
            "phone.example",
            "admin",
            "secret",
            total_timeout=total_timeout,
        )


def test_total_timeout_clamps_each_http_request(monkeypatch):
    monotonic = iter([10.0, 10.5])
    monkeypatch.setattr("pyfanvil.webconfig.time.monotonic", lambda: next(monotonic))
    response = Mock(status_code=200, text="ok")
    client = FanvilWebConfig(
        "phone.example",
        "admin",
        "secret",
        timeout=10,
        total_timeout=3,
    )
    client._s.get = Mock(return_value=response)

    assert client._request("/") == "ok"

    client._s.get.assert_called_once_with("http://phone.example/", timeout=2.5)
    response.raise_for_status.assert_called_once_with()


def test_final_busy_attempt_does_not_sleep(monkeypatch):
    response = Mock(status_code=503)
    client = FanvilWebConfig(
        "phone.example",
        "admin",
        "secret",
        max_503_retries=0,
    )
    client._s.get = Mock(return_value=response)
    sleep = Mock()
    monkeypatch.setattr("pyfanvil.webconfig.time.sleep", sleep)

    with pytest.raises(RuntimeError, match="503 Server Too Busy"):
        client._request("/")

    sleep.assert_not_called()


def test_login_supports_nonce_embedded_in_x_series_form():
    landing_page = """
    <form method="post">
      <input name="nonce" value="0123456789abcdef">
      <input name="URL" value="/">
      <input name="LOG_Language" value="0">
      <input name="goto" value="Logon">
    </form>
    """
    client = FanvilWebConfig("phone.example", "admin", "secret")
    client._request = Mock(side_effect=[landing_page, '<a href="currentstat.htm">Status</a>'])

    client.login()

    digest = hashlib.md5(b"admin:secret:0123456789abcdef").hexdigest()
    assert client._request.call_args_list == [
        (("/",),),
        (
            (
                "/",
                {
                    "nonce": "0123456789abcdef",
                    "URL": "/",
                    "LOG_Language": "0",
                    "goto": "Logon",
                    "encoded": f"admin:{digest}",
                },
            ),
        ),
    ]
    assert client._logged_in is True


def test_login_keeps_legacy_key_nonce_flow():
    client = FanvilWebConfig("intercom.example", "admin", "secret")
    client._request = Mock(
        side_effect=[
            '<html><input type="hidden" name="ReturnPage"></html>',
            "fedcba9876543210ignored",
            '<frame src="realws.htm">',
        ]
    )

    client.login()

    digest = hashlib.md5(b"admin:secret:fedcba9876543210").hexdigest()
    assert client._request.call_args_list[1].args[0].startswith("/key==nonce?now=")
    assert client._request.call_args_list[2].args == (
        "/",
        {
            "ReturnPage": "",
            "encoded": f"admin:{digest}",
        },
    )
    assert client._s.cookies.get("auth") == "fedcba9876543210"
    assert client._logged_in is True


def test_login_replays_legacy_return_page_advertised_by_firmware():
    client = FanvilWebConfig("intercom.example", "admin", "secret")
    client._request = Mock(
        side_effect=[
            '<input type="hidden" name="ReturnPage" value="/legacy.htm">',
            "fedcba9876543210ignored",
            '<frame src="realws.htm">',
        ]
    )

    client.login()

    digest = hashlib.md5(b"admin:secret:fedcba9876543210").hexdigest()
    assert client._request.call_args_list[2].args == (
        "/",
        {
            "ReturnPage": "/legacy.htm",
            "encoded": f"admin:{digest}",
        },
    )


def test_login_accepts_authenticated_rapid_logic_frameset():
    client = FanvilWebConfig("phone.example", "admin", "secret")
    client._request = Mock(
        side_effect=[
            '<input type="hidden" name="ReturnPage" value="/">',
            "fedcba9876543210ignored",
            '<HTML><FRAMESET ROWS="60,*"><FRAME NAME="title_top"></FRAMESET></HTML>',
        ]
    )

    client.login()

    assert client._logged_in is True


def test_login_rejects_form_nonce_when_authenticated_marker_never_appears():
    client = FanvilWebConfig("phone.example", "admin", "wrong")
    client._request = Mock(
        side_effect=[
            '<input name="nonce" value="0123456789abcdef">',
            "<html>login failed</html>",
            '<input name="nonce" value="fedcba9876543210">',
        ]
    )

    with pytest.raises(RuntimeError, match="app-session login failed"):
        client.login()

    assert client._logged_in is False
