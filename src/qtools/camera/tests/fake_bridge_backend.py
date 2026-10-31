"""Small camera implementation used by the cross-process bridge tests."""

from __future__ import annotations

import numpy as np

from qtools.camera.image import CameraImage


class FakeBridgeCamera:
    def __init__(self, serial: str = "bridge-fake", **kwargs: object) -> None:
        self._name = serial
        self._exposure_s = 0.01
        self._gain_db = 0.0
        self._format = "Mono16"
        self._auto_exposure = False
        self._auto_gain = False
        self._closed = False
        self.extra = dict(kwargs)

    @property
    def name(self) -> str:
        return self._name

    @property
    def serial(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return "FakeBridge"

    @property
    def shape(self) -> tuple[int, int]:
        return (2, 3)

    @property
    def info(self) -> dict[str, object]:
        return {
            "backend": "fake",
            "serial": self._name,
            "model": self.model,
            "shape": self.shape,
            "format": self._format,
            "exposure_s": self._exposure_s,
            "gain_db": self._gain_db,
            "auto_exposure": self._auto_exposure,
            "auto_gain": self._auto_gain,
        }

    @property
    def auto_exposure(self) -> bool:
        return self._auto_exposure

    @auto_exposure.setter
    def auto_exposure(self, enabled: bool) -> None:
        self._auto_exposure = bool(enabled)

    @property
    def auto_gain(self) -> bool:
        return self._auto_gain

    @auto_gain.setter
    def auto_gain(self, enabled: bool) -> None:
        self._auto_gain = bool(enabled)

    @property
    def format(self) -> str:
        return self._format

    @format.setter
    def format(self, value: str) -> None:
        self._format = str(value)

    @property
    def gain(self) -> float:
        return self._gain_db

    @gain.setter
    def gain(self, value: float) -> None:
        self._gain_db = float(value)

    def set_gain(self, gain_db: float) -> float:
        self.gain = gain_db
        return self._gain_db

    def capture(
        self,
        timeout_s: float = 1.0,
        *,
        timeout: float | None = None,
        rgb: bool = False,
    ) -> CameraImage:
        del timeout
        values = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)
        if rgb:
            values = np.repeat(values[..., None], 3, axis=2)
        return CameraImage(
            values,
            info={
                **self.info,
                "dtype": values.dtype.str,
                "nbytes": values.nbytes,
                "timeout_s": timeout_s,
            },
        )

    def get_images(self, image_count: int, timeout_s: float = 1.0) -> np.ndarray:
        return np.stack([self.capture(timeout_s=timeout_s) + index for index in range(image_count)])

    def get_extra(self) -> dict[str, object]:
        return dict(self.extra)

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
