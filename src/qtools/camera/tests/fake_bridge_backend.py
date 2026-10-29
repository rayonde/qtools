"""Small camera implementation used by the cross-process bridge tests."""

from __future__ import annotations

import numpy as np


class FakeBridgeCamera:
    def __init__(self, serial: str = "bridge-fake", **kwargs: object) -> None:
        self._name = serial
        self._exposure_s = 0.01
        self._closed = False
        self.extra = dict(kwargs)

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return "FakeBridge"

    @property
    def shape(self) -> tuple[int, int]:
        return (2, 3)

    def capture(self, timeout_s: float = 1.0) -> np.ndarray:
        del timeout_s
        return np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)

    def get_images(self, image_count: int, timeout_s: float = 1.0) -> np.ndarray:
        return np.stack([self.capture(timeout_s=timeout_s) + index for index in range(image_count)])

    def get_exposure(self) -> float:
        return self._exposure_s

    def set_exposure(self, exposure_s: float) -> float:
        self._exposure_s = float(exposure_s)
        return self._exposure_s

    def autoexpose(self, *, fraction: float = 0.8) -> float:
        return fraction

    def explode(self) -> None:
        raise RuntimeError("intentional bridge failure")

    def close(self) -> None:
        self._closed = True
