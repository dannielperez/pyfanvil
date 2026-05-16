from pyfanvil import NetworkConfig, build_network_xml


def test_build_network_xml_static_ip() -> None:
    xml = build_network_xml(
        NetworkConfig(
            ip="10.0.0.252",
            netmask="255.255.255.0",
            gateway="10.0.0.1",
        )
    )

    assert 'net.dhcp.Enabled="0"' in xml
    assert 'net.static.IP="10.0.0.252"' in xml
    assert 'net.static.SubnetMask="255.255.255.0"' in xml
    assert 'net.static.Gateway="10.0.0.1"' in xml
    assert xml.endswith("\n")
