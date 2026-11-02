"""TDC Connection and Device Discovery Registry.

Manages device connection dispatching, hardware backend registration,
and auto-discovery scanning.
"""

from __future__ import annotations

import logging
import select
import socket
import threading
import time
from importlib import import_module
from typing import Callable, Dict, List, Optional, Type

from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.data import DeviceInfo
from qtools.tdc.measurement import TDC

logger = logging.getLogger(__name__)

# Global registry mapping backend names to backend classes
_REGISTRY: Dict[str, Type[TDCBackend]] = {}


def register_backend(name: str) -> Callable[[Type[TDCBackend]], Type[TDCBackend]]:
    """Register a backend class in the global registry.

    Used as a class decorator:

    Example::

        @register_backend("tdc1")
        class TDC1Backend(TDCBackend):
            ...

    Args:
        name: Unique backend identifier (lowercase recommended).

    Returns:
        Decorator function.

    Raises:
        ValueError: If the name is already registered.
    """

    def decorator(cls: Type[TDCBackend]) -> Type[TDCBackend]:
        if name in _REGISTRY:
            raise ValueError(
                f"Backend '{name}' is already registered as {_REGISTRY[name].__name__}"
            )
        if not issubclass(cls, TDCBackend):
            raise TypeError(f"{cls.__name__} must be a subclass of TDCBackend")
        _REGISTRY[name] = cls
        logger.debug("Registered backend: %s -> %s", name, cls.__name__)
        return cls

    return decorator


def get_backend(name: str) -> Type[TDCBackend]:
    """Retrieve a registered backend class by name.

    Args:
        name: Backend identifier name.

    Returns:
        The corresponding ``TDCBackend`` subclass.

    Raises:
        KeyError: If the name is not registered.
    """
    # Explicit selection can load either TDC1 driver independently of the default.
    if name not in _REGISTRY and name in {"s15_tdc1", "exp_s15_tdc1"}:
        module = "backend" if name == "s15_tdc1" else "exp_backend"
        import_module(f"qtools.tdc.backends.s15_tdc1.{module}")
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "none"
        raise KeyError(f"Backend '{name}' not found. Available: {available}")
    return _REGISTRY[name]


def get_tdc(
    backend: str | DeviceInfo,
    port: Optional[str] = None,
    *,
    bin_width: int | None = None,
    **kwargs,
) -> TDC:
    """Create a TDC; enter its context to open the hardware connection.

    Args:
        backend: Registered backend identifier, or a ``DeviceInfo`` returned
            by discovery.
        port: Device path / address, or None to let the backend auto-discover.
        bin_width: Default analysis bin width in ps, or None for native resolution.
        **kwargs: Extra parameters forwarded to the backend constructor.

    Returns:
        A ``TDC`` instance wrapping the instantiated backend.

    Raises:
        KeyError: If *backend* is not registered.
    """

    if not isinstance(backend, (str, DeviceInfo)):
        raise TypeError(
            "backend must be a registered backend name or a DeviceInfo instance"
        )
    return TDC(backend=backend, port=port, bin_width=bin_width, **kwargs)


def list_backends() -> Dict[str, Type[TDCBackend]]:
    """Return a copy of all registered backends.

    Returns:
        A ``{name: backend_class}`` dictionary.
    """
    return dict(_REGISTRY)


def _discover_backend_with_timeout(
    name: str,
    backend_cls: Type[TDCBackend],
    timeout: float,
) -> List[DeviceInfo]:
    """Run one backend discovery in a daemon thread with a hard deadline."""
    state: dict[str, object] = {"devices": [], "error": None}

    def worker() -> None:
        try:
            state["devices"] = list(backend_cls.discover_devices())
        except Exception as exc:  # noqa: BLE001 - surfaced through state
            state["error"] = exc

    thread = threading.Thread(
        target=worker,
        name=f"tdc-discover-{name}",
        daemon=True,
    )
    thread.start()
    thread.join(max(0.05, float(timeout)))

    if thread.is_alive():
        logger.warning(
            "Backend '%s' discovery exceeded %.2fs; skipping it",
            name,
            timeout,
        )
        return []

    error = state.get("error")
    if error is not None:
        logger.warning("Backend '%s' discovery failed: %s", name, error)
        return []

    devices = state.get("devices", [])
    return list(devices) if isinstance(devices, list) else []


def auto_discover(timeout: float = 2.0) -> List[DeviceInfo]:
    """Run bounded device discovery on all registered backends.

    Duplicate registrations of the same backend class are scanned once. Each
    backend gets at most *timeout* seconds, so a blocking vendor SDK or serial
    driver cannot make ``list_tdc`` hang indefinitely.
    """
    all_devices: List[DeviceInfo] = []
    seen_backends: set[Type[TDCBackend]] = set()

    for name, backend_cls in sorted(_REGISTRY.items()):
        if backend_cls in seen_backends:
            continue
        seen_backends.add(backend_cls)
        logger.info("Scanning backend: %s (%s)", name, backend_cls.__name__)
        started = time.monotonic()
        devices = _discover_backend_with_timeout(name, backend_cls, timeout)
        all_devices.extend(devices)
        logger.info(
            "Backend '%s' found %d device(s) in %.2fs",
            name,
            len(devices),
            time.monotonic() - started,
        )

    return all_devices


def discover_network_devices(timeout: float = 1.0) -> List[DeviceInfo]:
    """Scan the local network for Ethernet-connected TDC devices using UDP broadcast.

    Sends a discovery ping to the broadcast address and waits for responses.
    """
    devices: List[DeviceInfo] = []
    discovery_port = 35515
    discovery_msg = b"TDC_DISCOVER"

    # Create UDP socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
    except Exception as e:
        logger.debug("Failed to create discovery socket: %s", e)
        return devices

    try:
        # Broadcast ping to local subnet
        sock.sendto(discovery_msg, ("255.255.255.255", discovery_port))

        # Listen for replies
        import time

        t_end = time.time() + timeout

        while time.time() < t_end:
            remaining = t_end - time.time()
            if remaining <= 0:
                break

            ready = select.select([sock], [], [], remaining)
            if ready[0]:
                data, addr = sock.recvfrom(1024)
                # Simple check for signature response (e.g. starting with TDC_REPLY)
                if data.startswith(b"TDC_REPLY"):
                    payload = data[9:].decode("utf-8", errors="ignore").strip()
                    # Expect response formatted like: "serial_number|description"
                    parts = payload.split("|")
                    sn = parts[0] if len(parts) > 0 and parts[0] else None
                    desc = parts[1] if len(parts) > 1 else "Ethernet TDC Device"

                    devices.append(
                        DeviceInfo(
                            backend_name="network_tdc",
                            device_path=f"udp://{addr[0]}:{addr[1]}",
                            serial_number=sn,
                            description=desc,
                            transport="ethernet",
                            host=addr[0],
                            port=addr[1],
                            protocol="udp",
                        )
                    )
    except Exception as e:
        logger.debug("Error during UDP broadcast discovery: %s", e)
    finally:
        sock.close()

    return devices


def discover_all(method: str = "all", timeout: float = 2.0) -> List[DeviceInfo]:
    """Import backends dynamically and perform device discovery (USB and/or Ethernet).

    Args:
        method:  The discovery method, either "usb", "ethernet", or "all".
        timeout: Maximum seconds allowed for each backend discovery routine.

    Returns:
        A list of DeviceInfo for all discovered devices.
    """
    if method not in {"usb", "ethernet", "all"}:
        raise ValueError("method must be 'usb', 'ethernet', or 'all'")

    # Import all backends before discovery. Each backend reports its own
    # transport and produces a path that its connector understands.
    try:
        import_module("qtools.tdc.backends")
    except Exception as e:
        logger.warning("Error dynamically importing backend modules: %s", e)

    devices = auto_discover(timeout=timeout)
    if method == "all":
        return devices

    if method == "ethernet":
        return [device for device in devices if device.transport == "ethernet"]

    # The CLI calls this mode "usb", but serial-backed USB devices are part
    # of the same local-device scan and are included for compatibility.
    return [device for device in devices if device.transport in {"usb", "serial"}]


def display_devices(devices: Optional[List[DeviceInfo]] = None) -> None:
    """Display discovered devices in a table format in the terminal.

    Args:
        devices: List of devices to display; if None, auto-discovery is performed.
    """
    if devices is None:
        devices = discover_all()

    registered = list_backends()

    # -- header --------------------------------------------------------
    print("=" * 72)
    print("TDC Device Discovery")
    print("=" * 72)

    # -- registered backends -------------------------------------
    print(f"\nRegistered backends ({len(registered)}):")
    if registered:
        for name, cls in sorted(registered.items()):
            print(f"  - {name:20s} -> {cls.__name__}")
    else:
        print("  (none)")

    # -- discovered devices --------------------------------------
    print(f"\nDiscovered devices ({len(devices)}):")
    if devices:
        print(
            f"  {'#':<4} {'Backend':<16} {'Transport':<12} {'Path':<28} "
            f"{'Endpoint':<24} {'S/N':<16} {'Desc'}"
        )
        print(
            f"  {'-' * 4} {'-' * 16} {'-' * 12} {'-' * 28} "
            f"{'-' * 24} {'-' * 16} {'-' * 20}"
        )
        for i, dev in enumerate(devices, 1):
            sn = dev.serial_number or "N/A"
            desc = dev.description or ""
            endpoint = dev.host or ""
            if dev.port is not None:
                endpoint = f"{endpoint}:{dev.port}" if endpoint else str(dev.port)
            if dev.protocol and endpoint:
                endpoint = f"{dev.protocol}://{endpoint}"
            print(
                f"  {i:<4} {dev.backend_name:<16} {dev.transport:<12} "
                f"{dev.device_path:<28} {endpoint:<24} {sn:<16} {desc}"
            )
    else:
        print("  (No devices found)")

    print()
    print("=" * 72)


def list_tdc(method: str = "all", timeout: float = 2.0) -> List[DeviceInfo]:
    """Discover attached TDC hardware, print its details, and return device records.

    Returned records can be passed directly to ``get_tdc`` or ``TDC``.
    Discovery does not open a persistent measurement connection.
    """
    devices = discover_all(method=method, timeout=timeout)
    display_devices(devices)
    return devices
