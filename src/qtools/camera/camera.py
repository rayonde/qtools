"""Vendor-neutral camera facade and backend registry."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from qtools.camera.base import CameraBackend
from qtools.camera.exceptions import CameraDependencyError

_BACKEND_MODULES: dict[str, tuple[str, str] | type[CameraBackend]] = {
    "flir": ("qtools.camera.backends.flir", "FLIR"),
}


def list_backends() -> list[str]:
    """Return registered camera backend names."""

    return sorted(_BACKEND_MODULES)


def register_backend(name: str, backend: type[CameraBackend]) -> None:
    """Register an external backend class for future industrial-camera drivers."""

    if not name or not name.strip():
        raise ValueError("Backend name must not be empty.")
    if not issubclass(backend, CameraBackend):
        raise TypeError("backend must subclass CameraBackend.")
    _BACKEND_MODULES[name.lower()] = backend


def get_backend(name: str) -> type[CameraBackend]:
    """Load a backend lazily by name."""

    key = name.lower()
    try:
        registered = _BACKEND_MODULES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown camera backend {name!r}; available: {list_backends()}") from exc
    if isinstance(registered, type):
        return registered
    module_name, class_name = registered
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


class Camera:
    """High-level camera API shared by FLIR and future vendor backends."""

    _IMAGE_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
    )

    def __init__(self, backend: str = "flir", **kwargs: Any) -> None:
        self._backend = get_backend(backend)(**kwargs)

    @classmethod
    def info(cls, backend: str = "flir", verbose: bool = True) -> list[str]:
        """Discover cameras for a backend without opening one."""

        return get_backend(backend).info(verbose=verbose)

    @classmethod
    def list_backends(cls) -> list[str]:
        return list_backends()

    @property
    def backend(self) -> CameraBackend:
        return self._backend

    @property
    def cam(self) -> CameraBackend:
        """Compatibility alias used by the existing lab scripts."""

        return self._backend

    @property
    def name(self) -> str:
        return self._backend.name

    @property
    def model(self) -> str:
        return self._backend.model

    @property
    def shape(self) -> tuple[int, int]:
        return self._backend.shape

    def capture(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        return self._backend.get_image(timeout_s=timeout_s)

    def get_image(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        return self.capture(timeout_s=timeout_s)

    def get_images(self, image_count: int, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        return self._backend.get_images(image_count, timeout_s=timeout_s)

    def get_exposure(self) -> float:
        return self._backend.get_exposure()

    def set_exposure(self, exposure_s: float) -> float:
        return self._backend.set_exposure(exposure_s)

    @property
    def exposure_s(self) -> float:
        return self.get_exposure()

    @exposure_s.setter
    def exposure_s(self, value: float) -> None:
        self.set_exposure(value)

    def autoexpose(self, *args: Any, **kwargs: Any) -> float:
        return self._backend.autoexpose(*args, **kwargs)

    def autoexposure(self, *args: Any, **kwargs: Any) -> float:
        return self.autoexpose(*args, **kwargs)

    def exposure_auto(self, fraction: float = 0.8) -> float:
        return self._backend.exposure_auto(fraction=fraction)

    def save(self, filename: str | Path, preview: bool = False) -> npt.NDArray[np.generic]:
        """Save raw NumPy data and optionally an 8-bit preview."""

        image = self.capture()
        data_filename, image_filename = self._resolve_filename(filename)
        np.save(data_filename, image)
        if preview:
            self._write_image(image_filename, image)
        return image

    def save_image(self, filename: str | Path) -> None:
        """Save one capture as an 8-bit image."""

        self._write_image(filename, self.capture())

    def show(self) -> None:
        """Display one captured image using Pillow's default viewer."""

        try:
            from PIL import Image
        except ImportError as exc:
            raise CameraDependencyError("Camera.show() requires Pillow.") from exc
        image = self._to_uint8(self.capture(), getattr(self._backend, "bitdepth", None))
        Image.fromarray(image).show()

    def monitor(self, interval_s: float = 0.5) -> None:
        """Continuously display frames until the plotting window is closed."""

        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise CameraDependencyError("Camera.monitor() requires matplotlib.") from exc
        plt.ion()
        figure, axis = plt.subplots()
        graph = axis.imshow(self.capture())
        try:
            while plt.fignum_exists(figure.number):
                plt.pause(interval_s)
                graph.set_data(self.capture())
                figure.canvas.draw_idle()
        finally:
            plt.ioff()
            plt.close(figure)

    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> "Camera":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        """Expose vendor-specific backend controls without polluting the facade."""

        backend = self.__dict__.get("_backend")
        if backend is None:
            raise AttributeError(name)
        return getattr(backend, name)

    @classmethod
    def _resolve_filename(cls, filename: str | Path) -> tuple[Path, Path]:
        path = Path(filename)
        if path.suffix.lower() == ".npy":
            return path, Path(f"{path}.png")
        image_path = path if path.suffix.lower() in cls._IMAGE_EXTENSIONS else Path(f"{path}.png")
        return Path(f"{path}.npy"), image_path

    def _write_image(self, filename: str | Path, image: npt.ArrayLike) -> None:
        try:
            import imageio.v3 as iio
        except ImportError as exc:
            raise CameraDependencyError("Saving camera previews requires imageio.") from exc
        iio.imwrite(filename, self._to_uint8(image, getattr(self._backend, "bitdepth", None)))

    @staticmethod
    def _to_uint8(image: npt.ArrayLike, bitdepth: int | None = None) -> npt.NDArray[np.uint8]:
        values = np.asarray(image)
        if values.dtype == np.uint8:
            return values
        if values.dtype.kind == "f":
            values = np.clip(values, 0, 1) * 255
        elif bitdepth is not None and bitdepth > 8:
            values = np.right_shift(values.astype(np.uint64), bitdepth - 8)
        else:
            max_value = float(np.max(values, initial=0))
            if max_value > 255:
                values = values / max_value * 255 if max_value else values
        return np.asarray(np.clip(values, 0, 255), dtype=np.uint8)


__all__ = ["Camera", "get_backend", "list_backends", "register_backend"]
