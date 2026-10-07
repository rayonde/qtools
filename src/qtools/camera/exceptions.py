"""Exceptions raised by :mod:`qtools.camera`."""

from __future__ import annotations


class CameraError(RuntimeError):
    """Base class for camera errors."""


class CameraDependencyError(CameraError, ImportError):
    """A vendor SDK or one of its Python bindings is unavailable."""


class CameraDiscoveryError(CameraError):
    """No compatible camera was found or the requested camera is unavailable."""


class CameraConfigurationError(CameraError):
    """A camera could not be configured or initialized."""


class CameraAcquisitionError(CameraError):
    """A frame could not be acquired or decoded."""


__all__ = [
    "CameraAcquisitionError",
    "CameraConfigurationError",
    "CameraDependencyError",
    "CameraDiscoveryError",
    "CameraError",
]
