"""Backend contract for SLM devices."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from qtools.slm.display.displaymask import DisplayMask
    from qtools.slm.slm import SLMGeometry


class SLMBackend(ABC):
    """Minimal lifecycle and output interface used by :class:`SLM`."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def geometry(self) -> "SLMGeometry": ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def load(self, mask: "DisplayMask | npt.ArrayLike") -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...

    @abstractmethod
    def get_current_image(self) -> npt.NDArray[np.uint8] | None: ...

    @abstractmethod
    def save(self, filename: str) -> None: ...

    @abstractmethod
    def show(self) -> None: ...

    def __enter__(self) -> "SLMBackend":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()


__all__ = ["SLMBackend"]
