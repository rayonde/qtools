"""slmsuite-backed simulated SLM with dependency loading deferred to use."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from qtools.slm.backends.base import SLMBackend
from qtools.slm.display.displaymask import DisplayMask
from qtools.slm.display.headless import HeadlessDisplay
from qtools.slm.slm import SLMGeometry


class SimulatedBackend(SLMBackend):
    """Software backend that initializes slmsuite only when selected."""

    def __init__(
        self,
        *,
        resolution: tuple[int, int] = (1920, 1080),
        pitch_um: float | tuple[float, float] = 6.4,
        wavelength: float = 532e-9,
        bitdepth: int = 8,
        **kwargs: Any,
    ):
        try:
            from slmsuite.hardware.slms.simulated import SimulatedSLM
        except ImportError as exc:
            raise ImportError(
                "The simulated backend requires optional dependency 'slmsuite'."
            ) from exc
        pitch = (pitch_um, pitch_um) if not isinstance(pitch_um, tuple) else pitch_um
        self.device = SimulatedSLM(
            resolution=resolution,
            pitch_um=pitch,
            bitdepth=bitdepth,
            wav_um=float(wavelength) * 1e6,
            **kwargs,
        )
        self._geometry = SLMGeometry(
            resolution=resolution,
            pitch_um=(float(pitch[0]), float(pitch[1])),
            wavelength=float(wavelength),
            bitdepth=bitdepth,
        )
        self._display: HeadlessDisplay | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "simulated"

    @property
    def model(self) -> str:
        return "slmsuite-SimulatedSLM"

    @property
    def geometry(self) -> SLMGeometry:
        return self._geometry

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if not self._connected:
            self._display = HeadlessDisplay(self.geometry.resolution)
            self._connected = True

    def disconnect(self) -> None:
        if self._display is not None:
            self._display.close()
        self._display = None
        self._connected = False

    def _require_display(self) -> HeadlessDisplay:
        if not self._connected or self._display is None:
            raise RuntimeError("SLM is not connected.")
        return self._display

    def load(self, mask: DisplayMask | npt.ArrayLike) -> None:
        if isinstance(mask, DisplayMask) and mask.resolution != self.geometry.resolution:
            raise ValueError(
                f"DisplayMask resolution {mask.resolution} does not match SLM resolution {self.geometry.resolution}."
            )
        self._require_display().load(mask)

    def clear(self) -> None:
        self._require_display().clear()

    def undo(self) -> None:
        self._require_display().undo()

    def get_current_image(self) -> npt.NDArray[np.uint8] | None:
        return None if self._display is None else self._display.get_data()

    def save(self, filename: str) -> None:
        self._require_display().save(filename)

    def show(self) -> None:
        self._require_display().show()


__all__ = ["SimulatedBackend"]
