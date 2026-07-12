"""Offline tests for the legacy Fanvil web-config driver (no device needed)."""

import base64
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
