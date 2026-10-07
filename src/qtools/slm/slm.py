"""High-level SLM controller and geometry context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from qtools.slm.backends import get_backend
from qtools.slm.phase.phasemask import PhaseRegion


@dataclass
class SLMGeometry:
    """Physical geometry and calibration context shared by phase masks."""

    resolution: tuple[int, int]
    pitch_um: tuple[float, float]
    wavelength: float
    bitdepth: int = 8
    gray_range: int | None = None
    lut: npt.NDArray[np.uint16] | None = None
    _grid_cache: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] | None = field(
        default=None, init=False, repr=False
    )

    @property
    def shape(self) -> tuple[int, int]:
        return self.resolution[1], self.resolution[0]

    @property
    def grid(self) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        if self._grid_cache is None:
            width, height = self.resolution
            x = (np.arange(width) - (width - 1) / 2) * self.pitch_um[0] * 1e-6 / self.wavelength
            y = (np.arange(height) - (height - 1) / 2) * self.pitch_um[1] * 1e-6 / self.wavelength
            self._grid_cache = np.meshgrid(x, y)
        return tuple(axis.copy() for axis in self._grid_cache)  # type: ignore[return-value]

    def quantize_phase(self, phase: npt.NDArray[np.float64], bits: int) -> npt.NDArray[np.integer]:
        """Map radians to device gray levels, including the active 8-bit LUT."""

        if not 1 <= int(bits) <= 16:
            raise ValueError("bits must be between 1 and 16.")
        max_level = (1 << int(bits)) - 1
        wrapped = np.mod(phase, 2 * np.pi)
        phase_range = self.gray_range if self.gray_range is not None and bits == self.bitdepth else max_level
        values = np.clip(np.rint(wrapped / (2 * np.pi) * phase_range), 0, max_level)
        if self.lut is not None and bits == 8:
            values = np.asarray(self.lut, dtype=np.uint16)[values.astype(np.uint8)]
        return values.astype(np.uint8 if bits <= 8 else np.uint16)


class SLM:
    """Unified controller for Holoeye and simulated SLM outputs."""

    def __init__(self, backend: str = "holoeye", **kwargs: Any):
        backend_class = get_backend(backend)
        self.backend = backend_class(**kwargs)

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def model(self) -> str:
        return self.backend.model

    @property
    def geometry(self) -> SLMGeometry:
        return self.backend.geometry

    @property
    def resolution(self) -> tuple[int, int]:
        return self.geometry.resolution

    @property
    def shape(self) -> tuple[int, int]:
        return self.geometry.shape

    @property
    def is_connected(self) -> bool:
        return self.backend.is_connected

    def create_canvas(self) -> PhaseRegion:
        """Return an empty full-screen PhaseRegion."""

        return PhaseRegion(self.geometry)

    def connect(self) -> "SLM":
        self.backend.connect()
        return self

    def disconnect(self) -> None:
        self.backend.disconnect()

    def __enter__(self) -> "SLM":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    def load(self, display_mask: Any) -> None:
        self.backend.load(display_mask)

    def load_phase(self, phase_mask: Any, *, bits: int | None = None, rgb: bool = False) -> None:
        from qtools.slm.display.displaymask import DisplayMask

        if isinstance(phase_mask, DisplayMask):
            raise TypeError("load_phase() expects a PhaseMask; use load() for DisplayMask.")
        mask = phase_mask.to_display(bits=self.geometry.bitdepth if bits is None else bits, rgb=rgb)
        self.load(mask)

    def clear(self) -> None:
        self.backend.clear()

    def undo(self) -> None:
        self.backend.undo()

    def get_current_image(self) -> npt.NDArray[np.uint8] | None:
        return self.backend.get_current_image()

    def save(self, filename: str) -> None:
        self.backend.save(filename)

    def show(self) -> None:
        self.backend.show()


__all__ = ["SLM", "SLMGeometry"]
