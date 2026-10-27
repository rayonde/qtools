"""Modal control for Thorlabs deformable mirrors.

Importing and constructing controllers is supported on macOS/Linux. Discovering
or connecting real hardware requires the Thorlabs Windows x64 SDK.
"""

from .backends.Thorlabs.DMP40 import DMP40, DeviceInfo, MirrorCapabilities
from .dm import DM
from .exceptions import (
    DMCapabilityError,
    DMConnectionError,
    DMDependencyError,
    DMDriverError,
    DMDriverWarning,
    DMError,
)
from .info import MirrorInfo, ParameterInfo
from .modes import TipTilt, ZernikeMode, zernike_vector

__all__ = [
    "DM",
    "DMP40",
    "DMCapabilityError",
    "DMConnectionError",
    "DMDependencyError",
    "DMDriverError",
    "DMDriverWarning",
    "DMError",
    "DeviceInfo",
    "MirrorCapabilities",
    "MirrorInfo",
    "ParameterInfo",
    "TipTilt",
    "ZernikeMode",
    "zernike_vector",
]
