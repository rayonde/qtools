"""Dependency-free camera enumeration through the Spinnaker C API."""

from __future__ import annotations

import ctypes
import ctypes.util
import ipaddress
import os
import re
import shutil
from dataclasses import replace
from pathlib import Path

from qtools.camera.base import CameraInfo
from qtools.camera.exceptions import CameraDependencyError, CameraDiscoveryError


def _decode_spinnaker_text(raw: bytes) -> str:
    for encoding in ("utf-8", "mbcs", "latin-1"):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _spinnaker_c_candidates() -> list[str]:
    """Return possible paths to the installed Spinnaker C runtime."""

    candidates: list[str] = []
    override = os.environ.get("SPINNAKER_C_LIBRARY")
    if override:
        candidates.append(override)

    if os.name == "nt":
        roots: list[Path] = []
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            value = os.environ.get(variable)
            if value:
                roots.extend(
                    [
                        Path(value) / "Teledyne" / "Spinnaker",
                        Path(value) / "FLIR Systems" / "Spinnaker",
                    ]
                )
        for root in roots:
            for path in sorted(root.glob("bin64/vs*/SpinnakerC*.dll")):
                if re.fullmatch(r"SpinnakerC(?:_v\d+)?\.dll", path.name, re.IGNORECASE):
                    candidates.append(str(path))
        for name in ("SpinnakerC_v140.dll", "SpinnakerC.dll"):
            executable = shutil.which(name)
            if executable:
                candidates.append(executable)
    else:
        for name in ("SpinnakerC", "Spinnaker_C"):
            library = ctypes.util.find_library(name)
            if library:
                candidates.append(library)
        candidates.extend(
            [
                "/opt/spinnaker/lib/libSpinnakerC.so",
                "/opt/spinnaker/lib/libSpinnaker_C.so",
            ]
        )

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _load_spinnaker_c_library() -> ctypes.CDLL:
    """Load the SDK without importing PySpin or changing Python runtimes."""

    errors: list[str] = []
    for candidate in _spinnaker_c_candidates():
        try:
            return ctypes.CDLL(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    detail = "; ".join(errors) if errors else "no Spinnaker C library candidates found"
    raise CameraDependencyError(
        "The Spinnaker SDK C runtime is unavailable. Camera enumeration only "
        "inspects an already installed SDK and does not install PySpin or another "
        f"Python runtime ({detail})."
    )


def _format_gige_ip(value: str) -> str:
    if not value:
        return ""
    text = value.strip()
    if not text or "." in text:
        return text
    try:
        number = int(text, 0)
    except ValueError:
        return text
    if 0 <= number <= 0xFFFFFFFF:
        return str(ipaddress.IPv4Address(number))
    return text


class SpinnakerCApi:
    """Minimal wrapper around the Spinnaker C API used for camera discovery."""

    def __init__(self, library: ctypes.CDLL) -> None:
        self._library = library
        self._handle = ctypes.c_void_p
        self._size = ctypes.c_size_t
        self.get_system = self._bind(
            "spinSystemGetInstance", [ctypes.POINTER(self._handle)]
        )
        self.release_system = self._bind("spinSystemReleaseInstance", [self._handle])
        self.get_interfaces = self._bind(
            "spinSystemGetInterfaces", [self._handle, self._handle]
        )
        self.create_interfaces = self._bind(
            "spinInterfaceListCreateEmpty", [ctypes.POINTER(self._handle)]
        )
        self.destroy_interfaces = self._bind("spinInterfaceListDestroy", [self._handle])
        self.interface_size = self._bind(
            "spinInterfaceListGetSize", [self._handle, ctypes.POINTER(self._size)]
        )
        self.get_interface = self._bind(
            "spinInterfaceListGet", [self._handle, self._size, ctypes.POINTER(self._handle)]
        )
        self.release_interface = self._bind("spinInterfaceRelease", [self._handle])
        self.get_interface_cameras = self._bind(
            "spinInterfaceGetCameras", [self._handle, self._handle]
        )
        self.create_cameras = self._bind(
            "spinCameraListCreateEmpty", [ctypes.POINTER(self._handle)]
        )
        self.destroy_cameras = self._bind("spinCameraListDestroy", [self._handle])
        self.camera_size = self._bind(
            "spinCameraListGetSize", [self._handle, ctypes.POINTER(self._size)]
        )
        self.get_camera = self._bind(
            "spinCameraListGet", [self._handle, self._size, ctypes.POINTER(self._handle)]
        )
        self.release_camera = self._bind("spinCameraRelease", [self._handle])
        self.get_interface_node_map = self._bind(
            "spinInterfaceGetTLNodeMap", [self._handle, ctypes.POINTER(self._handle)]
        )
        self.get_device_node_map = self._bind(
            "spinCameraGetTLDeviceNodeMap", [self._handle, ctypes.POINTER(self._handle)]
        )
        self.get_node = self._bind(
            "spinNodeMapGetNode",
            [self._handle, ctypes.c_char_p, ctypes.POINTER(self._handle)],
        )
        self.node_is_readable = self._bind(
            "spinNodeIsReadable", [self._handle, ctypes.POINTER(ctypes.c_bool)]
        )
        self.node_to_string = self._bind(
            "spinNodeToString",
            [self._handle, ctypes.c_char_p, ctypes.POINTER(self._size)],
        )

    def _bind(self, name: str, argtypes: list[object]) -> object:
        function = getattr(self._library, name)
        function.argtypes = argtypes
        function.restype = ctypes.c_int
        return function

    def _check(self, result: int, operation: str) -> None:
        if result != 0:
            raise CameraDiscoveryError(
                f"Spinnaker C API failed while {operation} (error {result})."
            )

    def _node_value(self, node_map: object, name: str) -> str:
        node = self._handle()
        result = self.get_node(node_map, name.encode("ascii"), ctypes.byref(node))
        if result != 0 or not node:
            return ""
        readable = ctypes.c_bool()
        result = self.node_is_readable(node, ctypes.byref(readable))
        if result != 0 or not readable.value:
            return ""
        buffer = ctypes.create_string_buffer(4096)
        buffer_size = self._size(len(buffer))
        result = self.node_to_string(node, buffer, ctypes.byref(buffer_size))
        if result != 0:
            return ""
        return _decode_spinnaker_text(bytes(buffer.value)).strip()
    def list_cameras(self) -> list[CameraInfo]:
        system = self._handle()
        interfaces = self._handle()
        self._check(self.get_system(ctypes.byref(system)), "acquiring the system")
        try:
            self._check(
                self.create_interfaces(ctypes.byref(interfaces)),
                "creating the interface list",
            )
            self._check(self.get_interfaces(system, interfaces), "enumerating interfaces")
            interface_count = self._size()
            self._check(
                self.interface_size(interfaces, ctypes.byref(interface_count)),
                "reading the interface count",
            )
            cameras: list[CameraInfo] = []
            for interface_index in range(interface_count.value):
                interface = self._handle()
                self._check(
                    self.get_interface(
                        interfaces, interface_index, ctypes.byref(interface)
                    ),
                    "reading an interface",
                )
                try:
                    interface_map = self._handle()
                    has_interface_map = (
                        self.get_interface_node_map(interface, ctypes.byref(interface_map)) == 0
                    )
                    interface_values = {
                        name: self._node_value(interface_map, name)
                        if has_interface_map
                        else ""
                        for name in ("InterfaceID", "InterfaceDisplayName", "InterfaceType")
                    }
                    camera_list = self._handle()
                    self._check(
                        self.create_cameras(ctypes.byref(camera_list)),
                        "creating a camera list",
                    )
                    try:
                        self._check(
                            self.get_interface_cameras(interface, camera_list),
                            "enumerating interface cameras",
                        )
                        camera_count = self._size()
                        self._check(
                            self.camera_size(camera_list, ctypes.byref(camera_count)),
                            "reading the interface camera count",
                        )
                        for camera_index in range(camera_count.value):
                            camera = self._handle()
                            self._check(
                                self.get_camera(
                                    camera_list, camera_index, ctypes.byref(camera)
                                ),
                                "reading a camera",
                            )
                            try:
                                device_map = self._handle()
                                self._check(
                                    self.get_device_node_map(
                                        camera, ctypes.byref(device_map)
                                    ),
                                    "reading camera information",
                                )
                                values = {
                                    name: self._node_value(device_map, name)
                                    for name in (
                                        "DeviceID",
                                        "DeviceSerialNumber",
                                        "DeviceVendorName",
                                        "DeviceModelName",
                                        "DeviceLocation",
                                        "DevicePortId",
                                        "DeviceInstanceId",
                                        "GevDeviceIPAddress",
                                        "GevDeviceMACAddress",
                                    )
                                }
                                interface_type = interface_values["InterfaceType"]
                                gigabit = "gige" in interface_type.casefold()
                                port = (
                                    _format_gige_ip(values["GevDeviceIPAddress"])
                                    or values["GevDeviceMACAddress"]
                                    if gigabit
                                    else (
                                        values["DeviceLocation"]
                                        or values["DevicePortId"]
                                        or values["DeviceInstanceId"]
                                    )
                                )
                                port = (
                                    port
                                    or values["DeviceID"]
                                    or interface_values["InterfaceID"]
                                )
                                cameras.append(
                                    CameraInfo(
                                        serial=(
                                            values["DeviceSerialNumber"]
                                            or values["DeviceID"]
                                            or f"cam_{len(cameras) + 1}"
                                        ),
                                        model=values["DeviceModelName"] or "unknown",
                                        vendor=values["DeviceVendorName"] or "unknown",
                                        index=len(cameras) + 1,
                                        device_id=values["DeviceID"],
                                        interface_type=interface_type,
                                        interface_id=interface_values["InterfaceID"],
                                        interface_name=interface_values["InterfaceDisplayName"],
                                        port=port,
                                    )
                                )
                            finally:
                                self.release_camera(camera)
                    finally:
                        self.destroy_cameras(camera_list)
                finally:
                    self.release_interface(interface)
            cameras.sort(
                key=lambda camera: (
                    camera.serial.casefold(),
                    camera.device_id.casefold(),
                    camera.port.casefold(),
                )
            )
            return [
                replace(camera, index=index)
                for index, camera in enumerate(cameras, start=1)
            ]
        finally:
            if interfaces:
                self.destroy_interfaces(interfaces)
            self.release_system(system)


def discover_spinnaker_cameras() -> list[CameraInfo]:
    """Enumerate connected cameras without importing PySpin."""

    return SpinnakerCApi(_load_spinnaker_c_library()).list_cameras()

