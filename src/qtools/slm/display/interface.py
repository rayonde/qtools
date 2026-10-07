"""Display output abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import numpy.typing as npt

from qtools.slm.display.displaymask import DisplayMask


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


__all__ = ["DisplayInterface"]
