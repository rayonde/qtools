"""Low-level Thorlabs KDC101 wrapper backed by the Kinesis C API.

The KDC101 is a brushed DC-servo controller, not a K10CR1-style stepper
stage. It therefore has its own backend and uses Kinesis' stage-aware unit
conversion rather than the K10CR1 step count.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KDC101_TYPE_ID = 27

_MOT_ROTATIONAL = 0x02
_UNIT_DISTANCE = 0
_UNIT_VELOCITY = 1

_STATUS_MOVING = 0x10 | 0x20 | 0x40 | 0x80 | 0x200
_STATUS_HOMED = 0x400

_LIBRARY_NAME = "Thorlabs.MotionControl.KCube.DCServo.dll"
_LIBRARY_LOCK = threading.Lock()
_LIBRARY: ctypes.WinDLL | None = None
_DLL_DIRECTORY_HANDLES: list[Any] = []


class KDC101Error(RuntimeError):
    """Raised when the Thorlabs KDC101 SDK reports an error."""


def _candidate_kinesis_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("THORLABS_KINESIS_DIR")
    if configured:
        roots.append(Path(configured))

    if sys.platform.startswith("win"):
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                roots.append(Path(base) / "Thorlabs" / "Kinesis")
    else:
        roots.extend(
            [
                Path("/usr/local/lib/Thorlabs/Kinesis"),
                Path("/opt/Thorlabs/Kinesis"),
            ]
        )
    return roots


def _find_library() -> Path:
    for root in _candidate_kinesis_roots():
        candidate = root / _LIBRARY_NAME
        if candidate.is_file():
            return candidate
    raise KDC101Error(
        "Thorlabs Kinesis was not found. Install Kinesis and ensure "
        f"{_LIBRARY_NAME} is present, or set THORLABS_KINESIS_DIR."
    )


def _set_prototypes(lib: ctypes.WinDLL) -> None:
    lib.TLI_BuildDeviceList.argtypes = []
    lib.TLI_BuildDeviceList.restype = ctypes.c_short
    lib.TLI_GetDeviceListSize.argtypes = []
    lib.TLI_GetDeviceListSize.restype = ctypes.c_short
    lib.TLI_GetDeviceListByTypeExt.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    lib.TLI_GetDeviceListByTypeExt.restype = ctypes.c_short

    lib.CC_Open.argtypes = [ctypes.c_char_p]
    lib.CC_Open.restype = ctypes.c_short
    lib.CC_Close.argtypes = [ctypes.c_char_p]
    lib.CC_Close.restype = None
    lib.CC_CheckConnection.argtypes = [ctypes.c_char_p]
    lib.CC_CheckConnection.restype = ctypes.c_bool
    lib.CC_StartPolling.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.CC_StartPolling.restype = ctypes.c_bool
    lib.CC_StopPolling.argtypes = [ctypes.c_char_p]
    lib.CC_StopPolling.restype = None

    lib.CC_EnableChannel.argtypes = [ctypes.c_char_p]
    lib.CC_EnableChannel.restype = ctypes.c_short
    lib.CC_LoadSettings.argtypes = [ctypes.c_char_p]
    lib.CC_LoadSettings.restype = ctypes.c_bool
    lib.CC_LoadNamedSettings.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.CC_LoadNamedSettings.restype = ctypes.c_bool

    lib.CC_GetHardwareInfo.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ushort),
    ]
    lib.CC_GetHardwareInfo.restype = ctypes.c_short

    lib.CC_SetMotorParamsExt.argtypes = [
        ctypes.c_char_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
    ]
    lib.CC_SetMotorParamsExt.restype = ctypes.c_short
    lib.CC_GetMotorParamsExt.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.CC_GetMotorParamsExt.restype = ctypes.c_short
    lib.CC_SetMotorTravelMode.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.CC_SetMotorTravelMode.restype = ctypes.c_short
    lib.CC_GetMotorTravelMode.argtypes = [ctypes.c_char_p]
    lib.CC_GetMotorTravelMode.restype = ctypes.c_int

    lib.CC_RequestSettings.argtypes = [ctypes.c_char_p]
    lib.CC_RequestSettings.restype = ctypes.c_short
    lib.CC_RequestPosition.argtypes = [ctypes.c_char_p]
    lib.CC_RequestPosition.restype = ctypes.c_short
    lib.CC_GetPosition.argtypes = [ctypes.c_char_p]
    lib.CC_GetPosition.restype = ctypes.c_int
    lib.CC_RequestStatusBits.argtypes = [ctypes.c_char_p]
    lib.CC_RequestStatusBits.restype = ctypes.c_short
    lib.CC_GetStatusBits.argtypes = [ctypes.c_char_p]
    lib.CC_GetStatusBits.restype = ctypes.c_uint32

    lib.CC_MoveToPosition.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.CC_MoveToPosition.restype = ctypes.c_short
    lib.CC_MoveRelative.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.CC_MoveRelative.restype = ctypes.c_short
    lib.CC_Home.argtypes = [ctypes.c_char_p]
    lib.CC_Home.restype = ctypes.c_short
    lib.CC_StopImmediate.argtypes = [ctypes.c_char_p]
    lib.CC_StopImmediate.restype = ctypes.c_short
    lib.CC_StopProfiled.argtypes = [ctypes.c_char_p]
    lib.CC_StopProfiled.restype = ctypes.c_short
    lib.CC_Identify.argtypes = [ctypes.c_char_p]
    lib.CC_Identify.restype = None

    lib.CC_RequestVelParams.argtypes = [ctypes.c_char_p]
    lib.CC_RequestVelParams.restype = ctypes.c_short
    lib.CC_GetVelParams.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.CC_GetVelParams.restype = ctypes.c_short
    lib.CC_SetVelParams.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.CC_SetVelParams.restype = ctypes.c_short

    lib.CC_GetRealValueFromDeviceUnit.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
    ]
    lib.CC_GetRealValueFromDeviceUnit.restype = ctypes.c_short
    lib.CC_GetDeviceUnitFromRealValue.argtypes = [
        ctypes.c_char_p,
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
    ]
    lib.CC_GetDeviceUnitFromRealValue.restype = ctypes.c_short

    lib.CC_CanHome.argtypes = [ctypes.c_char_p]
    lib.CC_CanHome.restype = ctypes.c_bool
    lib.CC_CanMoveWithoutHomingFirst.argtypes = [ctypes.c_char_p]
    lib.CC_CanMoveWithoutHomingFirst.restype = ctypes.c_bool


def _load_library() -> ctypes.WinDLL:
    global _LIBRARY
    with _LIBRARY_LOCK:
        if _LIBRARY is not None:
            return _LIBRARY
        library_path = _find_library()
        if not sys.platform.startswith("win"):
            raise KDC101Error("The Thorlabs Kinesis C API backend requires Windows.")
        handle = os.add_dll_directory(str(library_path.parent))
        _DLL_DIRECTORY_HANDLES.append(handle)
        try:
            library = ctypes.WinDLL(str(library_path))
        except OSError as exc:
            raise KDC101Error(f"Could not load {library_path}: {exc}") from exc
        _set_prototypes(library)
        _LIBRARY = library
        return library


def _decode(buffer: ctypes.Array[ctypes.c_char]) -> str:
    return bytes(buffer.value).decode("ascii", errors="replace").strip()


def list_devices() -> list[tuple[str, str]]:
    """Return ``[(serial, label), ...]`` for connected KDC101 controllers."""
    try:
        lib = _load_library()
        if lib.TLI_BuildDeviceList() != 0:
            return []
        buffer = ctypes.create_string_buffer(8192)
        result = lib.TLI_GetDeviceListByTypeExt(
            buffer, len(buffer), KDC101_TYPE_ID
        )
        if result != 0:
            return []
        serials = [item.strip() for item in _decode(buffer).split(",")]
        return [
            (serial, f"KDC101 (SN={serial})")
            for serial in serials
            if serial
        ]
    except Exception as exc:
        logger.debug("KDC101 enumeration failed: %s", exc)
        return []


class ThorlabsKDC101:
    """KDC101 connection using Thorlabs' Kinesis DC-servo C API."""

    def __init__(
        self,
        serial: str,
        *,
        blocking: bool = True,
        poll_ms: int = 100,
        move_timeout: float = 120.0,
    ) -> None:
        if not serial:
            raise ValueError("A KDC101 serial number is required.")
        self.serial = str(serial)
        self.blocking = blocking
        self.poll_ms = int(poll_ms)
        self.move_timeout = float(move_timeout)
        self._lib: ctypes.WinDLL | None = None
        self._connected = False
        self._polling = False

    @property
    def is_connected(self) -> bool:
        if not self._connected or self._lib is None:
            return False
        try:
            return bool(self._lib.CC_CheckConnection(self._serial_bytes))
        except Exception:
            return False

    @property
    def _serial_bytes(self) -> bytes:
        return self.serial.encode("ascii")

    def _check(self, result: int, operation: str) -> None:
        if result != 0:
            raise KDC101Error(f"{operation} failed (Kinesis error {result}).")

    def connect(self) -> None:
        if self._connected:
            return
        self._lib = _load_library()
        if self._lib.TLI_BuildDeviceList() != 0:
            raise KDC101Error("Building the Kinesis device list failed.")
        self._check(self._lib.CC_Open(self._serial_bytes), "Opening KDC101")
        self._connected = True
        try:
            if not self._lib.CC_StartPolling(self._serial_bytes, self.poll_ms):
                raise KDC101Error("Starting KDC101 polling failed.")
            self._polling = True
            self._check(
                self._lib.CC_EnableChannel(self._serial_bytes),
                "Enabling KDC101 motor channel",
            )
            time.sleep(0.25)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._lib is None:
            return
        if self._polling:
            try:
                self._lib.CC_StopPolling(self._serial_bytes)
            except Exception:
                pass
            self._polling = False
        if self._connected:
            try:
                self._lib.CC_Close(self._serial_bytes)
            except Exception:
                pass
            self._connected = False

    def identity(self) -> tuple[str, str]:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        model_buffer = ctypes.create_string_buffer(65)
        device_type = ctypes.c_ushort()
        channel_count = ctypes.c_ushort()
        notes = ctypes.create_string_buffer(256)
        firmware = ctypes.c_uint32()
        hardware = ctypes.c_ushort()
        modification = ctypes.c_ushort()
        self._check(
            self._lib.CC_GetHardwareInfo(
                self._serial_bytes,
                model_buffer,
                len(model_buffer),
                ctypes.byref(device_type),
                ctypes.byref(channel_count),
                notes,
                len(notes),
                ctypes.byref(firmware),
                ctypes.byref(hardware),
                ctypes.byref(modification),
            ),
            "Reading KDC101 hardware information",
        )
        return _decode(model_buffer), self.serial

    def load_settings(self) -> bool:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        return bool(self._lib.CC_LoadSettings(self._serial_bytes))

    def load_named_settings(self, settings_name: str) -> bool:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        return bool(
            self._lib.CC_LoadNamedSettings(
                self._serial_bytes, settings_name.encode("ascii")
            )
        )

    def set_motor_params(
        self,
        steps_per_rev: float,
        gearbox_ratio: float = 1.0,
        pitch: float = 1.0,
    ) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_SetMotorParamsExt(
                self._serial_bytes,
                float(steps_per_rev),
                float(gearbox_ratio),
                float(pitch),
            ),
            "Setting KDC101 motor parameters",
        )

    def get_motor_params(self) -> tuple[float, float, float]:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        steps = ctypes.c_double()
        gearbox = ctypes.c_double()
        pitch = ctypes.c_double()
        self._check(
            self._lib.CC_GetMotorParamsExt(
                self._serial_bytes,
                ctypes.byref(steps),
                ctypes.byref(gearbox),
                ctypes.byref(pitch),
            ),
            "Reading KDC101 motor parameters",
        )
        return steps.value, gearbox.value, pitch.value

    def set_travel_mode(self, mode: int) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_SetMotorTravelMode(self._serial_bytes, int(mode)),
            "Setting KDC101 travel mode",
        )

    def get_travel_mode(self) -> int:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        return int(self._lib.CC_GetMotorTravelMode(self._serial_bytes))

    @property
    def is_rotational(self) -> bool:
        return self.get_travel_mode() == _MOT_ROTATIONAL

    def request_settings(self) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_RequestSettings(self._serial_bytes),
            "Requesting KDC101 settings",
        )

    def _device_to_real(self, value: int, unit_type: int) -> float:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        real = ctypes.c_double()
        self._check(
            self._lib.CC_GetRealValueFromDeviceUnit(
                self._serial_bytes,
                int(value),
                ctypes.byref(real),
                int(unit_type),
            ),
            "Converting KDC101 device units",
        )
        return float(real.value)

    def _real_to_device(self, value: float, unit_type: int) -> int:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        device = ctypes.c_int()
        self._check(
            self._lib.CC_GetDeviceUnitFromRealValue(
                self._serial_bytes,
                float(value),
                ctypes.byref(device),
                int(unit_type),
            ),
            "Converting KDC101 physical units",
        )
        return int(device.value)

    def get_position(self) -> float:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_RequestPosition(self._serial_bytes),
            "Requesting KDC101 position",
        )
        time.sleep(max(0.02, self.poll_ms / 2000.0))
        position = int(self._lib.CC_GetPosition(self._serial_bytes))
        return self._device_to_real(position, _UNIT_DISTANCE)

    def get_velocity(self) -> float:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_RequestVelParams(self._serial_bytes),
            "Requesting KDC101 velocity parameters",
        )
        time.sleep(max(0.02, self.poll_ms / 2000.0))
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        self._check(
            self._lib.CC_GetVelParams(
                self._serial_bytes,
                ctypes.byref(acceleration),
                ctypes.byref(velocity),
            ),
            "Reading KDC101 velocity parameters",
        )
        return self._device_to_real(velocity.value, _UNIT_VELOCITY)

    def set_velocity(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("Velocity must be positive.")
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_RequestVelParams(self._serial_bytes),
            "Requesting KDC101 velocity parameters",
        )
        time.sleep(max(0.02, self.poll_ms / 2000.0))
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        self._check(
            self._lib.CC_GetVelParams(
                self._serial_bytes,
                ctypes.byref(acceleration),
                ctypes.byref(velocity),
            ),
            "Reading KDC101 velocity parameters",
        )
        max_velocity = self._real_to_device(speed, _UNIT_VELOCITY)
        self._check(
            self._lib.CC_SetVelParams(
                self._serial_bytes,
                acceleration.value,
                max_velocity,
            ),
            "Setting KDC101 velocity parameters",
        )

    def move_to(self, position: float) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        device_position = self._real_to_device(position, _UNIT_DISTANCE)
        self._check(
            self._lib.CC_MoveToPosition(self._serial_bytes, device_position),
            "Starting KDC101 absolute move",
        )
        if self.blocking:
            self.wait_move()

    def move_by(self, displacement: float) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        device_distance = self._real_to_device(displacement, _UNIT_DISTANCE)
        self._check(
            self._lib.CC_MoveRelative(self._serial_bytes, device_distance),
            "Starting KDC101 relative move",
        )
        if self.blocking:
            self.wait_move()

    def home(self) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_Home(self._serial_bytes),
            "Starting KDC101 homing",
        )
        if self.blocking:
            self.wait_move()

    def status_bits(self) -> int:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_RequestStatusBits(self._serial_bytes),
            "Requesting KDC101 status",
        )
        time.sleep(max(0.02, self.poll_ms / 2000.0))
        return int(self._lib.CC_GetStatusBits(self._serial_bytes))

    def is_moving(self) -> bool:
        return bool(self.status_bits() & _STATUS_MOVING)

    @property
    def is_homed(self) -> bool:
        return bool(self.status_bits() & _STATUS_HOMED)

    def wait_move(self) -> None:
        time.sleep(0.2)
        deadline = time.monotonic() + self.move_timeout
        while self.is_moving():
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"KDC101 {self.serial} did not finish moving within "
                    f"{self.move_timeout:.0f}s."
                )
            time.sleep(0.1)

    def stop(self) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._check(
            self._lib.CC_StopProfiled(self._serial_bytes),
            "Stopping KDC101",
        )

    def identify(self) -> None:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        self._lib.CC_Identify(self._serial_bytes)

    def can_home(self) -> bool:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        return bool(self._lib.CC_CanHome(self._serial_bytes))

    def can_move_without_homing(self) -> bool:
        if self._lib is None:
            raise KDC101Error("KDC101 is not connected.")
        return bool(self._lib.CC_CanMoveWithoutHomingFirst(self._serial_bytes))
