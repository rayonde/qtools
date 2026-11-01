"""Thin, typed adapter around Daheng Imaging's official ``gxipy`` binding.

``gxipy`` is shipped with the Galaxy/IndustryCam SDK and is not available on
PyPI.  This module is the only place in qtools that imports or manipulates the
official Python objects.  The public camera backend consumes the small wrappers
defined here instead of relying on gxipy implementation details directly.
"""

from __future__ import annotations

import importlib
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt

from qtools.camera.base import CameraInfo
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
)

_GXIPY_MODULE: Any | None = None


def _sdk_path_candidates() -> list[Path]:
    """Return directories where the official Galaxy Python package may live."""

    candidates: list[Path] = []
    development = os.environ.get("GALAXY_SDK_DEVELOPMENT")
    if development:
        candidates.append(Path(development) / "Samples" / "Python")

    genicam_root = os.environ.get("GALAXY_GENICAM_ROOT")
    if genicam_root:
        candidates.append(
            Path(genicam_root).parent / "Development" / "Samples" / "Python"
        )

    for variable in ("PROGRAMFILES", "PROGRAMW6432", "ProgramFiles"):
        program_files = os.environ.get(variable)
        if program_files:
            candidates.extend(
                (
                    Path(program_files)
                    / "IndustryCam"
                    / "Development"
                    / "Samples"
                    / "Python",
                    Path(program_files)
                    / "Daheng Imaging"
                    / "Galaxy"
                    / "Development"
                    / "Samples"
                    / "Python",
                )
            )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def load_gxipy() -> Any:
    """Import and cache the official ``gxipy`` package."""

    global _GXIPY_MODULE
    if _GXIPY_MODULE is not None:
        return _GXIPY_MODULE

    for candidate in _sdk_path_candidates():
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=SyntaxWarning)
            _GXIPY_MODULE = importlib.import_module("gxipy")
    except Exception as exc:
        locations = "\n".join(f"  - {path}" for path in _sdk_path_candidates())
        raise CameraDependencyError(
            "The Daheng Galaxy Python binding 'gxipy' is unavailable. Install "
            "the Daheng Galaxy/IndustryCam SDK, or add its "
            "Development/Samples/Python directory to PYTHONPATH.\n"
            f"Checked:\n{locations or '  (no SDK locations detected)'}"
        ) from exc
    return _GXIPY_MODULE


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def _interface_details(gx: Any, row: Mapping[str, Any]) -> tuple[str, str]:
    classes = getattr(gx, "GxDeviceClassList", None)
    device_class = int(row.get("device_class") or 0)
    if classes is not None and device_class == getattr(classes, "GEV", 2):
        return "GigE Vision", _text(row, "ip") or _text(row, "mac")
    if classes is not None and device_class == getattr(classes, "U3V", 3):
        return "USB3 Vision", _text(row, "display_name") or _text(row, "user_id")
    if classes is not None and device_class == getattr(classes, "USB2", 1):
        return "USB2", _text(row, "display_name") or _text(row, "user_id")
    return "unknown", _text(row, "display_name") or _text(row, "user_id")


@dataclass(frozen=True, slots=True)
class GalaxyDeviceInfo:
    """Normalized device row returned by ``DeviceManager.update_all_device_list``."""

    index: int
    serial: str
    model: str
    vendor: str
    device_id: str
    user_id: str
    display_name: str
    interface_type: str
    interface_id: str
    interface_name: str
    port: str
    ip: str
    mac: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_row(
        cls,
        gx: Any,
        row: Mapping[str, Any],
        index: int,
    ) -> "GalaxyDeviceInfo":
        interface_type, port = _interface_details(gx, row)
        return cls(
            index=index,
            serial=_text(row, "sn") or _text(row, "device_id") or f"cam_{index}",
            model=_text(row, "model_name") or "unknown",
            vendor=_text(row, "vendor_name") or "Daheng Imaging",
            device_id=_text(row, "device_id"),
            user_id=_text(row, "user_id"),
            display_name=_text(row, "display_name"),
            interface_type=interface_type,
            interface_id=_text(row, "interface_id"),
            interface_name=_text(row, "nic_description"),
            port=port,
            ip=_text(row, "ip"),
            mac=_text(row, "mac"),
            raw=dict(row),
        )

    def as_camera_info(self) -> CameraInfo:
        """Convert a Galaxy device row to qtools' vendor-neutral camera info."""

        return CameraInfo(
            serial=self.serial,
            model=self.model,
            vendor=self.vendor,
            index=self.index,
            device_id=self.device_id,
            interface_type=self.interface_type,
            interface_id=self.interface_id,
            interface_name=self.interface_name,
            port=self.port,
        )


class GalaxyFeatureControl:
    """Small wrapper around the official remote-device feature controller."""

    def __init__(self, remote_control: Any) -> None:
        self._remote = remote_control

    def enum(self, name: str) -> tuple[int, str]:
        try:
            value, symbol = self._remote.get_enum_feature(name).get()
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng enum feature {name!r}: {exc}"
            ) from exc
        return int(value), str(symbol)

    def enum_range(self, name: str) -> dict[str, int]:
        try:
            values = self._remote.get_enum_feature(name).get_range()
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng enum range {name!r}: {exc}"
            ) from exc
        return {str(key): int(value) for key, value in values.items()}

    def enum_symbol(self, name: str) -> str:
        return self.enum(name)[1]

    def set_enum_symbol(self, name: str, symbol: str) -> None:
        values = self.enum_range(name)
        selected = next(
            (
                value
                for entry, value in values.items()
                if entry.casefold() == symbol.casefold()
            ),
            None,
        )
        if selected is None:
            raise CameraConfigurationError(
                f"Daheng feature {name!r} does not support {symbol!r}; "
                f"available values: {', '.join(values)}"
            )
        try:
            self._remote.get_enum_feature(name).set(selected)
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not set Daheng enum feature {name!r} to {symbol!r}: {exc}"
            ) from exc

    def try_set_enum_symbol(self, name: str, symbol: str) -> bool:
        try:
            self.set_enum_symbol(name, symbol)
            return True
        except CameraConfigurationError:
            return False

    def int_value(self, name: str) -> int:
        try:
            return int(self._remote.get_int_feature(name).get())
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng integer feature {name!r}: {exc}"
            ) from exc

    def float_value(self, name: str) -> float:
        try:
            return float(self._remote.get_float_feature(name).get())
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng float feature {name!r}: {exc}"
            ) from exc

    def float_range(self, name: str) -> dict[str, Any]:
        try:
            return dict(self._remote.get_float_feature(name).get_range())
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng float range {name!r}: {exc}"
            ) from exc

    def set_float(self, name: str, value: float) -> None:
        try:
            self._remote.get_float_feature(name).set(float(value))
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not set Daheng float feature {name!r}: {exc}"
            ) from exc


class GalaxyCamera:
    """Own one opened Galaxy device and its data stream."""

    def __init__(self, manager: "GalaxyDeviceManager", handle: Any) -> None:
        self._manager = manager
        self._handle = handle
        self._features = GalaxyFeatureControl(
            handle.get_remote_device_feature_control()
        )
        self._acquiring = False

    @property
    def features(self) -> GalaxyFeatureControl:
        return self._features

    @property
    def acquiring(self) -> bool:
        return self._acquiring

    def stream_on(self) -> None:
        if self._handle is None or self._acquiring:
            return
        try:
            self._handle.stream_on()
        except Exception as exc:
            raise CameraAcquisitionError(
                f"Could not start Daheng acquisition: {exc}"
            ) from exc
        self._acquiring = True

    def stream_off(self) -> None:
        if self._handle is None or not self._acquiring:
            return
        try:
            self._handle.stream_off()
        except Exception as exc:
            raise CameraAcquisitionError(
                f"Could not stop Daheng acquisition: {exc}"
            ) from exc
        finally:
            self._acquiring = False

    def capture(self, timeout_ms: int) -> npt.NDArray[np.generic]:
        if self._handle is None or not self._acquiring:
            raise CameraAcquisitionError("Daheng camera is not acquiring.")
        try:
            raw = self._handle.data_stream[0].get_image(timeout=int(timeout_ms))
        except Exception as exc:
            raise CameraAcquisitionError(
                f"Daheng image acquisition failed: {exc}"
            ) from exc
        if raw is None:
            raise CameraAcquisitionError("Daheng image acquisition timed out.")
        try:
            image = raw.get_numpy_array()
        except Exception as exc:
            raise CameraAcquisitionError(
                f"Could not convert the Daheng frame to NumPy: {exc}"
            ) from exc
        if image is None:
            try:
                frame_format = self.features.enum_symbol("PixelFormat")
            except CameraConfigurationError:
                frame_format = "unknown"
            raise CameraAcquisitionError(
                f"Daheng frame format {frame_format!r} cannot be converted to NumPy. "
                "Select Mono8, Mono16, Bayer*8, RGB8, or BGR8 with camera.format."
            )
        return np.array(image, copy=True)

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self.stream_off()
        finally:
            try:
                self._handle.close_device()
            except Exception as exc:
                raise CameraConfigurationError(
                    f"Could not close the Daheng camera: {exc}"
                ) from exc
            finally:
                self._handle = None
                self._manager = None

    def __enter__(self) -> "GalaxyCamera":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


class GalaxyDeviceManager:
    """Own a Galaxy ``DeviceManager`` and normalize its device information."""

    def __init__(self, gx: Any | None = None) -> None:
        self._gx = gx if gx is not None else load_gxipy()
        try:
            self._manager = self._gx.DeviceManager()
        except Exception as exc:
            raise CameraDependencyError(
                f"Could not initialize the Daheng Galaxy SDK: {exc}"
            ) from exc
        self._closed = False

    def enumerate(self, timeout_ms: int = 200) -> list[GalaxyDeviceInfo]:
        if self._closed:
            raise CameraDiscoveryError("Daheng DeviceManager is closed.")
        try:
            _, rows = self._manager.update_all_device_list(timeout=int(timeout_ms))
        except Exception as exc:
            raise CameraDiscoveryError(
                f"Failed to enumerate Daheng cameras: {exc}"
            ) from exc
        return [
            GalaxyDeviceInfo.from_row(self._gx, row, index)
            for index, row in enumerate(rows or [], start=1)
        ]

    def open(self, device: GalaxyDeviceInfo) -> GalaxyCamera:
        if self._closed:
            raise CameraDiscoveryError("Daheng DeviceManager is closed.")
        try:
            handle = self._manager.open_device_by_index(device.index)
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not open Daheng camera {device.serial!r}: {exc}"
            ) from exc
        return GalaxyCamera(self, handle)

    def close(self) -> None:
        # gxipy's DeviceManager has no close method; releasing the reference lets
        # its __del__ call gx_close_lib after all cameras have been closed.
        self._manager = None
        self._closed = True

    def __enter__(self) -> "GalaxyDeviceManager":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def discover_devices(timeout_ms: int = 200) -> list[GalaxyDeviceInfo]:
    """Enumerate Galaxy devices and release the temporary manager."""

    manager = GalaxyDeviceManager()
    try:
        return manager.enumerate(timeout_ms=timeout_ms)
    finally:
        manager.close()


__all__ = [
    "GalaxyCamera",
    "GalaxyDeviceInfo",
    "GalaxyDeviceManager",
    "GalaxyFeatureControl",
    "discover_devices",
    "load_gxipy",
]
