"""Industrial camera interfaces and vendor backends."""

from qtools.camera.backends.daheng import DAHENG
from qtools.camera.backends.flir import FLIR
from qtools.camera.base import CameraBackend
from qtools.camera.bridge import RemoteCamera
from qtools.camera.camera import (
    Camera,
    get_backend,
    list_camera,
    register_backend,
)
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraBridgeError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
    CameraError,
)
from qtools.camera.image import CameraImage

__all__ = [
    "Camera",
    "CameraAcquisitionError",
    "CameraBackend",
    "CameraBridgeError",
    "CameraConfigurationError",
    "CameraDependencyError",
    "CameraDiscoveryError",
    "CameraError",
    "CameraImage",
    "DAHENG",
    "FLIR",
    "RemoteCamera",
    "get_backend",
    "list_camera",
    "register_backend",
]