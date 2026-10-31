"""FLIR industrial-camera backend using the Spinnaker ``PySpin`` API.

The implementation is adapted from the FLIR backend in SLMSuite.  The PySpin
module is deliberately imported only when a real FLIR operation is requested;
therefore importing :mod:`qtools.camera` does not require the vendor SDK.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import importlib
import ipaddress
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from qtools.camera._spinnaker_c import discover_spinnaker_cameras
from qtools.camera.base import CameraBackend, CameraInfo, print_camera_list
from qtools.camera.exceptions import (
    CameraAcquisitionError,
    CameraConfigurationError,
    CameraDependencyError,
    CameraDiscoveryError,
    CameraError,
)

logger = logging.getLogger(__name__)

_CP_TAG_RE = re.compile(r"(?:^|[-.])(?P<tag>cp\d{3,4})(?:[-.]|$)")


def _wheel_cp_tag(wheel: Path) -> str | None:
    match = _CP_TAG_RE.search(wheel.name)
    return None if match is None else match.group("tag")


def _wheel_version(wheel: Path) -> str | None:
    parts = wheel.stem.split("-")
    return parts[1] if len(parts) > 1 else None


def _cp_tag_version(tag: str) -> tuple[int, int]:
    digits = tag.removeprefix("cp")
    return int(digits[0]), int(digits[1:])


def _probe_python(executable: str | Path) -> tuple[int, int, int] | None:
    code = (
        "import struct, sys; "
        "print(sys.version_info[0]); print(sys.version_info[1]); "
        "print(struct.calcsize('P') * 8)"
    )
    try:
        result = subprocess.run(
            [str(executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        major, minor, bits = (int(value) for value in result.stdout.splitlines()[:3])
    except (TypeError, ValueError):
        return None
    return major, minor, bits


def _find_python(
    required_version: tuple[int, int],
    base_python: str | Path | None,
) -> Path | None:
    if base_python is not None:
        candidate = Path(base_python).expanduser()
        executable = str(candidate) if candidate.exists() else shutil.which(str(base_python))
        if executable is None:
            raise CameraDependencyError(f"Python executable not found: {base_python}")
        identity = _probe_python(executable)
        if identity is None:
            raise CameraDependencyError(f"Could not run Python executable: {executable}")
        if identity[:2] != required_version:
            raise CameraDependencyError(
                f"{executable} is Python {identity[0]}.{identity[1]}, but the wheel "
                f"requires Python {required_version[0]}.{required_version[1]}."
            )
        return Path(executable).resolve()

    major, minor = required_version
    version_text = f"{major}.{minor}"
    launcher = shutil.which("py")
    if launcher:
        try:
            result = subprocess.run(
                [launcher, f"-{version_text}", "-c", "import sys; print(sys.executable)"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            executable = result.stdout.strip().splitlines()[0]
            identity = _probe_python(executable)
            if identity is not None and identity[:2] == required_version:
                return Path(executable).resolve()

    known: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    if local_app_data:
        known.append(
            Path(local_app_data) / "Programs" / "Python" / f"Python{major}{minor}" / "python.exe"
        )
    if program_files:
        known.append(Path(program_files) / f"Python{major}{minor}" / "python.exe")

    candidates = [
        sys.executable,
        shutil.which(f"python{version_text}"),
        shutil.which(f"python{major}"),
        shutil.which("python3"),
        shutil.which("python"),
        *(str(path) for path in known),
    ]
    checked: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in checked:
            continue
        checked.add(candidate)
        identity = _probe_python(candidate)
        if identity is not None and identity[:2] == required_version:
            return Path(candidate).resolve()
    return None


def _install_python_with_winget(required_version: tuple[int, int]) -> bool:
    if os.name != "nt":
        return False
    winget = shutil.which("winget")
    if winget is None:
        logger.warning("winget is unavailable; cannot auto-install Python.")
        return False
    major, minor = required_version
    package_id = f"Python.Python.{major}.{minor}"
    logger.warning(
        "No Python %s.%s was found. Installing %s with winget; this may take a few minutes.",
        major,
        minor,
        package_id,
    )
    try:
        result = subprocess.run(
            [
                winget,
                "install",
                "--id",
                package_id,
                "--exact",
                "--scope",
                "user",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            check=False,
        )
    except OSError as exc:
        logger.warning("Could not start winget: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning("winget returned exit code %s while installing Python.", result.returncode)
    return True


def _resolve_python(
    required_version: tuple[int, int],
    base_python: str | Path | None,
    *,
    auto_install: bool = True,
) -> Path:
    found = _find_python(required_version, base_python)
    if found is not None:
        return found

    attempted_auto_install = False
    if auto_install and base_python is None:
        attempted_auto_install = True
        _install_python_with_winget(required_version)
        found = _find_python(required_version, None)
        if found is not None:
            return found

    major, minor = required_version
    if attempted_auto_install:
        recovery = (
            "Automatic installation with winget was attempted but failed. Install the "
            "matching 64-bit Python interpreter manually or pass its path with "
            "base_python=/path/to/python.exe."
        )
    else:
        recovery = (
            "Install the matching 64-bit Python interpreter or pass its path with "
            "base_python=/path/to/python.exe."
        )
    raise CameraDependencyError(
        f"Python {major}.{minor} is required by the bundled PySpin wheel, but it was "
        f"not found. {recovery}"
    )


def _run_checked(command: list[str], description: str) -> None:
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise CameraDependencyError(f"{description} could not start: {exc}") from exc
    if result.returncode != 0:
        joined = " ".join(command)
        raise CameraDependencyError(
            f"{description} failed with exit code {result.returncode}: {joined}"
        )


def _pyspin_ready(
    python_executable: Path,
    expected_version: str | None = None,
) -> bool:
    code = (
        "import importlib.metadata as metadata, numpy, PySpin; "
        "print(metadata.version('spinnaker-python'))"
    )
    try:
        result = subprocess.run(
            [str(python_executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    if expected_version is None:
        return True
    lines = result.stdout.strip().splitlines()
    return bool(lines) and lines[-1].strip() == expected_version


def _ensure_pip(python_executable: Path) -> None:
    result = subprocess.run(
        [str(python_executable), "-m", "pip", "--version"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        _run_checked(
            [str(python_executable), "-m", "ensurepip", "--upgrade"],
            "Bootstrapping pip",
        )


class FLIR(CameraBackend):
    """Control a FLIR camera through Teledyne's Spinnaker/PySpin SDK."""

    backend_name: ClassVar[str] = "flir"
    default_python_version: ClassVar[tuple[int, int]] = (3, 12)
    sdk: ClassVar[Any | None] = None
    _pyspin: ClassVar[Any | None] = None
    refs_dir: ClassVar[Path] = Path(__file__).resolve().with_name("refs")

    @classmethod
    def pyspin_available(cls) -> bool:
        """Return whether PySpin can be imported by the current interpreter."""

        try:
            cls._load_pyspin()
        except Exception:
            return False
        return True

    @classmethod
    def find_pyspin_wheel(
        cls,
        *,
        python_version: tuple[int, int] | None = None,
        refs_dir: str | Path | None = None,
    ) -> Path:
        """Return a bundled PySpin wheel matching the requested Python version.

        By default, the managed camera runtime targets the Python version used
        by the current bundled PySpin wheel (currently CPython 3.12).
        """

        directory = Path(refs_dir).expanduser() if refs_dir else cls.refs_dir
        python_version = cls.default_python_version if python_version is None else python_version
        candidates = sorted(directory.glob("spinnaker_python-*.whl"))
        required_tag = f"cp{python_version[0]}{python_version[1]}"
        candidates = [wheel for wheel in candidates if _wheel_cp_tag(wheel) == required_tag]
        if not candidates:
            detail = f" for Python {python_version[0]}.{python_version[1]}"
            raise CameraDependencyError(
                f"No spinnaker_python wheel found in {directory}{detail}."
            )
        return candidates[0]

    @staticmethod
    def bridge_python(venv_dir: str | Path = ".venv-camera") -> Path:
        """Return the Python executable inside a camera bridge environment."""

        root = Path(venv_dir).expanduser()
        if os.name == "nt":
            return root / "Scripts" / "python.exe"
        return root / "bin" / "python"

    @classmethod
    def create_bridge_venv(
        cls,
        venv_dir: str | Path = ".venv-camera",
        *,
        base_python: str | Path | None = None,
        wheel: str | Path | None = None,
        numpy_requirement: str | None = "numpy<2",
        auto_install_python: bool = True,
    ) -> Path:
        """Create or repair a camera venv from the bundled PySpin wheel.

        The interpreter version is inferred from the wheel's ``cp3xx`` tag.
        NumPy is installed separately and the vendor wheel is installed with
        ``--no-deps`` so PySpin cannot replace the selected NumPy version. An
        existing compatible venv is reused; an incompatible one is recreated.
        """

        venv_path = Path(venv_dir).expanduser().resolve()
        wheel_path = (
            Path(wheel).expanduser().resolve()
            if wheel is not None
            else cls.find_pyspin_wheel()
        )
        if not wheel_path.is_file():
            raise CameraDependencyError(f"PySpin wheel not found: {wheel_path}")
        python_tag = _wheel_cp_tag(wheel_path)
        if python_tag is None:
            raise CameraDependencyError(
                f"Could not determine the CPython version from wheel: {wheel_path.name}"
            )
        required_version = _cp_tag_version(python_tag)
        wheel_version = _wheel_version(wheel_path)
        if wheel_version is None:
            raise CameraDependencyError(f"Could not determine wheel version: {wheel_path.name}")
        base_executable = _resolve_python(
            required_version,
            base_python,
            auto_install=auto_install_python,
        )
        base_identity = _probe_python(base_executable)
        if base_identity is None:
            raise CameraDependencyError(f"Could not inspect Python: {base_executable}")
        platform_tag = wheel_path.stem.rsplit("-", 1)[-1]
        if "64" in platform_tag and base_identity[2] != 64:
            raise CameraDependencyError(
                f"{base_executable} is {base_identity[2]}-bit, but "
                f"{wheel_path.name} requires a 64-bit interpreter."
            )

        venv_python = cls.bridge_python(venv_path)
        if venv_path.exists():
            if not venv_path.is_dir():
                raise CameraDependencyError(f"Camera venv path is not a directory: {venv_path}")
            venv_identity = _probe_python(venv_python) if venv_python.is_file() else None
            recreate = venv_identity is None or venv_identity[:2] != required_version
        else:
            recreate = True

        if recreate:
            _run_checked(
                [
                    str(base_executable),
                    "-m",
                    "venv",
                    *(("--clear",) if venv_path.exists() else ()),
                    str(venv_path),
                ],
                f"Creating camera venv with Python {required_version[0]}.{required_version[1]}",
            )
        venv_identity = _probe_python(venv_python)
        if venv_identity is None:
            raise CameraDependencyError(f"Could not run camera venv Python: {venv_python}")
        if venv_identity[:2] != required_version:
            raise CameraDependencyError(
                f"Camera venv uses Python {venv_identity[0]}.{venv_identity[1]}, but "
                f"{wheel_path.name} requires Python {required_version[0]}.{required_version[1]}."
            )

        if _pyspin_ready(venv_python, wheel_version):
            return venv_path

        _ensure_pip(venv_python)
        if numpy_requirement:
            _run_checked(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    numpy_requirement,
                ],
                "Installing NumPy in the camera venv",
            )
        _run_checked(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheel_path),
            ],
            "Installing the PySpin wheel in the camera venv",
        )
        if not _pyspin_ready(venv_python, wheel_version):
            raise CameraDependencyError(
                "The camera venv was created, but 'import numpy, PySpin' still fails. "
                "Install the matching Spinnaker SDK runtime and check the Python ABI."
            )
        return venv_path

    @classmethod
    def ensure_bridge_python(
        cls,
        venv_dir: str | Path = ".venv-camera",
        *,
        base_python: str | Path | None = None,
        wheel: str | Path | None = None,
        numpy_requirement: str | None = "numpy<2",
        auto_install_python: bool = True,
    ) -> Path:
        """Ensure the managed FLIR venv exists and return its interpreter."""

        venv_path = cls.create_bridge_venv(
            venv_dir,
            base_python=base_python,
            wheel=wheel,
            numpy_requirement=numpy_requirement,
            auto_install_python=auto_install_python,
        )
        return cls.bridge_python(venv_path)

    @classmethod
    def remote_camera(
        cls,
        venv_dir: str | Path = ".venv-camera",
        *,
        base_python: str | Path | None = None,
        wheel: str | Path | None = None,
        numpy_requirement: str | None = "numpy<2",
        auto_install_python: bool = True,
        **camera_kwargs: Any,
    ) -> Any:
        """Create a :class:`RemoteCamera` backed by a managed FLIR venv."""

        venv_path = cls.create_bridge_venv(
            venv_dir,
            base_python=base_python,
            wheel=wheel,
            numpy_requirement=numpy_requirement,
            auto_install_python=auto_install_python,
        )
        from qtools.camera.bridge import RemoteCamera

        return RemoteCamera(
            cls.bridge_python(venv_path),
            backend=cls.backend_name,
            **camera_kwargs,
        )

    def __init__(
        self,
        serial: str = "",
        bitdepth: int | None = None,
        pitch_um: float | tuple[float, float] | None = None,
        *,
        target: str | int | None = None,
        **kwargs: Any,
    ) -> None:
        if serial and target is not None:
            raise ValueError("Specify either serial or target, not both.")
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
            try:
                runtime_info = {
                    info.serial: info for info in discover_spinnaker_cameras()
                }
            except CameraError:
                runtime_info = {}
            for entry in cameras:
                entry.info = runtime_info.get(entry.info.serial, entry.info)
            cameras.sort(key=lambda entry: entry.info.index)

            selected, selected_info = self._select_camera(cameras, serial, target)
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
                f"Failed to initialize FLIR camera {target if target is not None else serial or '<first camera>'}: {exc}"
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
        try:
            cameras = discover_spinnaker_cameras()
        except CameraError:
            raise
        except Exception as exc:
            raise CameraDiscoveryError(f"Failed to enumerate FLIR cameras: {exc}") from exc
        if verbose:
            print_camera_list(cameras)
        return cameras

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
        return CameraInfo(
            serial=serial,
            model=model,
            vendor=vendor,
            index=index + 1,
            device_id=cls._read_string_node(node_map, "DeviceID", pyspin) or "",
        )

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
        target: str | int | None,
    ) -> tuple[Any, CameraInfo]:
        selector = target if target is not None else serial
        if selector is None or str(selector).strip() == "":
            if len(entries) != 1:
                available = ", ".join(
                    f"[{entry.info.index}] {entry.info.serial}" for entry in entries
                )
                raise CameraDiscoveryError(
                    "Multiple FLIR cameras found; specify target by camera number, "
                    f"serial, USB port, or Ethernet address. Available: {available}"
                )
            return entries[0].handle, entries[0].info

        if isinstance(selector, int):
            index = selector
            if 1 <= index <= len(entries):
                entry = entries[index - 1]
                return entry.handle, entry.info
            raise CameraDiscoveryError(
                f"Camera number {index} is out of range; available numbers are "
                f"1-{len(entries)}."
            )

        text = str(selector).strip()
        fields = (
            "serial",
            "device_id",
            "port",
            "interface_id",
            "interface_name",
        )
        matches = [
            entry
            for entry in entries
            if any(
                text.casefold() == str(getattr(entry.info, field, "")).casefold()
                for field in fields
                if getattr(entry.info, field, "")
            )
        ]
        if len(matches) == 1:
            return matches[0].handle, matches[0].info
        if len(matches) > 1:
            numbers = ", ".join(str(entry.info.index) for entry in matches)
            raise CameraDiscoveryError(
                f"Target {text!r} matches multiple cameras ({numbers}); use the "
                "camera number or serial number instead."
            )

        if text.isdigit() and 1 <= int(text) <= len(entries):
            entry = entries[int(text) - 1]
            return entry.handle, entry.info

        available = ", ".join(
            f"[{entry.info.index}] {entry.info.serial} ({entry.info.port})"
            for entry in entries
        )
        raise CameraDiscoveryError(
            f"Camera target {text!r} was not found. Available: {available}"
        )

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
        self._set_enum_if_writable("GainAuto", "Off", getattr(pyspin, "GainAuto_Off", None))
        self._set_if_writable("Gain", 0.0)
        self._set_enum_if_writable(
            "ExposureAuto", "Off", getattr(pyspin, "ExposureAuto_Off", None)
        )
        self._set_enum_if_writable(
            "ExposureMode", "Timed", getattr(pyspin, "ExposureMode_Timed", None)
        )

        self._set_enum_if_writable(
            "BlackLevelSelector", "All", getattr(pyspin, "BlackLevelSelector_All", None)
        )
        self._set_if_writable("BlackLevel", 0.0)

        if not self._set_if_writable("GammaEnable", False):
            self._set_if_writable("Gamma", 1.0)

        exposure_time = self._quick_node("ExposureTime")
        if self._is_writable(exposure_time):
            exposure_time.SetValue(exposure_time.GetMin())

    def _configure_trigger(self) -> None:
        pyspin = self._pyspin
        # Spinnaker requires TriggerMode to be disabled before TriggerSource or
        # TriggerSelector can be changed.  The vendor examples all follow this
        # order; setting TriggerMode=On first works with some fake cameras but
        # is rejected by real GenICam devices.
        trigger_mode = self._quick_node("TriggerMode")
        trigger_off = getattr(pyspin, "TriggerMode_Off", None)
        if trigger_off is not None and not self._set_enum_value(trigger_mode, "Off", trigger_off):
            logger.debug("TriggerMode cannot be disabled; leaving the camera in its current mode.")
            self._trigger_is_software = False
            return

        selector = getattr(pyspin, "TriggerSelector_FrameStart", None)
        source = getattr(pyspin, "TriggerSource_Software", None)
        selector_ok = self._set_enum_if_writable("TriggerSelector", "FrameStart", selector)
        source_ok = self._set_enum_if_writable("TriggerSource", "Software", source)
        enabled = getattr(pyspin, "TriggerMode_On", None)
        mode_ok = (
            selector_ok
            and source_ok
            and enabled is not None
            and self._set_enum_value(trigger_mode, "On", enabled)
        )
        self._trigger_is_software = bool(selector_ok and source_ok and mode_ok)

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
                pixel_format_symbol = {8: "Mono8", 10: "Mono16", 12: "Mono16"}[bits]
                self._set_enum_value(pixel_format, pixel_format_symbol, pixel_value)
            except Exception:
                continue
            try:
                adc_node = self._quick_node("AdcBitDepth")
                if adc_value is not None:
                    self._set_enum_value(adc_node, f"Bit{bits}", adc_value, required=False)
            except Exception:
                logger.debug("AdcBitDepth is unavailable; using the selected pixel format.")
            return bits
        if bitdepth is not None:
            raise CameraConfigurationError(
                f"Camera does not support the requested {bitdepth}-bit acquisition mode."
            )
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
        if not math.isfinite(exposure_s) or exposure_s <= 0:
            raise ValueError("exposure_s must be a finite positive number.")
        try:
            node = self._quick_node("ExposureTime")
            bounds = self.exposure_bounds_s
            if bounds is None:
                bounds = (float(node.GetMin()) / 1e6, float(node.GetMax()) / 1e6)
            exposure_s = float(np.clip(exposure_s, *bounds))
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
            self._cache_camera_metadata()
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
        timeout_s = float(timeout_s)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a finite positive number.")
        frame: Any | None = None
        try:
            if self._trigger_is_software:
                self._quick_node("TriggerSoftware").Execute()
            frame = self.cam.GetNextImage(max(1, int(timeout_s * 1e3)))
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
        raw_node = self.cam.GetNodeMap().GetNode(name)
        pointer_type = {
            "AdcBitDepth": "CEnumerationPtr",
            "AcquisitionFrameRateEnable": "CBooleanPtr",
            "AcquisitionFrameRate": "CFloatPtr",
            "BlackLevelSelector": "CEnumerationPtr",
            "BinningHorizontal": "CIntegerPtr",
            "BinningVertical": "CIntegerPtr",
            "ExposureAuto": "CEnumerationPtr",
            "ExposureMode": "CEnumerationPtr",
            "ExposureTime": "CFloatPtr",
            "GainAuto": "CEnumerationPtr",
            "Gain": "CFloatPtr",
            "GammaEnable": "CBooleanPtr",
            "Gamma": "CFloatPtr",
            "Height": "CIntegerPtr",
            "HeightMax": "CIntegerPtr",
            "OffsetX": "CIntegerPtr",
            "OffsetY": "CIntegerPtr",
            "PixelFormat": "CEnumerationPtr",
            "TriggerMode": "CEnumerationPtr",
            "TriggerSelector": "CEnumerationPtr",
            "TriggerSource": "CEnumerationPtr",
            "TriggerSoftware": "CCommandPtr",
            "Width": "CIntegerPtr",
            "WidthMax": "CIntegerPtr",
        }.get(name)
        wrapper = getattr(self._pyspin, pointer_type, None) if pointer_type else None
        return wrapper(raw_node) if wrapper is not None else raw_node

    def _set_enum_if_writable(self, name: str, symbol: str, value: Any) -> bool:
        if value is None:
            return False
        try:
            return self._set_enum_value(self._quick_node(name), symbol, value)
        except Exception:
            return False

    def _set_enum_value(
        self,
        node: Any,
        symbol: str,
        value: Any,
        *,
        required: bool = True,
    ) -> bool:
        """Set either a QuickSpin enum node or a GenICam enum node."""

        if not self._is_writable(node):
            return False
        try:
            get_entry = getattr(node, "GetEntryByName", None)
            set_int_value = getattr(node, "SetIntValue", None)
            if get_entry is not None and set_int_value is not None:
                entry = get_entry(symbol)
                entry_wrapper = getattr(self._pyspin, "CEnumEntryPtr", None)
                if entry_wrapper is not None:
                    entry = entry_wrapper(entry)
                readable = getattr(self._pyspin, "IsReadable", None)
                if readable is not None and not readable(entry):
                    return False
                set_int_value(entry.GetValue())
            elif hasattr(node, "SetValue"):
                # QuickSpin exposes SetValue(enum_constant).
                node.SetValue(value)
            elif required:
                return False
            else:
                return False
            return True
        except Exception:
            return False

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


def main(argv: list[str] | None = None) -> None:
    """Create or repair the managed FLIR camera environment."""

    parser = argparse.ArgumentParser(
        description="Create a PySpin camera venv using the wheel in refs/."
    )
    parser.add_argument("--venv", default=".venv-camera", help="Camera venv directory.")
    parser.add_argument(
        "--python",
        dest="base_python",
        help="Base Python executable (normally Python 3.12 for the bundled wheel).",
    )
    parser.add_argument(
        "--wheel",
        help="PySpin wheel path; defaults to the matching wheel in refs/.",
    )
    parser.add_argument(
        "--numpy",
        default="numpy<2",
        help="NumPy requirement installed before the vendor wheel (default: numpy<2).",
    )
    parser.add_argument(
        "--no-install-python",
        action="store_false",
        dest="install_python",
        help="Do not try to install a missing Python version with winget.",
    )
    args = parser.parse_args(argv)
    try:
        venv_path = FLIR.create_bridge_venv(
            args.venv,
            base_python=args.base_python,
            wheel=args.wheel,
            numpy_requirement=args.numpy,
            auto_install_python=args.install_python,
        )
    except CameraDependencyError as exc:
        parser.exit(1, f"error: {exc}\n")
    print(f"Camera venv: {venv_path}")
    print(f"Camera Python: {FLIR.bridge_python(venv_path)}")
    print("PySpin import: OK")


__all__ = ["FLIR"]


if __name__ == "__main__":
    main()
