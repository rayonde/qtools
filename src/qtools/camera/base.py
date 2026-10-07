"""Common camera backend contracts.

The contract intentionally contains only operations shared by most industrial
cameras. Vendor-specific controls remain on the concrete backend, so adding a
Basler, Allied Vision, or GenICam backend does not require changing this API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class CameraInfo:
    """Small, vendor-neutral description returned during discovery."""

    serial: str
    model: str = "unknown"
    vendor: str = "unknown"
    index: int = 0


class CameraBackend(ABC):
    """Minimal lifecycle and acquisition interface for industrial cameras."""

    backend_name: ClassVar[str]

    @classmethod
    @abstractmethod
    def discover(cls, verbose: bool = True) -> list[CameraInfo]:
        """Discover cameras without opening one for acquisition."""

    @classmethod
    def info(cls, verbose: bool = True) -> list[str]:
        """Return discovered serial numbers, preserving the SLMSuite API."""

        return [camera.serial for camera in cls.discover(verbose=verbose)]

    @abstractmethod
    def __init__(self, **kwargs: Any) -> None:
        """Initialize one camera backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable camera name."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Camera model name."""

    @property
    @abstractmethod
    def shape(self) -> tuple[int, int]:
        """Returned image shape as ``(height, width)``."""

    @abstractmethod
    def get_image(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        """Acquire one image."""

    def capture(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        """Compatibility alias for :meth:`get_image`."""

        return self.get_image(timeout_s=timeout_s)

    def get_images(
        self,
        image_count: int,
        timeout_s: float = 1.0,
    ) -> npt.NDArray[np.generic]:
        """Acquire and stack multiple images using the single-frame API."""

        if image_count <= 0:
            raise ValueError("image_count must be positive.")
        return np.stack(
            [self.get_image(timeout_s=timeout_s) for _ in range(int(image_count))],
            axis=0,
        )

    def get_exposure(self) -> float:
        """Return exposure in seconds when supported by the backend."""

        raise NotImplementedError(f"Camera backend {self.backend_name!r} has no exposure control.")

    def set_exposure(self, exposure_s: float) -> float:
        """Set exposure in seconds when supported by the backend."""

        del exposure_s
        raise NotImplementedError(f"Camera backend {self.backend_name!r} has no exposure control.")

    def autoexpose(self, *args: Any, **kwargs: Any) -> float:
        """Automatically set exposure when supported by the backend."""

        del args, kwargs
        raise NotImplementedError(f"Camera backend {self.backend_name!r} has no autoexposure.")

    @abstractmethod
    def close(self) -> None:
        """Stop acquisition and release the camera handle."""

    def __enter__(self) -> "CameraBackend":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


__all__ = ["CameraBackend", "CameraInfo"]
