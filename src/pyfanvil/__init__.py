"""Fanvil IP phone/intercom helpers."""

from .client import FanvilClient, FanvilResponse
from .network import NetworkConfig, build_network_xml, map_ip, plan_static_network
from .webconfig import (
    FANVIL_OUIS,
    BusyError,
    DeviceInfo,
    FanvilWebConfig,
    LoginError,
    SipAccount,
    is_fanvil_mac,
)

__all__ = [
    "FanvilClient",
    "FanvilResponse",
    "NetworkConfig",
    "build_network_xml",
    "map_ip",
    "plan_static_network",
    "FanvilWebConfig",
    "SipAccount",
    "DeviceInfo",
    "LoginError",
    "BusyError",
    "FANVIL_OUIS",
    "is_fanvil_mac",
]
