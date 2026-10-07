"""FLIR industrial-camera backend using the Spinnaker ``PySpin`` API.

The implementation is adapted from the FLIR backend in SLMSuite.  The PySpin
module is deliberately imported only when a real FLIR operation is requested;
therefore importing :mod:`qtools.camera` does not require the vendor SDK.
"""

from __future__ import annotations

import importlib
import logging
import time
import warnings
from collections.abc import Iterable
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from qtools.camera.base import CameraBackend, CameraInfo
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
    CameraError,
)

logger = logging.getLogger(__name__)


class FLIR(CameraBackend):
    """Control a FLIR camera through Teledyne's Spinnaker/PySpin SDK."""

    backend_name: ClassVar[str] = "flir"
    sdk: ClassVar[Any | None] = None
    _pyspin: ClassVar[Any | None] = None

    def __init__(
        self,
        serial: str = "",
        bitdepth: int | None = None,
        pitch_um: float | tuple[float, float] | None = None,
        **kwargs: Any,
    ) -> None:
        self._pyspin = self._load_pyspin()
        self.camera_list: Any | None = None
        self.cam: Any | None = None
        self._initialized = False
        self._acquiring = False
        self._closed = False
        self._trigger_is_software = False
        self._bitdepth = bitdepth
        self._pitch_um = self._parse_pitch(pitch_um)
        self._name = str(kwargs.pop("name", serial or "FLIR"))
        self.exposure_bounds_s: tuple[float, float] | None = kwargs.pop(
            "exposure_bounds_s", None
        )

        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unsupported FLIR camera options: {unknown}")

        try:
            self.sdk = self._get_sdk()
            self.camera_list = self.sdk.GetCameras()
            cameras = self._enumerate_camera_handles(self.camera_list)
            if not cameras:
                raise CameraDiscoveryError("No FLIR cameras found by Spinnaker.")

            selected, selected_info = self._select_camera(cameras, serial)
            self.cam = selected
            self._name = selected_info.serial
            self._initialize_camera()
        except CameraDiscoveryError:
            self._cleanup_partial()
            raise
        except CameraDependencyError:
            self._cleanup_partial()
            raise
        except Exception as exc:
            self._cleanup_partial()
            raise CameraConfigurationError(
                f"Failed to initialize FLIR camera {serial or '<first camera>'}: {exc}"
            ) from exc

    # -- SDK and discovery -------------------------------------------------

    @classmethod
    def _load_pyspin(cls) -> Any:
        if cls._pyspin is not None:
            return cls._pyspin
        try:
            cls._pyspin = importlib.import_module("PySpin")
        except (ImportError, OSError) as exc:
            raise CameraDependencyError(
                "PySpin is not installed. Install the matching Teledyne FLIR "
                "Spinnaker SDK and spinnaker-python wheel for this Python version. "
                "See https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"
            ) from exc
        return cls._pyspin

    @classmethod
    def _get_sdk(cls) -> Any:
        pyspin = cls._load_pyspin()
        if cls.sdk is None:
            try:
                cls.sdk = pyspin.System.GetInstance()
            except Exception as exc:
                raise CameraDependencyError(f"Could not initialize Spinnaker SDK: {exc}") from exc
        return cls.sdk

    @classmethod
    def discover(cls, verbose: bool = True) -> list[CameraInfo]:
        sdk = cls._get_sdk()
        camera_list: Any | None = None
        try:
            camera_list = sdk.GetCameras()
            entries = cls._enumerate_camera_handles(camera_list)
            if verbose:
                for camera in entries:
                    print(f"{camera.serial} ('{camera.model}')")
            return [entry.info for entry in entries]
        except CameraError:
            raise
        except Exception as exc:
            raise CameraDiscoveryError(f"Failed to enumerate FLIR cameras: {exc}") from exc
        finally:
            if camera_list is not None:
                cls._clear_camera_list(camera_list)

    @classmethod
    def _enumerate_camera_handles(cls, camera_list: Any) -> list["_CameraEntry"]:
        count = int(camera_list.GetSize())
        entries: list[_CameraEntry] = []
        for index in range(count):
            camera = camera_list.GetByIndex(index)
            entries.append(_CameraEntry(cls._camera_info(camera, index), camera))
        return entries

    @classmethod
    def _camera_info(cls, camera: Any, index: int) -> CameraInfo:
        pyspin = cls._load_pyspin()
        node_map = camera.GetTLDeviceNodeMap()
        serial = cls._read_string_node(node_map, "DeviceSerialNumber", pyspin) or f"cam_{index}"
        model = cls._read_string_node(node_map, "DeviceModelName", pyspin) or "unknown"
        vendor = cls._read_string_node(node_map, "DeviceVendorName", pyspin) or "FLIR"
        return CameraInfo(serial=serial, model=model, vendor=vendor, index=index)

    @classmethod
    def _read_string_node(cls, node_map: Any, name: str, pyspin: Any) -> str | None:
        try:
            node = pyspin.CStringPtr(node_map.GetNode(name))
            if pyspin.IsReadable(node):
                return str(node.GetValue())
        except Exception:
            return None
        return None

    def _select_camera(
        self,
        entries: list["_CameraEntry"],
        serial: str,
    ) -> tuple[Any, CameraInfo]:
        if not serial:
            if len(entries) > 1:
                logger.debug("No serial given; choosing first of %s", [e.info.serial for e in entries])
            return entries[0].handle, entries[0].info
        for entry in entries:
            if entry.info.serial == serial:
                return entry.handle, entry.info
        available = ", ".join(entry.info.serial for entry in entries)
        raise CameraDiscoveryError(f"Serial {serial!r} not found by PySpin. Available: {available}")

    # -- initialization and cleanup ---------------------------------------

    def _initialize_camera(self) -> None:
        assert self.cam is not None
        try:
            self.cam.Init()
            self._initialized = True
            try:
                if self.cam.IsStreaming():
                    self.cam.EndAcquisition()
            except Exception:
                pass

            self._configure_manual_image_settings()
            self._bitdepth = self._configure_adc_depth(self._bitdepth)
            self._configure_trigger()
            self._configure_frame_rate()

            self.cam.BeginAcquisition()
            self._acquiring = True
            self._cache_camera_metadata()
        except Exception as exc:
            if isinstance(exc, (CameraConfigurationError, CameraDiscoveryError)):
                raise
            raise CameraConfigurationError(f"Failed to configure FLIR camera: {exc}") from exc

    def _configure_manual_image_settings(self) -> None:
        assert self.cam is not None
        pyspin = self._pyspin
        self._set_if_writable("GainAuto", getattr(pyspin, "GainAuto_Off", None))
        self._set_if_writable("Gain", 0.0)
        self._set_if_writable("ExposureAuto", getattr(pyspin, "ExposureAuto_Off", None))
        self._set_if_writable("ExposureMode", getattr(pyspin, "ExposureMode_Timed", None))

        self._set_if_writable("BlackLevelSelector", getattr(pyspin, "BlackLevelSelector_All", None))
        self._set_if_writable("BlackLevel", 0.0)

        if not self._set_if_writable("GammaEnable", False):
            self._set_if_writable("Gamma", 1.0)

        exposure_time = self._quick_node("ExposureTime")
        if self._is_writable(exposure_time):
            exposure_time.SetValue(exposure_time.GetMin())

    def _configure_trigger(self) -> None:
        pyspin = self._pyspin
        self._set_if_writable("TriggerMode", getattr(pyspin, "TriggerMode_On", None))
        self._set_if_writable("TriggerSource", getattr(pyspin, "TriggerSource_Software", None))
        self._set_if_writable("TriggerSelector", getattr(pyspin, "TriggerSelector_FrameStart", None))
        self._trigger_is_software = self._read_trigger_is_software()

    def _configure_adc_depth(self, bitdepth: int | None) -> int:
        if bitdepth is not None and bitdepth not in (8, 10, 12):
            raise ValueError("Unsupported bitdepth. Choose from 8, 10, or 12.")
        pyspin = self._pyspin
        pixel_format = self._quick_node("PixelFormat")
        if not self._is_writable(pixel_format):
            return self._read_adc_depth()

        candidates = [
            (
                getattr(pyspin, "PixelFormat_Mono16", None),
                getattr(pyspin, "AdcBitDepth_Bit12", None),
                12,
            ),
            (
                getattr(pyspin, "PixelFormat_Mono16", None),
                getattr(pyspin, "AdcBitDepth_Bit10", None),
                10,
            ),
            (getattr(pyspin, "PixelFormat_Mono8", None), getattr(pyspin, "AdcBitDepth_Bit8", None), 8),
        ]
        if bitdepth is not None:
            candidates = [candidate for candidate in candidates if candidate[2] == bitdepth]

        for pixel_value, adc_value, bits in candidates:
            if pixel_value is None:
                continue
            try:
                pixel_format.SetValue(pixel_value)
                adc_node = self._quick_node("AdcBitDepth")
                if adc_value is not None and self._is_writable(adc_node):
                    adc_node.SetValue(adc_value)
                return bits
            except Exception:
                continue
        return self._read_adc_depth()

    def _read_adc_depth(self) -> int:
        try:
            value = str(self._quick_node("AdcBitDepth").ToString()).replace("Bit", "")
            parsed = int(value)
            if parsed in (8, 10, 12):
                return parsed
        except Exception:
            pass
        return 8

    def _read_trigger_is_software(self) -> bool:
        try:
            pyspin = self._pyspin
            return bool(
                self._quick_node("TriggerMode").GetValue() == pyspin.TriggerMode_On
                and self._quick_node("TriggerSource").GetValue() == pyspin.TriggerSource_Software
            )
        except Exception:
            return False

    def _configure_frame_rate(self) -> None:
        enabled = self._quick_node("AcquisitionFrameRateEnable")
        if self._is_writable(enabled):
            enabled.SetValue(not self._trigger_is_software)
        if not self._trigger_is_software:
            rate = self._quick_node("AcquisitionFrameRate")
            if self._is_writable(rate):
                rate.SetValue(rate.GetMax())

    def _cache_camera_metadata(self) -> None:
        self._shape = (
            self._read_int_node("Height", fallback=0),
            self._read_int_node("Width", fallback=0),
        )
        if not all(self._shape):
            self._shape = (
                self._read_int_node("HeightMax", fallback=0),
                self._read_int_node("WidthMax", fallback=0),
            )
        try:
            self.exposure_bounds_s = (
                float(self._quick_node("ExposureTime").GetMin()) / 1e6,
                float(self._quick_node("ExposureTime").GetMax()) / 1e6,
            )
        except Exception:
            pass

    def _cleanup_partial(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        if self.cam is not None:
            if self._acquiring:
                try:
                    self.cam.EndAcquisition()
                except Exception:
                    pass
            if self._initialized:
                try:
                    self.cam.DeInit()
                except Exception:
                    pass
        self._acquiring = False
        self._initialized = False
        if self.camera_list is not None:
            self._clear_camera_list(self.camera_list)
        self.camera_list = None
        self.cam = None
        self._closed = True

    @classmethod
    def close_sdk(cls) -> None:
        if cls.sdk is not None:
            try:
                cls.sdk.ReleaseInstance()
            finally:
                cls.sdk = None

    @classmethod
    def _clear_camera_list(cls, camera_list: Any) -> None:
        try:
            camera_list.Clear()
        except Exception:
            pass

    # -- generic controls --------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        if self.cam is None:
            return "unknown"
        try:
            return self._read_string_node(
                self.cam.GetTLDeviceNodeMap(), "DeviceModelName", self._pyspin
            ) or "unknown"
        except Exception:
            return "unknown"

    @property
    def shape(self) -> tuple[int, int]:
        return getattr(self, "_shape", (0, 0))

    @property
    def pitch_um(self) -> tuple[float, float] | None:
        return self._pitch_um

    @property
    def bitdepth(self) -> int:
        return int(self._bitdepth or 8)

    @property
    def bitresolution(self) -> int:
        return 1 << self.bitdepth

    @property
    def exposure_s(self) -> float:
        return self.get_exposure()

    @exposure_s.setter
    def exposure_s(self, value: float) -> None:
        self.set_exposure(value)

    def get_exposure(self) -> float:
        try:
            return float(self._quick_node("ExposureTime").GetValue()) / 1e6
        except Exception as exc:
            raise CameraConfigurationError(f"Could not read FLIR exposure: {exc}") from exc

    def set_exposure(self, exposure_s: float) -> float:
        exposure_s = float(exposure_s)
        if exposure_s <= 0:
            raise ValueError("exposure_s must be positive.")
        if self.exposure_bounds_s is not None:
            exposure_s = float(np.clip(exposure_s, *self.exposure_bounds_s))
        try:
            node = self._quick_node("ExposureTime")
            node.SetValue(exposure_s * 1e6)
            return self.get_exposure()
        except Exception as exc:
            raise CameraConfigurationError(f"Could not set FLIR exposure: {exc}") from exc

    def get_binning(self) -> tuple[int, int]:
        try:
            node_map = self.cam.GetNodeMap()
            horizontal = self._pyspin.CIntegerPtr(node_map.GetNode("BinningHorizontal"))
            vertical = self._pyspin.CIntegerPtr(node_map.GetNode("BinningVertical"))
            return int(horizontal.GetValue()), int(vertical.GetValue())
        except Exception:
            return 1, 1

    def set_binning(self, binning: int | tuple[int, int]) -> None:
        if isinstance(binning, int):
            binning = (binning, binning)
        if len(binning) != 2 or any(int(value) < 1 for value in binning):
            raise ValueError("binning must be a positive integer or a pair of positive integers.")
        was_acquiring = self._stop_acquisition_for_reconfigure()
        try:
            node_map = self.cam.GetNodeMap()
            horizontal = self._pyspin.CIntegerPtr(node_map.GetNode("BinningHorizontal"))
            vertical = self._pyspin.CIntegerPtr(node_map.GetNode("BinningVertical"))
            if not self._is_writable(horizontal) or not self._is_writable(vertical):
                raise NotImplementedError(f"Camera {self.name} does not support binning.")
            horizontal.SetValue(int(binning[0]))
            vertical.SetValue(int(binning[1]))
        except NotImplementedError:
            raise
        except Exception as exc:
            raise CameraConfigurationError(f"Could not set FLIR binning: {exc}") from exc
        finally:
            self._restart_acquisition(was_acquiring)

    def get_woi(self) -> tuple[int, int, int, int]:
        return (
            self._read_int_node("OffsetX"),
            self._read_int_node("Width"),
            self._read_int_node("OffsetY"),
            self._read_int_node("Height"),
        )

    def set_woi(self, woi: Iterable[int]) -> None:
        values = tuple(int(value) for value in woi)
        if len(values) != 4:
            raise ValueError("woi must be (offset_x, width, offset_y, height).")
        x, width, y, height = values
        if min(x, width, y, height) < 0:
            raise ValueError("woi values must be non-negative.")
        was_acquiring = self._stop_acquisition_for_reconfigure()
        try:
            for node_name, value in (
                ("OffsetX", 0),
                ("OffsetY", 0),
                ("Width", width),
                ("Height", height),
                ("OffsetX", x),
                ("OffsetY", y),
            ):
                node = self._quick_node(node_name)
                if self._is_writable(node):
                    node.SetValue(self._snap_to_increment(node, value))
            self._cache_camera_metadata()
            self._configure_frame_rate()
        except Exception as exc:
            raise CameraConfigurationError(f"Could not set FLIR WOI: {exc}") from exc
        finally:
            self._restart_acquisition(was_acquiring)

    def get_properties(self, verbose: bool = True) -> dict[str, str] | None:
        """Return or print readable GenICam properties."""

        properties: dict[str, str] = {}
        try:
            root = self._pyspin.CCategoryPtr(self.cam.GetNodeMap().GetNode("Root"))
            self._walk_category(root, properties, verbose)
        except Exception as exc:
            if verbose:
                warnings.warn(f"Unable to access FLIR properties: {exc}", RuntimeWarning)
        return None if verbose else properties

    def _walk_category(self, category: Any, properties: dict[str, str], verbose: bool) -> None:
        try:
            features = category.GetFeatures()
        except Exception:
            return
        for feature in features:
            try:
                if not self._pyspin.IsReadable(feature):
                    continue
                if feature.GetPrincipalInterfaceType() == self._pyspin.intfICategory:
                    self._walk_category(self._pyspin.CCategoryPtr(feature), properties, verbose)
                    continue
                node = self._pyspin.CValuePtr(feature)
                name = str(node.GetName())
                value = str(node.ToString())
                properties[name] = value
                if verbose:
                    print(f"{name}\t{value}")
            except Exception:
                continue

    # -- acquisition ------------------------------------------------------

    def get_image(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        if self.cam is None or not self._acquiring:
            raise CameraAcquisitionError("FLIR camera is not acquiring.")
        frame: Any | None = None
        try:
            if self._trigger_is_software:
                self._quick_node("TriggerSoftware").Execute()
            frame = self.cam.GetNextImage(int(float(timeout_s) * 1e3))
            if frame.IsIncomplete():
                status = frame.GetImageStatus()
                raise CameraAcquisitionError(f"FLIR image is incomplete with status {status}.")
            image = np.array(frame.GetNDArray(), copy=True)
            if image.dtype == np.uint16 and self.bitdepth < 16:
                image = np.right_shift(image, 16 - self.bitdepth)
            return image
        except CameraAcquisitionError:
            raise
        except Exception as exc:
            raise CameraAcquisitionError(f"FLIR image acquisition failed: {exc}") from exc
        finally:
            if frame is not None:
                try:
                    frame.Release()
                except Exception as exc:
                    logger.warning("Could not release FLIR image buffer: %s", exc)

    def autoexpose(
        self,
        set_fraction: float = 0.5,
        tol: float = 0.05,
        exposure_bounds_s: tuple[float, float] | None = None,
        window: tuple[slice, slice] | None = None,
        metric: Any | None = None,
        timeout_s: float = 10.0,
        verbose: bool = True,
        *,
        fraction: float | None = None,
    ) -> float:
        """Adjust exposure until the selected image metric reaches a target fraction."""

        if fraction is not None:
            set_fraction = fraction
        set_fraction = float(set_fraction)
        tol = float(tol)
        if not 0 < set_fraction <= 1 or tol <= 0:
            raise ValueError("set_fraction must be in (0, 1] and tol must be positive.")
        if metric is None:
            metric = np.max
        bounds = exposure_bounds_s or self.exposure_bounds_s or (1e-9, np.inf)
        target = set_fraction * self.bitresolution
        exposure = self.get_exposure()
        status = 0.0
        start = time.perf_counter()

        for _ in range(20):
            image = self.get_image()
            selected = image if window is None else image[window]
            status = float(metric(selected))
            if abs(status - target) / self.bitresolution <= tol:
                break
            if time.perf_counter() - start > timeout_s:
                break
            exposure = float(np.clip(exposure * target / max(status, 1.0), *bounds))
            next_exposure = self.set_exposure(exposure)
            if np.isclose(next_exposure, exposure):
                exposure = next_exposure

        if verbose:
            logger.info("FLIR autoexposure: %.3g s - %.1f/%d", exposure, status, self.bitresolution)
        return self.get_exposure()

    def autoexposure(self, *args: Any, **kwargs: Any) -> float:
        return self.autoexpose(*args, **kwargs)

    def exposure_auto(self, fraction: float = 0.8) -> float:
        return self.autoexpose(fraction=fraction)

    # -- helpers -----------------------------------------------------------

    def _quick_node(self, name: str) -> Any:
        if self.cam is None:
            raise CameraConfigurationError("FLIR camera is not initialized.")
        node = getattr(self.cam, name, None)
        if node is not None:
            return node
        return self.cam.GetNodeMap().GetNode(name)

    def _set_if_writable(self, name: str, value: Any) -> bool:
        if value is None:
            return False
        try:
            node = self._quick_node(name)
            if self._is_writable(node):
                node.SetValue(value)
                return True
        except Exception:
            return False
        return False

    def _is_writable(self, node: Any) -> bool:
        if node is None:
            return False
        try:
            return node.GetAccessMode() == self._pyspin.RW
        except Exception:
            try:
                return bool(self._pyspin.IsWritable(node))
            except Exception:
                return hasattr(node, "SetValue")

    def _read_int_node(self, name: str, fallback: int = 0) -> int:
        try:
            return int(self._quick_node(name).GetValue())
        except Exception:
            return fallback

    @staticmethod
    def _parse_pitch(pitch_um: float | tuple[float, float] | None) -> tuple[float, float] | None:
        if pitch_um is None:
            return None
        if isinstance(pitch_um, (float, int)):
            return float(pitch_um), float(pitch_um)
        if len(pitch_um) != 2:
            raise ValueError("pitch_um must be a scalar or a pair of values.")
        return float(pitch_um[0]), float(pitch_um[1])

    @staticmethod
    def _snap_to_increment(node: Any, value: int) -> int:
        try:
            increment = int(node.GetInc())
            return (value // increment) * increment if increment else value
        except Exception:
            return value

    def _stop_acquisition_for_reconfigure(self) -> bool:
        was_acquiring = self._acquiring
        if was_acquiring:
            try:
                self.cam.EndAcquisition()
            except Exception as exc:
                raise CameraConfigurationError(f"Could not stop FLIR acquisition: {exc}") from exc
            self._acquiring = False
        return was_acquiring

    def _restart_acquisition(self, was_acquiring: bool) -> None:
        if was_acquiring:
            try:
                self.cam.BeginAcquisition()
                self._acquiring = True
            except Exception as exc:
                raise CameraConfigurationError(
                    f"Could not restart FLIR acquisition after reconfiguration: {exc}"
                ) from exc


class _CameraEntry:
    def __init__(self, info: CameraInfo, handle: Any) -> None:
        self.info = info
        self.handle = handle


__all__ = ["FLIR"]
