from pyfanvil import map_ip, plan_static_network


def test_map_ip_preserves_host_offset() -> None:
    assert map_ip("192.168.110.252", "192.168.110.0/24", "10.0.0.0/24") == "10.0.0.252"


def test_plan_static_network_defaults_gateway_to_first_host() -> None:
    config = plan_static_network(
        "192.168.110.252",
        "192.168.110.0/24",
        "10.0.0.0/24",
    )
    assert config.ip == "10.0.0.252"
    assert config.netmask == "255.255.255.0"
    assert config.gateway == "10.0.0.1"
    assert config.dhcp_enabled is False


def test_plan_static_network_explicit_gateway() -> None:
    config = plan_static_network(
        "192.168.110.252",
        "192.168.110.0/24",
        "10.0.0.0/24",
        gateway="10.0.0.254",
    )
    assert config.gateway == "10.0.0.254"
