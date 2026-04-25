"""Fanvil network configuration payload helpers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


CONFIG_KEYS = {
    "dhcp": "net.dhcp.Enabled",
    "ip": "net.static.IP",
    "mask": "net.static.SubnetMask",
    "gateway": "net.static.Gateway",
    "dns1": "net.static.PrimaryDNS",
    "dns2": "net.static.SecondaryDNS",
}


@dataclass(frozen=True)
class NetworkConfig:
    """Static IPv4 network settings for a Fanvil endpoint."""

    ip: str
    netmask: str
    gateway: str
    dns1: str = "8.8.8.8"
    dns2: str = "1.1.1.1"
    dhcp_enabled: bool = False


def build_network_xml(config: NetworkConfig, *, beep: bool = False) -> str:
    """Build a Fanvil XMLService static-network payload."""

    dhcp = "1" if config.dhcp_enabled else "0"
    beep_value = "yes" if beep else "no"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<FanvilConfiguration Beep="{beep_value}" cmd="set">',
        f'  <ConfigItem>{CONFIG_KEYS["dhcp"]}="{dhcp}"</ConfigItem>',
        f'  <ConfigItem>{CONFIG_KEYS["ip"]}="{config.ip}"</ConfigItem>',
        f'  <ConfigItem>{CONFIG_KEYS["mask"]}="{config.netmask}"</ConfigItem>',
        f'  <ConfigItem>{CONFIG_KEYS["gateway"]}="{config.gateway}"</ConfigItem>',
        f'  <ConfigItem>{CONFIG_KEYS["dns1"]}="{config.dns1}"</ConfigItem>',
        f'  <ConfigItem>{CONFIG_KEYS["dns2"]}="{config.dns2}"</ConfigItem>',
        "</FanvilConfiguration>",
        "",
    ]
    return "\n".join(lines)


def map_ip(old_ip: str, old_subnet: str, new_subnet: str) -> str:
    """Map an IP from one subnet to another while preserving host offset."""

    old_net = ipaddress.ip_network(old_subnet, strict=False)
    new_net = ipaddress.ip_network(new_subnet, strict=False)
    old = ipaddress.ip_address(old_ip)
    if old not in old_net:
        raise ValueError(f"{old_ip} is not inside {old_net}")
    host = int(old) - int(old_net.network_address)
    return str(ipaddress.ip_address(int(new_net.network_address) + host))


def plan_static_network(
    old_ip: str,
    old_subnet: str,
    new_subnet: str,
    *,
    gateway: str | None = None,
    dns1: str = "8.8.8.8",
    dns2: str = "1.1.1.1",
) -> NetworkConfig:
    """Build a static NetworkConfig by preserving the old host octet."""

    new_net = ipaddress.ip_network(new_subnet, strict=False)
    return NetworkConfig(
        ip=map_ip(old_ip, old_subnet, new_subnet),
        netmask=str(new_net.netmask),
        gateway=gateway or str(next(new_net.hosts())),
        dns1=dns1,
        dns2=dns2,
        dhcp_enabled=False,
    )
