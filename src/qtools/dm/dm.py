"""High-level deformable mirror interface."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Any

from .backends.Thorlabs.DMP40 import DMP40, DeviceInfo, MirrorCapabilities
from .info import MirrorInfo
from .modes import TipTilt, ZernikeMode


class DM:
    """Modal mirror controller; the currently supported backend is ``dmp40``."""

    def __init__(self, backend: str = "dmp40", **kwargs: Any) -> None:
        if not isinstance(backend, str) or backend.lower() != "dmp40":
            raise ValueError("The supported DM backend is 'dmp40'.")
        self._backend = DMP40(**kwargs)

    @property
    def backend(self) -> DMP40:
        return self._backend

    @classmethod
    def discover(cls, **kwargs: Any) -> list[DeviceInfo]:
        return DMP40.discover(**kwargs)

    @property
    def is_connected(self) -> bool:
        return self.backend.is_connected

    @property
    def info(self) -> MirrorInfo:
        """Printable parameter ranges and last commanded values for this device."""
        return self.backend.info

    @property
    def capabilities(self) -> MirrorCapabilities:
        return self.backend.capabilities

    @property
    def zernikes(self) -> dict[ZernikeMode, float] | None:
        """Last commanded modal state, or None when unknown."""
        return self.backend.zernikes

    @property
    def tip_tilt(self) -> TipTilt | None:
        return self.backend.tip_tilt

    def connect(self) -> DM:
        self.backend.connect()
        return self

    def close(self) -> None:
        """Disconnect without changing the mirror output."""
        self.backend.close()

    def disconnect(self) -> None:
        self.close()

    def set_orientation(self, *, pitch: float, yaw: float) -> None:
        """Normalized pitch=SDK Y, yaw=SDK X; these are not physical angles."""
        self.backend.set_orientation(pitch=pitch, yaw=yaw)

    def set_tip_tilt(self, *, x: float, y: float) -> None:
        self.backend.set_tip_tilt(x=x, y=y)

    def set_tilt(self, *, amplitude: float, azimuth_deg: float) -> None:
        self.backend.set_tilt(amplitude=amplitude, azimuth_deg=azimuth_deg)

    def set_zernike(self, mode: ZernikeMode | str, amplitude: float) -> None:
        """Replace the shape with a single mode; all other shape modes become zero."""
        self.backend.set_zernike(mode, amplitude)

    def set_zernikes(self, coefficients: Mapping[ZernikeMode | str, Real]) -> None:
        """Replace the shape with a mode combination; omitted modes become zero."""
        self.backend.set_zernikes(coefficients)

    def update_zernikes(self, coefficients: Mapping[ZernikeMode | str, Real]) -> None:
        """Update selected modes of a previously issued modal command."""
        self.backend.update_zernikes(coefficients)

    def zero_zernikes(self) -> None:
        """Apply the SDK reference shape; this is not a measured flat wavefront."""
        self.backend.zero_zernikes()

    def calculate_zernikes(self, coefficients: Mapping[ZernikeMode | str, Real]):
        """Calculate a voltage pattern using the connected SDK, without applying it."""
        return self.backend.calculate_zernikes(coefficients)

    def relax(
        self, *, part: str = "both", interval_s: float = 0.01, max_steps: int = 10000
    ) -> int:
        return self.backend.relax(part=part, interval_s=interval_s, max_steps=max_steps)

    def read_voltages(self):
        return self.backend.read_voltages()

    def __enter__(self) -> DM:  # noqa: PYI034 - Python 3.10, no typing.Self
        return self.connect()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.backend.__exit__(exc_type, exc, traceback)
