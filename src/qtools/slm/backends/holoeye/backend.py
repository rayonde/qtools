"""Holoeye backend using the SLM's bound display monitor."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import numpy.typing as npt

from qtools.slm.backends.base import SLMBackend
from qtools.slm.backends.holoeye.calibration import load_lut
from qtools.slm.backends.holoeye.models import HoloeyeModel, get_model
from qtools.slm.display.displaymask import DisplayMask
from qtools.slm.display.headless import HeadlessDisplay
from qtools.slm.monitor import MonitorBinding, resolve_monitor
from qtools.slm.slm import SLMGeometry


class HoloeyeBackend(SLMBackend):
    """Holoeye model plus second-monitor display output."""

    def __init__(
        self,
        *,
        model: str = "LETO-II",
        wavelength: float = 532e-9,
        monitor: int | None = None,
        headless: bool = False,
        lut: str | Path | Sequence[int] | npt.NDArray[np.integer] | None = None,
        gray_range: int | None = None,
        rescaling: str | None = None,
    ):
        self.spec: HoloeyeModel = get_model(model)
        lut_array = load_lut(lut) if lut is not None else None
        self._geometry = SLMGeometry(
            resolution=self.spec.resolution,
            pitch_um=self.spec.pitch_um,
            wavelength=float(wavelength),
            bitdepth=self.spec.bitdepth,
            gray_range=gray_range,
            lut=lut_array,
        )
        self._monitor_index = monitor
        self._headless = headless
        self._rescaling = rescaling
        self._binding: MonitorBinding | None = None
        self._display = None
        self._connected = False

    @property
    def name(self) -> str:
        return "holoeye"

    @property
    def model(self) -> str:
        return self.spec.name

    @property
    def geometry(self) -> SLMGeometry:
        return self._geometry

    @property
    def monitor(self) -> MonitorBinding | None:
        return self._binding

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            return
        if self._headless:
            self._display = HeadlessDisplay(self.geometry.resolution)
        else:
            self._binding = resolve_monitor(self._monitor_index)
            if self._binding.resolution != self.geometry.resolution:
                raise ValueError(
                    f"Monitor {self._binding.index} has resolution {self._binding.resolution}, "
                    f"but {self.model} requires {self.geometry.resolution}."
                )
            from qtools.slm.display.qt import QtDisplay

            self._display = QtDisplay(self._binding, rescaling=self._rescaling)
        self._connected = True

    def disconnect(self) -> None:
        if self._display is not None:
            self._display.close()
        self._display = None
        self._connected = False

    def _require_display(self):
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
        if self._display is None:
            return None
        return self._display.get_data()

    def save(self, filename: str) -> None:
        self._require_display().save(filename)

    def show(self) -> None:
        self._require_display().show()


__all__ = ["HoloeyeBackend"]
