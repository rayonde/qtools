"""In-memory display for tests and explicitly headless operation."""

from __future__ import annotations

from pathlib import Path

import imageio.v3 as iio
import numpy as np
import numpy.typing as npt

from qtools.slm.display.displaymask import DisplayMask
from qtools.slm.display.interface import DisplayInterface, display_array
from qtools.slm.utils import save_image, show_image


class HeadlessDisplay(DisplayInterface):
    def __init__(self, resolution: tuple[int, int]):
        self._resolution = resolution
        self._current = np.zeros((resolution[1], resolution[0], 3), dtype=np.uint8)
        self._previous = self._current.copy()

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    def load(self, mask: DisplayMask | npt.ArrayLike) -> None:
        values = display_array(mask, self.resolution)
        self._previous = self._current.copy()
        self._current = values.copy()

    def load_image(self, path: str) -> None:
        self.load(iio.imread(Path(path)))

    def clear(self) -> None:
        self._previous = self._current.copy()
        self._current = np.zeros_like(self._current)

    def undo(self) -> None:
        self._current, self._previous = self._previous, self._current

    def get_data(self) -> npt.NDArray[np.uint8]:
        return self._current.copy()

    def save(self, filename: str) -> None:
        save_image(self._current, filename)

    def show(self) -> None:
        show_image(self._current)

    def close(self) -> None:
        self._current = np.zeros((0, 0, 3), dtype=np.uint8)
        self._previous = self._current.copy()


__all__ = ["HeadlessDisplay"]
