"""Industrial camera interfaces and vendor backends."""

from qtools.camera.base import CameraBackend, CameraInfo
from qtools.camera.camera import Camera, get_backend, list_backends, register_backend
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
    CameraError,
)
from qtools.camera.backends.flir import FLIR

__all__ = [
    "Camera",
    "CameraAcquisitionError",
    "CameraBackend",
    "CameraConfigurationError",
    "CameraDependencyError",
    "CameraDiscoveryError",
    "CameraError",
    "CameraInfo",
    "FLIR",
    "get_backend",
    "list_backends",
    "register_backend",
]
