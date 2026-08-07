"""Fanvil IP phone/intercom helpers."""

from .capture import RTSPFrame, capture_rtsp_frame
from .client import FanvilClient, FanvilResponse
from .network import NetworkConfig, build_network_xml, map_ip, plan_static_network
from .rtsp import RTSPStreamConfig, build_rtsp_url
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
    "RTSPStreamConfig",
    "RTSPFrame",
    "build_network_xml",
    "build_rtsp_url",
    "capture_rtsp_frame",
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
