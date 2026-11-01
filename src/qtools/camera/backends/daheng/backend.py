"""Daheng Imaging camera backend using the wrapped Galaxy SDK binding."""

from __future__ import annotations

import logging
import math
import re
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from .gxipy import (
    GalaxyCamera,
    GalaxyDeviceInfo,
    GalaxyDeviceManager,
    discover_devices,
)
from qtools.camera.base import CameraBackend, CameraInfo, print_camera_list
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
)

logger = logging.getLogger(__name__)

_PIXEL_FORMAT_DEPTH_RE = re.compile(
    r"(?:MONO|BAYER_[A-Z]{2}|RGB|BGR)(8|10|12|14|16)",
    re.I,
)


class DAHENG(CameraBackend):
    """Daheng Imaging camera controlled through the Galaxy SDK."""

    backend_name: ClassVar[str] = "daheng"

    @classmethod
    def discover(cls, verbose: bool = True) -> list[CameraInfo]:
        devices = discover_devices()
        cameras = [device.as_camera_info() for device in devices]
        if verbose:
            print_camera_list(cameras)
        return cameras

    def __init__(
        self,
        serial: str = "",
        *,
        target: str | int | None = None,
        timeout_ms: int = 200,
        **kwargs: Any,
    ) -> None:
        if serial and target is not None:
            raise ValueError("Specify either serial or target, not both.")
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unsupported Daheng camera options: {unknown}")
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative.")

        self._manager: GalaxyDeviceManager | None = None
        self._camera: GalaxyCamera | None = None
        self._device: GalaxyDeviceInfo | None = None
        self._serial = str(serial or "")
        self._model = "unknown"
        self._shape = (0, 0)

        try:
            self._manager = GalaxyDeviceManager()
            devices = self._manager.enumerate(timeout_ms=timeout_ms)
            if not devices:
                raise CameraDiscoveryError("No Daheng cameras found by Galaxy SDK.")
            selected = self._select_device(devices, serial=serial, target=target)
            self._device = selected
            self._serial = selected.serial
            self._model = selected.model
            self._camera = self._manager.open(selected)
            self._disable_trigger()
            self._cache_geometry()
            self._camera.stream_on()
        except (CameraDiscoveryError, CameraDependencyError):
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise CameraConfigurationError(
                f"Failed to initialize Daheng camera "
                f"{target if target is not None else serial or '<first camera>'}: {exc}"
            ) from exc

    @staticmethod
    def _select_device(
        devices: list[GalaxyDeviceInfo],
        *,
        serial: str = "",
        target: str | int | None = None,
    ) -> GalaxyDeviceInfo:
        selector = serial if serial else target
        if selector is None:
            if len(devices) == 1:
                return devices[0]
            available = ", ".join(device.serial for device in devices)
            raise CameraDiscoveryError(
                "Multiple Daheng cameras are connected; specify target=... or "
                f"serial=.... Available serials: {available}"
            )

        if isinstance(selector, int):
            if not 1 <= selector <= len(devices):
                raise CameraDiscoveryError(
                    f"Daheng camera number {selector} is out of range "
                    f"1..{len(devices)}."
                )
            return devices[selector - 1]

        text = str(selector).strip()
        fields = (
            "serial",
            "user_id",
            "ip",
            "mac",
            "device_id",
            "display_name",
        )
        matches = [
            device
            for device in devices
            if any(
                text.casefold() == str(getattr(device, name)).casefold()
                for name in fields
                if getattr(device, name)
            )
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CameraDiscoveryError(
                f"Daheng camera target {text!r} is ambiguous; use the serial number."
            )

        if text.isdigit() and 1 <= int(text) <= len(devices):
            return devices[int(text) - 1]

        available = ", ".join(
            f"[{device.index}] {device.serial} ({device.model})"
            for device in devices
        )
        raise CameraDiscoveryError(
            f"Daheng camera target {text!r} was not found. Available: {available}"
        )

    def close(self) -> None:
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception as exc:
                logger.warning("Could not close Daheng camera: %s", exc)
        self._camera = None
        if self._manager is not None:
            self._manager.close()
        self._manager = None

    # -- controls ----------------------------------------------------------

    @property
    def name(self) -> str:
        return self._serial

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def model(self) -> str:
        return self._model

    @property
    def shape(self) -> tuple[int, int]:
        return self._shape

    @property
    def format(self) -> str:
        return self.get_format()

    @format.setter
    def format(self, value: str) -> None:
        self.set_format(value)

    def _features(self) -> Any:
        if self._camera is None:
            raise CameraConfigurationError("Daheng camera is not open.")
        return self._camera.features

    def _disable_trigger(self) -> None:
        if not self._features().try_set_enum_symbol("TriggerMode", "Off"):
            logger.debug("Daheng TriggerMode cannot be disabled; preserving current mode.")

    def _cache_geometry(self) -> None:
        try:
            width = self._features().int_value("Width")
            height = self._features().int_value("Height")
        except Exception:
            return
        if width > 0 and height > 0:
            self._shape = (height, width)

    def _restart_stream(self) -> None:
        if self._camera is not None and not self._camera.acquiring:
            self._camera.stream_on()

    def _stop_stream(self) -> bool:
        if self._camera is None or not self._camera.acquiring:
            return False
        self._camera.stream_off()
        return True

    def get_format(self) -> str:
        try:
            return self._features().enum_symbol("PixelFormat")
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng pixel format: {exc}"
            ) from exc

    def set_format(self, pixel_format: str) -> str:
        requested = str(pixel_format).strip()
        if not requested:
            raise ValueError("pixel_format must not be empty.")
        was_acquiring = self._stop_stream()
        try:
            self._features().set_enum_symbol("PixelFormat", requested)
            self._cache_geometry()
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not set Daheng pixel format {requested!r}: {exc}"
            ) from exc
        finally:
            if was_acquiring:
                self._restart_stream()
        return self.get_format()

    @property
    def bitdepth(self) -> int:
        match = _PIXEL_FORMAT_DEPTH_RE.search(self.get_format())
        return int(match.group(1)) if match else 8

    @property
    def bitresolution(self) -> int:
        return 1 << self.bitdepth

    def get_exposure(self) -> float:
        try:
            return self._features().float_value("ExposureTime") * 1e-6
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not read Daheng exposure: {exc}"
            ) from exc

    def set_exposure(self, exposure_s: float) -> float:
        exposure_s = float(exposure_s)
        if not math.isfinite(exposure_s) or exposure_s <= 0:
            raise ValueError("exposure_s must be a finite positive number.")
        try:
            features = self._features()
            bounds = features.float_range("ExposureTime")
            value_us = float(
                np.clip(exposure_s * 1e6, bounds["min"], bounds["max"])
            )
            features.set_float("ExposureTime", value_us)
            return self.get_exposure()
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not set Daheng exposure: {exc}"
            ) from exc

    @property
    def exposure_s(self) -> float:
        return self.get_exposure()

    @exposure_s.setter
    def exposure_s(self, value: float) -> None:
        self.set_exposure(value)

    def get_gain(self) -> float:
        try:
            return self._features().float_value("Gain")
        except Exception as exc:
            raise CameraConfigurationError(f"Could not read Daheng gain: {exc}") from exc

    def set_gain(self, gain_db: float) -> float:
        gain_db = float(gain_db)
        if not math.isfinite(gain_db):
            raise ValueError("gain_db must be finite.")
        try:
            features = self._features()
            bounds = features.float_range("Gain")
            features.set_float("Gain", float(np.clip(gain_db, bounds["min"], bounds["max"])))
            return self.get_gain()
        except Exception as exc:
            raise CameraConfigurationError(f"Could not set Daheng gain: {exc}") from exc

    @property
    def gain(self) -> float:
        return self.get_gain()

    @gain.setter
    def gain(self, value: float) -> None:
        self.set_gain(value)

    def _get_auto_mode(self, name: str) -> bool:
        try:
            return self._features().enum_symbol(name).casefold() != "off"
        except Exception:
            return False

    def _set_auto_mode(self, name: str, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError(f"{name} must be a bool.")
        try:
            self._features().set_enum_symbol(
                name, "Continuous" if enabled else "Off"
            )
        except Exception as exc:
            raise CameraConfigurationError(
                f"Could not set Daheng {name}: {exc}"
            ) from exc

    @property
    def auto_exposure(self) -> bool:
        return self._get_auto_mode("ExposureAuto")

    @auto_exposure.setter
    def auto_exposure(self, enabled: bool) -> None:
        self._set_auto_mode("ExposureAuto", enabled)

    @property
    def auto_gain(self) -> bool:
        return self._get_auto_mode("GainAuto")

    @auto_gain.setter
    def auto_gain(self, enabled: bool) -> None:
        self._set_auto_mode("GainAuto", enabled)

    # -- acquisition -------------------------------------------------------

    def get_image(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        timeout_s = float(timeout_s)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a finite positive number.")
        if self._camera is None or not self._camera.acquiring:
            raise CameraAcquisitionError("Daheng camera is not acquiring.")
        try:
            values = self._camera.capture(max(1, int(timeout_s * 1e3)))
        except CameraAcquisitionError:
            raise
        except Exception as exc:
            raise CameraAcquisitionError(
                f"Daheng image acquisition failed: {exc}"
            ) from exc
        if values.ndim >= 2:
            self._shape = (int(values.shape[0]), int(values.shape[1]))
        return values


__all__ = ["DAHENG"]
