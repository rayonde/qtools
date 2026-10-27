"""Connection management and device resolution for stepper motors.

Provides helper functions to resolve and instantiate :class:`MotorBackend`
handles. Connection lifecycle is managed directly by individual instances
or via context managers.
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

from qtools.motor.backends.motor import DEFAULT_BACKEND, MotorBackend, list_devices
from qtools.motor.config import MotorConfigManager

logger = logging.getLogger(__name__)


def _parse_device_info(
    target: str | int | None = None,
    backend: str | type = DEFAULT_BACKEND,
    config_mgr: MotorConfigManager | None = None,
) -> Tuple[str, str, str]:
    """Parse target identifier into (resolved_port, dev_name, serial_no).

    Resolution Flow:
    - If target is None (Auto-detect):
      1. Check Config: if a single device is configured, match its port/serial in USB scan.
      2. Scan USB list_devices():
         - 0 devices: raise ConnectionError.
         - 1 device: auto-select single connected device and fill config info.
         - >1 devices: raise ValueError requiring target specification.

    - If target is specified:
      1. Direct serial port path (e.g. 'COM3', '/dev/ttyUSB0').
      2. Config lookup by id/name/serial/optical_path -> match USB scan by port or serial.
      3. Physical device scan fallback (1-based index or serial/port substring).
    """
    cfg = config_mgr or MotorConfigManager.resolve()
    devices = list_devices(backend)

    # ── Scenario A: target is None (Auto-detect mode) ───────────
    if target is None:
        if not devices:
            raise ConnectionError("No motors detected. Check USB connection and power.")

        # 1. Check if Config defines a single registered device
        cfg_devices = cfg.get_all_devices()
        if len(cfg_devices) == 1:
            entry = cfg_devices[0]
            dev_name = str(entry.get("name") or entry.get("optical_path") or "")
            serial_no = str(entry.get("serial") or "")
            resolved_port = str(entry.get("port") or "")
            return resolved_port, dev_name, serial_no

        # 2. USB Auto-detection fallback
        if len(devices) == 1:
            port, label = devices[0]
            m = re.search(r"SN=([a-zA-Z0-9]+)", label)
            serial_no = re.sub(r"\D", "", m.group(1)) if m else ""
            entry = cfg.get_device(serial_no) if serial_no else None
            dev_name = str(entry.get("name") if entry else "")
            return port, dev_name, serial_no

        ports = [p for p, _ in devices]
        raise ValueError(
            f"Multiple motor devices connected on ports {ports}. "
            "Please specify target device by name, serial, or port."
        )

    # ── Scenario B: target is specified ───────────────────────────
    target_str = str(target).strip()
    dev_name = target_str
    serial_no = ""
    resolved_port = ""

    # 1. Direct serial port path (COMx, /dev/...)
    if target_str.startswith("/") or target_str.upper().startswith("COM"):
        return target_str, dev_name, serial_no

    # 2. Config lookup by id / name / serial / optical_path
    entry = cfg.get_device(target)
    if entry:
        dev_name = str(entry.get("name") or entry.get("optical_path") or target_str)
        serial_no = str(entry.get("serial") or "")
        configured_port = str(entry.get("port") or "")
        if configured_port:
            resolved_port = configured_port

    # 3. Match serial number against connected USB devices
    if not resolved_port and serial_no:
        for p, label in devices:
            if serial_no in label:
                resolved_port = p
                break

    # 4. Fallback: match device index (1-based) or serial/port substring from list_devices
    if not resolved_port:
        if target_str.isdigit() and devices:
            idx = int(target_str) - 1
            if 0 <= idx < len(devices):
                resolved_port = devices[idx][0]
        else:
            for p, label in devices:
                if target_str.lower() in label.lower() or target_str.lower() in p.lower():
                    resolved_port = p
                    break

    if not resolved_port:
        raise ConnectionError(
            f"Could not resolve motor device for target '{target}'. Check connection and configuration."
        )

    return resolved_port, dev_name, serial_no


def get_motor(
    target: str | int | None = None,
    *,
    port: str | None = None,
    name: str | None = None,
    blocking: bool = True,
    backend: str | type[MotorBackend] | None = None,
    config_mgr: MotorConfigManager | None = None,
) -> MotorBackend:
    """Resolve device target and return a :class:`MotorBackend` handle.

    Parameters
    ----------
    target : str or int, optional
        Target device identifier (id, name, serial port, serial number, or optical path).
    port : str, optional
        Explicit serial port path (legacy keyword argument).
    name : str, optional
        Configured device name or alias (legacy keyword argument).
    blocking : bool, default True
        Whether movement commands block until completion.
    backend : str or type, optional
        Backend implementation identifier (defaults to 'k10cr1').
    config_mgr : MotorConfigManager, optional
        Custom configuration manager instance.

    Returns
    -------
    MotorBackend
        An instantiated motor backend handle. Connect via ``with get_motor(...) as motor:``.
    """
    target = target if target is not None else (name or port)
    backend_arg = backend if backend is not None else DEFAULT_BACKEND

    resolved_port, dev_name, serial_no = _parse_device_info(
        target=target,
        backend=backend_arg,
        config_mgr=config_mgr,
    )

    return MotorBackend(
        port=resolved_port,
        blocking=blocking,
        name=dev_name,
        serial_no=serial_no,
        backend=backend_arg,
        config_mgr=config_mgr,
    )
