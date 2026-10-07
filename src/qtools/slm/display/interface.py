"""Display output abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import numpy.typing as npt

from qtools.slm.display.displaymask import DisplayMask


def display_array(
    mask: DisplayMask | npt.ArrayLike,
    resolution: tuple[int, int],
) -> npt.NDArray[np.uint8]:
    """Validate and normalize encoded display data for a concrete display.

    A raw array is already display data, so it must fit the bound display and
    be representable by the 8-bit transport.  Higher-bit-depth data carries
    its bit-depth metadata in :class:`DisplayMask` and must be RGB-packed.
    """

    if isinstance(mask, DisplayMask) and mask.bits > 8 and not mask.rgb:
        raise ValueError(
            "Display masks above 8 bits must be RGB-packed before display output."
        )

    values = mask.array if isinstance(mask, DisplayMask) else np.asarray(mask)
    height, width = resolution[1], resolution[0]
    if values.ndim == 2:
        if values.shape != (height, width):
            raise ValueError(
                f"Display data shape {values.shape} does not match resolution {resolution}."
            )
    elif values.ndim == 3 and values.shape[-1] in (3, 4):
        if values.shape[:2] != (height, width):
            raise ValueError(
                f"Display data shape {values.shape[:2]} does not match resolution {resolution}."
            )
    else:
        raise ValueError("Display data must be grayscale or RGB(A).")

    if not np.issubdtype(values.dtype, np.number) or np.issubdtype(
        values.dtype, np.complexfloating
    ):
        raise TypeError("Display data must contain real numeric gray levels.")
    if not np.all(np.isfinite(values)) or np.any(values < 0) or np.any(values > 255):
        raise ValueError("Raw display data values must be in the range 0..255.")
    if np.issubdtype(values.dtype, np.floating) and not np.all(
        values == np.floor(values)
    ):
        raise ValueError("Raw display data must contain integer gray levels.")

    if values.ndim == 2:
        values = np.repeat(values[:, :, None], 3, axis=2)
    return np.ascontiguousarray(values[:, :, :3], dtype=np.uint8)


class DisplayInterface(ABC):
    @property
    @abstractmethod
    def resolution(self) -> tuple[int, int]: ...

    @abstractmethod
    def load(self, mask: DisplayMask | npt.ArrayLike) -> None: ...

    @abstractmethod
    def load_image(self, path: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...

    @abstractmethod
    def get_data(self) -> npt.NDArray[np.uint8]: ...

    @abstractmethod
    def save(self, filename: str) -> None: ...

    @abstractmethod
    def show(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


__all__ = ["DisplayInterface", "display_array"]
