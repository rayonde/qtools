"""Typed, lazy bindings for the TLDFM / TLDFMX Windows x64 SDK.

The control flow follows the local Light_Control_and_Manipulation_Examples.
Signatures and flags follow the vendor TLDFM.h / TLDFMX.h headers. Windows VISA
uses 32-bit sessions/statuses and 16-bit booleans, including in 64-bit Python.
"""

from __future__ import annotations

import ctypes as ct
import os
import sys
import warnings
from pathlib import Path
from typing import Any

from qtools.dm.exceptions import DMDependencyError, DMDriverError, DMDriverWarning
from qtools.dm.info import DeviceInfo

LIBRARY_DIR = Path(__file__).with_name("libs")
DLL_NAMES = ("TLDFM_64.dll", "TLDFMX_64.dll")
ViSession = ct.c_uint32
ViStatus = ct.c_int32
ViBoolean = ct.c_uint16
ViUInt32 = ct.c_uint32
ViInt32 = ct.c_int32
ViReal64 = ct.c_double
P = ct.POINTER
CHAR_BUFFER = P(ct.c_char)
ALL_ZERNIKES = 0xFFFFFFFF

_SIGNATURES = {
    "TLDFM_get_device_count": [ViSession, P(ViUInt32)],
    "TLDFM_get_device_information": [
        ViSession,
        ViUInt32,
        CHAR_BUFFER,
        CHAR_BUFFER,
        CHAR_BUFFER,
        P(ViBoolean),
        CHAR_BUFFER,
    ],
    "TLDFMX_init": [ct.c_char_p, ViBoolean, ViBoolean, P(ViSession)],
    "TLDFMX_close": [ViSession],
    "TLDFM_error_message": [ViSession, ViStatus, CHAR_BUFFER],
    "TLDFMX_error_message": [ViSession, ViStatus, CHAR_BUFFER],
    "TLDFM_get_segment_count": [ViSession, P(ViUInt32)],
    "TLDFM_get_tilt_count": [ViSession, P(ViUInt32)],
    "TLDFM_get_segment_minimum": [ViSession, P(ViReal64)],
    "TLDFM_get_segment_maximum": [ViSession, P(ViReal64)],
    "TLDFM_get_tilt_minimum": [ViSession, P(ViReal64)],
    "TLDFM_get_tilt_maximum": [ViSession, P(ViReal64)],
    "TLDFM_get_segment_voltages": [ViSession, P(ViReal64)],
    "TLDFM_get_tilt_voltages": [ViSession, P(ViReal64)],
    "TLDFM_set_segment_voltages": [ViSession, P(ViReal64)],
    "TLDFM_set_tilt_voltages": [ViSession, P(ViReal64)],
    "TLDFM_set_tilt_amplitude_angle": [ViSession, ViReal64, ViReal64],
    "TLDFMX_get_parameters": [
        ViSession,
        P(ViReal64),
        P(ViReal64),
        P(ViInt32),
        P(ViInt32),
        P(ViInt32),
    ],
    "TLDFMX_set_pattern_range_check": [ViSession, ViBoolean],
    "TLDFMX_calculate_single_zernike_pattern": [
        ViSession,
        ViUInt32,
        ViReal64,
        P(ViReal64),
    ],
    "TLDFMX_calculate_zernike_pattern": [ViSession, ViUInt32, P(ViReal64), P(ViReal64)],
    "TLDFMX_relax": [
        ViSession,
        ViInt32,
        ViBoolean,
        ViBoolean,
        P(ViReal64),
        P(ViReal64),
        P(ViInt32),
    ],
}


class DMP40SDK:
    """Load package-local DLLs, bind their C signatures and check VISA statuses.

    ``libraries`` is an injection point for isolated software tests. It does not
    simulate the physical device. Normal callers should leave it unset.
    """

    def __init__(
        self,
        dll_dir: str | os.PathLike[str] | None = None,
        *,
        libraries: tuple[Any, Any] | None = None,
    ) -> None:
        self.dll_dir = Path(dll_dir).expanduser().resolve() if dll_dir else LIBRARY_DIR
        self._provided = libraries
        self._libraries: tuple[Any, Any] | None = None
        self._directory_handle: Any = None
        self._functions: dict[str, Any] = {}

    def load(self) -> DMP40SDK:
        if self._libraries is not None:
            return self
        try:
            if self._provided is not None:
                self._libraries = self._provided
            else:
                if sys.platform != "win32" or ct.sizeof(ct.c_void_p) != 8:
                    raise DMDependencyError(
                        "DMP40 hardware requires Windows with 64-bit Python. "
                        "Mode conversion and example --dry-run work on macOS/Linux."
                    )
                missing = [
                    name for name in DLL_NAMES if not (self.dll_dir / name).is_file()
                ]
                if missing:
                    raise DMDependencyError(
                        f"Missing {', '.join(missing)} in {self.dll_dir}. Copy the files "
                        "from the official Thorlabs Windows software into this directory."
                    )
                self._directory_handle = os.add_dll_directory(str(self.dll_dir))
                # Match the ctypes reference. Windows x64 has one calling convention.
                self._libraries = tuple(
                    ct.CDLL(str(self.dll_dir / name)) for name in DLL_NAMES
                )
            for name, args in _SIGNATURES.items():
                library = self._libraries[1 if name.startswith("TLDFMX_") else 0]
                function = getattr(library, name)
                function.argtypes = args
                function.restype = ViStatus
                self._functions[name] = function
        except DMDependencyError:
            self.unload()
            raise
        except (OSError, AttributeError) as exc:
            self.unload()
            raise DMDependencyError(
                f"Cannot load the DMP40 SDK in {self.dll_dir}: {exc}. "
                "Install the official Thorlabs Windows software and its VISA/USB/runtime "
                "prerequisites; having only the two DLLs may be insufficient."
            ) from exc
        return self

    def unload(self) -> None:
        """Release Python library references/search paths after closing all sessions."""
        self._functions.clear()
        self._libraries = None
        if self._directory_handle is not None:
            self._directory_handle.close()
            self._directory_handle = None

    def check(self, name: str, *args: Any) -> int:
        self.load()
        result = self._functions[name](*args)
        status = ViStatus(result.value if hasattr(result, "value") else result).value
        if status:
            error_name = (
                "TLDFMX_error_message"
                if name.startswith("TLDFMX_")
                else "TLDFM_error_message"
            )
            message = ct.create_string_buffer(512)
            session = 0 if name == "TLDFMX_init" else args[0]
            error_status = self._functions[error_name](session, status, message)
            detail = (
                message.value.decode("utf-8", errors="replace")
                if error_status == 0
                else ""
            )
            if status < 0:
                raise DMDriverError(name, status, detail)
            warnings.warn(
                f"{name}: 0x{status:08X} {detail}", DMDriverWarning, stacklevel=2
            )
        return status

    def discover(self) -> list[DeviceInfo]:
        count = ViUInt32()
        self.check("TLDFM_get_device_count", 0, ct.byref(count))
        devices = []
        for index in range(count.value):
            manufacturer, model, serial, resource = (
                ct.create_string_buffer(256) for _ in range(4)
            )
            available = ViBoolean()
            self.check(
                "TLDFM_get_device_information",
                0,
                index,
                manufacturer,
                model,
                serial,
                ct.byref(available),
                resource,
            )
            text = [
                buf.value.decode("utf-8", errors="replace")
                for buf in (serial, model, manufacturer, resource)
            ]
            devices.append(
                DeviceInfo(*text, available=bool(available.value), index=index)
            )
        return devices

    def scalar(
        self, name: str, session: ViSession, kind: Any = ViReal64
    ) -> int | float:
        value = kind()
        self.check(name, session, ct.byref(value))
        return value.value


__all__ = ["DLL_NAMES", "DMP40SDK", "LIBRARY_DIR", "DeviceInfo"]
