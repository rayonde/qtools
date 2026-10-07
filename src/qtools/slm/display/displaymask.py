"""DisplayMask: device gray levels and optional RGB transport encoding."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import imageio.v3 as iio
import numpy as np
import numpy.typing as npt

from qtools.slm.utils import show_image

if TYPE_CHECKING:
    from qtools.slm.phase.phasemask import PhaseMask


SUPPORTED_EXTENSIONS = (".png", ".bmp", ".gif", ".tif", ".tiff")


class DisplayMask:
    """Encoded image to be sent to an SLM display backend."""

    def __init__(self, array: npt.ArrayLike, *, bits: int = 8, rgb: bool = False):
        if not 1 <= int(bits) <= 16:
            raise ValueError("bits must be between 1 and 16.")
        self.bits = int(bits)
        self.rgb = bool(rgb)
        values = np.asarray(array)
        if self.rgb:
            if values.ndim != 3 or values.shape[-1] != 3:
                raise ValueError("RGB DisplayMask data must have shape (height, width, 3).")
            self.array = np.ascontiguousarray(np.clip(values, 0, 255).astype(np.uint8))
        else:
            if values.ndim != 2:
                raise ValueError("Grayscale DisplayMask data must have shape (height, width).")
            dtype = np.uint8 if self.bits <= 8 else np.uint16
            self.array = np.ascontiguousarray(np.clip(values, 0, (1 << self.bits) - 1).astype(dtype))

    @classmethod
    def zeros(cls, resolution: tuple[int, int], *, bits: int = 8) -> "DisplayMask":
        """Create a zero-valued grayscale mask for ``(width, height)``."""

        width, height = resolution
        return cls(np.zeros((height, width), dtype=np.uint8 if bits <= 8 else np.uint16), bits=bits)

    @classmethod
    def from_phase(cls, phase: "PhaseMask", *, bits: int = 8, rgb: bool = False) -> "DisplayMask":
        levels = phase.geometry.quantize_phase(phase.array, int(bits))
        mask = cls(levels, bits=bits, rgb=False)
        return mask.to_rgb() if rgb else mask

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape[:2]

    @property
    def resolution(self) -> tuple[int, int]:
        height, width = self.shape
        return width, height

    @property
    def max_level(self) -> int:
        return (1 << self.bits) - 1

    def copy(self) -> "DisplayMask":
        return DisplayMask(self.array.copy(), bits=self.bits, rgb=self.rgb)

    def to_rgb(self) -> "DisplayMask":
        if self.rgb:
            return self.copy()
        if self.bits <= 8:
            high = self.array.astype(np.uint8)
            low = np.zeros_like(high)
        else:
            shift = self.bits - 8
            high = (self.array.astype(np.uint16) >> shift).astype(np.uint8)
            low = (self.array.astype(np.uint16) & ((1 << shift) - 1)).astype(np.uint8)
        return DisplayMask(np.stack((high, low, np.zeros_like(high)), axis=-1), bits=self.bits, rgb=True)

    def to_grayscale(self) -> "DisplayMask":
        if not self.rgb:
            return self.copy()
        return DisplayMask(self.array[:, :, 0], bits=self.bits)

    def flat(self, level: int = 0) -> "DisplayMask":
        return DisplayMask(np.full(self.shape, level), bits=self.bits)

    def random(self) -> "DisplayMask":
        return DisplayMask(np.random.randint(0, self.max_level + 1, size=self.shape), bits=self.bits)

    def crop(self, left: int = 0, right: int | None = None, top: int = 0, bottom: int | None = None, *, background: int = 0) -> "DisplayMask":
        right = self.shape[1] if right is None else right
        bottom = self.shape[0] if bottom is None else bottom
        result = np.full(self.shape, background, dtype=self.array.dtype)
        result[top:bottom, left:right] = self.to_grayscale().array[top:bottom, left:right]
        return DisplayMask(result, bits=self.bits)

    def flip(self) -> "DisplayMask":
        return DisplayMask(np.fliplr(self.to_grayscale().array), bits=self.bits)

    def save(self, filename: str | Path) -> None:
        path = Path(filename)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"File extension must be one of {SUPPORTED_EXTENSIONS}.")
        iio.imwrite(path, self.array)

    def show(self) -> None:
        show_image(self.array)


__all__ = ["DisplayMask", "SUPPORTED_EXTENSIONS"]
