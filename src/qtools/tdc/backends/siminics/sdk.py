"""Lazy ctypes bindings for the Siminics FTMT V2.2 DLL."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any

from .errors import SiminicsError, SiminicsSDKError, SiminicsSDKUnavailable

DLL_NAME = "smncsftmt.dll"
_PACKAGE_LIB = Path(__file__).with_name("libs") / "win64" / DLL_NAME


class FtmtRawData(ctypes.Structure):
    """ABI-compatible representation of the vendor ``FtmtRawData`` struct."""

    _fields_ = [
        ("nType", ctypes.c_int),
        # C long is 32-bit on Windows x64 (the supported target).
        ("lLength", ctypes.c_int32),
        ("ptrData", ctypes.POINTER(ctypes.c_ubyte)),
    ]

_FUNCTIONS: dict[str, tuple[list[Any], Any]] = {
    "InitDll": ([], ctypes.c_int),
    "InitDev": ([], ctypes.c_int),
    "UnInitDll": ([], ctypes.c_int),
    "DevConnected": ([ctypes.c_int], ctypes.c_bool),
    "GetDevType": ([ctypes.c_int, ctypes.POINTER(ctypes.c_uint)], ctypes.c_int),
    "GetSerialNumber": ([ctypes.c_int], ctypes.POINTER(ctypes.c_char)),
    "FreeSerialNumberStr": ([ctypes.POINTER(ctypes.c_char)], None),
    "GetSignalStatus": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)], ctypes.c_int),
    "SetStartFreqDiv": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetTimeWindowRes": ([ctypes.c_int, ctypes.c_uint], ctypes.c_int),
    "SetBlockedWindow": ([ctypes.c_int, ctypes.c_float], ctypes.c_int),
    "SetStartThreshold": ([ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStopThreshold": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStartDelay": ([ctypes.c_int, ctypes.c_int, ctypes.c_float], ctypes.c_int),
    "SetStopDelay": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_float], ctypes.c_int),
    "SetStartImpedence": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStopImpedence": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStartEdge": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStopEdge": ([ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetFilePath": ([ctypes.c_int, ctypes.c_int, ctypes.c_char_p], ctypes.c_int),
    "SetFileMode": ([ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "SetStatisticsTime": ([ctypes.c_int, ctypes.c_float], ctypes.c_int),
    "SetTTTREndMode": ([ctypes.c_int, ctypes.c_ulonglong], ctypes.c_int),
    "SetITTREndMode": ([ctypes.c_int, ctypes.c_ulonglong], ctypes.c_int),
    "SetT1Interval": ([ctypes.c_float], ctypes.c_int),
    "SetBinSize": ([ctypes.c_int, ctypes.c_uint], ctypes.c_int),
    "SetMaxBarValue": ([ctypes.c_ulonglong], ctypes.c_int),
    "EnableT1": ([ctypes.c_int, ctypes.c_int, ctypes.c_ushort], ctypes.c_int),
    "GetT1Data": ([ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ulonglong)], ctypes.c_int),
    "EnableITTR": ([ctypes.c_int, ctypes.c_int, ctypes.c_ushort], ctypes.c_int),
    "SetITTRInterval": ([ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "GetIttrDataOverflow": ([ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)], ctypes.c_int),
    "EnableTTTR": ([ctypes.c_int, ctypes.c_int, ctypes.c_ushort], ctypes.c_int),
    "GetTttrDataOverflow": ([ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)], ctypes.c_int),
    "DmtchInitialize": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "DmtchModeSelection": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
    "DmtchAddStrategy": ([ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_ulonglong, ctypes.c_float, ctypes.c_int, ctypes.c_float, ctypes.c_int], ctypes.c_int),
    "DmtchGetStratgyCount": ([ctypes.c_int], ctypes.c_ulonglong),
    "StartTask": ([ctypes.c_int], ctypes.c_int),
    "StopTask": ([ctypes.c_int], ctypes.c_int),
    "IsTaskCompleted": ([], ctypes.c_int),
    "SetMemoryDataMode": ([ctypes.c_bool], ctypes.c_int),
    "MemoryDataModeEnabled": ([], ctypes.c_bool),
    "GetMemoryData": ([ctypes.c_int], ctypes.POINTER(FtmtRawData)),
    "ReleaseMemoryData": ([ctypes.POINTER(FtmtRawData)], ctypes.c_int),
}


def _as_bytes(ptr: ctypes.POINTER(FtmtRawData)) -> bytes:
    if not ptr or not ptr.contents.ptrData or ptr.contents.lLength <= 0:
        return b""
    return ctypes.string_at(ptr.contents.ptrData, int(ptr.contents.lLength))


class SiminicsSDK:
    """Small typed wrapper around ``smncsftmt.dll``.

    The class is intentionally lazy: importing the backend works on Linux and
    macOS, while loading the vendor DLL happens only in ``connect``.
    """

    def __init__(self, dll_path: str | os.PathLike[str] | None = None, library: Any = None):
        self.dll_path = Path(dll_path) if dll_path else _PACKAGE_LIB
        self._lib = library
        self._dll_dir_handle = None

    @property
    def loaded(self) -> bool:
        return self._lib is not None

    def load(self) -> SiminicsSDK:
        if self._lib is not None:
            return self
        if sys.platform != "win32":
            raise SiminicsSDKUnavailable(
                "Siminics FTMT DLL is a Windows x64 library; "
                "connect on a 64-bit Windows Python process."
            )
        if not self.dll_path.exists():
            raise SiminicsSDKUnavailable(
                f"Siminics DLL not found at {self.dll_path}. "
                "Copy smncsftmt.dll into backends/siminics/libs/win64."
            )
        try:
            if hasattr(os, "add_dll_directory"):
                self._dll_dir_handle = os.add_dll_directory(str(self.dll_path.parent))
            # The vendor Python examples use ``ctypes.cdll.LoadLibrary``;
            # the exported C API is cdecl rather than stdcall.
            self._lib = ctypes.CDLL(str(self.dll_path))
        except (OSError, AttributeError) as exc:
            raise SiminicsSDKUnavailable(
                f"Unable to load Siminics DLL {self.dll_path}: {exc}"
            ) from exc
        return self

    def _func(self, name: str, argtypes: list[Any] | None = None, restype: Any = ctypes.c_int):
        self.load()
        try:
            fn = getattr(self._lib, name)
        except AttributeError as exc:
            raise SiminicsSDKUnavailable(f"Siminics DLL does not export {name}") from exc
        if argtypes is not None:
            try:
                fn.argtypes = argtypes
            except (AttributeError, TypeError):
                # Lightweight fake libraries used by offline tests may expose
                # plain Python callables rather than ctypes function objects.
                pass
        try:
            fn.restype = restype
        except (AttributeError, TypeError):
            pass
        return fn

    def call(self, name: str, *args: Any, argtypes: list[Any] | None = None, restype: Any = ctypes.c_int):
        return self._func(name, argtypes, restype)(*args)

    def invoke(self, name: str, *args: Any):
        """Call one of the V2.2 functions with its declared ctypes ABI."""

        try:
            argtypes, restype = _FUNCTIONS[name]
        except KeyError:
            return self.call(name, *args)
        return self.call(name, *args, argtypes=argtypes, restype=restype)

    def check(self, name: str, *args: Any, argtypes: list[Any] | None = None) -> int:
        if argtypes is None and name in _FUNCTIONS:
            argtypes, declared_restype = _FUNCTIONS[name]
            restype = declared_restype
        else:
            restype = ctypes.c_int
        result = int(self.call(name, *args, argtypes=argtypes, restype=restype))
        if result != 0:
            raise SiminicsSDKError(name, result)
        return result

    def init(self) -> None:
        self.check("InitDll")
        try:
            self.check("InitDev")
        except Exception:
            try:
                self.call("UnInitDll")
            except (SiminicsError, OSError):
                # Preserve the original InitDev failure.
                pass
            raise

    def uninit(self) -> None:
        if self._lib is None:
            return
        try:
            self.call("UnInitDll")
        finally:
            if self._dll_dir_handle is not None:
                try:
                    self._dll_dir_handle.close()
                except (SiminicsError, OSError):
                    pass
                self._dll_dir_handle = None

    def connected(self, dev_id: int) -> bool:
        return bool(self.call("DevConnected", int(dev_id), restype=ctypes.c_bool))

    def device_type(self, dev_id: int) -> int:
        value = ctypes.c_uint(0)
        self.check("GetDevType", int(dev_id), ctypes.byref(value), argtypes=[ctypes.c_int, ctypes.POINTER(ctypes.c_uint)])
        return int(value.value)

    def serial_number(self, dev_id: int) -> str | None:
        # Keep the vendor pointer alive until ``FreeSerialNumberStr``.  Using
        # ``c_char_p`` as the restype would eagerly convert it to ``bytes``
        # and lose the allocation address required by the DLL's free routine.
        fn = self._func(
            "GetSerialNumber", [ctypes.c_int], ctypes.POINTER(ctypes.c_char)
        )
        ptr = fn(int(dev_id))
        if not ptr:
            return None
        try:
            value = ctypes.cast(ptr, ctypes.c_char_p).value
            return value.decode("utf-8", errors="replace") if value else None
        finally:
            try:
                self.call(
                    "FreeSerialNumberStr",
                    ptr,
                    argtypes=[ctypes.POINTER(ctypes.c_char)],
                    restype=None,
                )
            except (SiminicsError, OSError):
                pass

    def signal_status(self, dev_id: int, board: int, channel: int) -> tuple[int, int]:
        start = ctypes.c_uint(0)
        stop = ctypes.c_uint(0)
        self.check(
            "GetSignalStatus", int(dev_id), int(board), int(channel), ctypes.byref(start), ctypes.byref(stop),
            argtypes=[ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)],
        )
        return int(start.value), int(stop.value)

    def get_memory_data(self, dev_id: int) -> tuple[int, bytes] | None:
        fn = self._func("GetMemoryData", [ctypes.c_int], ctypes.POINTER(FtmtRawData))
        ptr = fn(int(dev_id))
        if not ptr:
            return None
        try:
            return int(ptr.contents.nType), _as_bytes(ptr)
        finally:
            self.call("ReleaseMemoryData", ptr, argtypes=[ctypes.POINTER(FtmtRawData)])

