"""Thorlabs DMP40 SDK backend (DLLs load only when connecting/discovering)."""

from .backend import DMP40, MirrorCapabilities
from .sdk import DeviceInfo

__all__ = ["DMP40", "DeviceInfo", "MirrorCapabilities"]
