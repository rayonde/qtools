"""Vendor-neutral camera facade and backend registry."""

from __future__ import annotations

import importlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from qtools.camera.base import CameraBackend
from qtools.camera.exceptions import CameraConfigurationError, CameraDependencyError
from qtools.camera.image import CameraImage, to_uint8

_BACKEND_MODULES: dict[str, tuple[str, str] | type[CameraBackend]] = {
    "flir": ("qtools.camera.backends.flir", "FLIR"),
}


def list_camera(backend: str = "flir") -> None:
    """Print connected cameras and identifiers for ``target=...`` selection.

    Enumeration does not open a camera or provision the managed camera runtime.
    The function returns ``None`` so notebooks display only the formatted list.
    """

    get_backend(backend).discover(verbose=True)


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
        available = ", ".join(sorted(_BACKEND_MODULES))
        raise KeyError(f"Unknown camera backend {name!r}; available: {available}") from exc
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

    @property
    def info(self) -> dict[str, Any]:
        """Return current camera identity and acquisition settings."""

        return self._camera_info()

    def capture(
        self,
        timeout_s: float = 1.0,
        *,
        timeout: float | None = None,
        rgb: bool = False,
    ) -> CameraImage:
        """Acquire one frame as a NumPy-compatible :class:`CameraImage`.

        ``timeout`` is accepted as an alias for ``timeout_s``.  ``rgb=False``
        requests the native mono frame.  ``rgb=True`` is only accepted when the
        backend already returns an RGB/RGBA frame; this facade does not perform
        Bayer demosaicing.
        """

        timeout_s = self._resolve_timeout(timeout_s, timeout)
        values = np.asarray(self._backend.get_image(timeout_s=timeout_s))
        if not isinstance(rgb, bool):
            raise TypeError("rgb must be a bool.")
        if rgb and (values.ndim != 3 or values.shape[-1] not in (3, 4)):
            raise CameraConfigurationError(
                "rgb=True requires an RGB or RGBA frame; configure a color pixel "
                "format or use rgb=False for the native mono array."
            )
        return CameraImage(values, info=self._image_info(values))

    def get_image(
        self,
        timeout_s: float = 1.0,
        *,
        timeout: float | None = None,
        rgb: bool = False,
    ) -> CameraImage:
        return self.capture(timeout_s=timeout_s, timeout=timeout, rgb=rgb)

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

    def get_gain(self) -> float:
        """Return gain in dB when supported by the backend."""

        return float(getattr(self._backend, "get_gain")())

    def set_gain(self, gain_db: float) -> float:
        """Set gain in dB when supported by the backend."""

        return float(getattr(self._backend, "set_gain")(gain_db))

    @property
    def gain(self) -> float:
        return self.get_gain()

    @gain.setter
    def gain(self, value: float) -> None:
        self.set_gain(value)

    def get_format(self) -> str:
        """Return the active pixel format name, such as ``Mono8``."""

        return str(getattr(self._backend, "get_format")())

    def set_format(self, pixel_format: str) -> str:
        """Set the pixel format when supported by the backend."""

        return str(getattr(self._backend, "set_format")(pixel_format))

    @property
    def format(self) -> str:
        return self.get_format()

    @format.setter
    def format(self, value: str) -> None:
        self.set_format(value)

    @property
    def auto_exposure(self) -> bool:
        return bool(getattr(self._backend, "auto_exposure"))

    @auto_exposure.setter
    def auto_exposure(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("auto_exposure must be a bool.")
        setattr(self._backend, "auto_exposure", enabled)

    @property
    def auto_gain(self) -> bool:
        return bool(getattr(self._backend, "auto_gain"))

    @auto_gain.setter
    def auto_gain(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("auto_gain must be a bool.")
        setattr(self._backend, "auto_gain", enabled)

    def autoexpose(self, *args: Any, **kwargs: Any) -> float:
        return self._backend.autoexpose(*args, **kwargs)

    def autoexposure(self, *args: Any, **kwargs: Any) -> float:
        return self.autoexpose(*args, **kwargs)

    def exposure_auto(self, fraction: float = 0.8) -> float:
        return self._backend.exposure_auto(fraction=fraction)

    def save(
        self,
        filename: str | Path,
        preview: bool = False,
        *,
        overwrite: bool = False,
    ) -> CameraImage:
        """Capture and save one frame.

        With ``preview=True`` this delegates to :meth:`CameraImage.save`, so the
        filename suffix selects the exact output format and no companion
        ``.npy`` file is created.  The legacy ``preview=False`` path captures to
        NumPy data and writes the resolved ``.npy`` file.
        """

        image = self.capture()
        if preview:
            image.save(filename, overwrite=overwrite)
            return image

        data_filename, _ = self._resolve_filename(filename)
        if data_filename.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {data_filename}")
        data_filename.parent.mkdir(parents=True, exist_ok=True)
        np.save(data_filename, np.asarray(image))
        return image

    def save_image(self, filename: str | Path) -> None:
        """Save one capture as an 8-bit image."""

        self.capture().save(filename)

    def show(self) -> None:
        """Display one captured image using Pillow's default viewer."""

        self.capture().show()

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

    def _camera_info(self) -> dict[str, Any]:
        backend_name = str(
            getattr(self._backend, "backend_name", type(self._backend).__name__.lower())
        )
        info: dict[str, Any] = {
            "backend": backend_name,
            "name": self.name,
            "serial": self._optional_backend_attr("serial", self.name),
            "model": self.model,
            "shape": tuple(int(value) for value in self.shape),
            "bitdepth": self._optional_backend_attr("bitdepth"),
            "format": self._optional_backend_attr("format"),
            "exposure_s": self._optional_backend_attr("exposure_s"),
            "gain_db": self._optional_backend_attr("gain"),
            "auto_exposure": self._optional_backend_attr("auto_exposure"),
            "auto_gain": self._optional_backend_attr("auto_gain"),
        }
        return {key: value for key, value in info.items() if value is not None}

    def _image_info(self, image: npt.ArrayLike) -> dict[str, Any]:
        values = np.asarray(image)
        return {
            **self._camera_info(),
            "shape": tuple(int(value) for value in values.shape),
            "dtype": values.dtype.str,
            "nbytes": int(values.nbytes),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }

    def _optional_backend_attr(self, name: str, default: Any = None) -> Any:
        try:
            return getattr(self._backend, name)
        except Exception:
            return default

    @staticmethod
    def _resolve_timeout(timeout_s: float, timeout: float | None) -> float:
        if timeout is not None:
            if timeout_s != 1.0:
                raise TypeError("Specify either timeout_s or timeout, not both.")
            timeout_s = timeout
        timeout_s = float(timeout_s)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a finite positive number.")
        return timeout_s

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
        return to_uint8(image, bitdepth)


__all__ = ["Camera", "get_backend", "list_camera", "register_backend"]
