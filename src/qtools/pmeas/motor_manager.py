"""Multi-motor optical role resolver and session manager for qtools.pmeas.

Delegates physical connection and device resolution to :func:`qtools.motor.get_motor`,
while managing optical path role mappings and session lifecycle for polarization experiments.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

import serial.tools.list_ports

from qtools.pmeas.backends.motor import (
    MotorBackend,
    MotorConfigManager,
    get_motor as sm_get_motor,
    list_devices as sm_list_devices,
)
from qtools.pmeas.config import ConfigManager

logger = logging.getLogger(__name__)


def _check_availability(port: str | None) -> bool:
    """Check if the motor port is available on the system."""
    if not port:
        return False
    return port in [p.device for p in serial.tools.list_ports.comports()]


class MotorManager:
    """Manages optical role mapping, session lifecycle, and multi-motor coordination."""

    def __init__(self, config_mgr: ConfigManager):
        self.cfg = config_mgr
        self._available: Dict[str, MotorBackend] = {}
        self._notavailable: Dict[str, MotorBackend] = {}
        self._init_configured_devices()

    def _init_configured_devices(self) -> None:
        """Pre-populate motor handles for all configured devices into _available or _notavailable."""
        for dev_info in self.cfg.get_all_devices():
            dev_id = str(dev_info.get("id", ""))
            dev_port = dev_info.get("port")
            dev_serial = dev_info.get("serial")
            dev_backend = dev_info.get("backend")

            if not dev_id or dev_id in self._available or dev_id in self._notavailable:
                continue

            # 1. Port is online: connect directly and add to _available pool
            if dev_port and _check_availability(dev_port):
                try:
                    self._available[dev_id] = sm_get_motor(
                        port=dev_port, blocking=False, backend=dev_backend
                    )
                    logger.info("Motor '%s' port %s is available.", dev_id, dev_port)
                    continue
                except Exception as exc:
                    logger.warning("Motor '%s' port %s connect failed: %s", dev_id, dev_port, exc)

            # 2. Port is offline or serial-only: try resolving handle and add to _notavailable pool
            target = dev_serial or dev_id
            motor = None
            try:
                motor = sm_get_motor(target=target, blocking=False, backend=dev_backend)
            except Exception:
                logger.warning("Motor '%s' (target: %s) is not detected.", dev_id, target)

            self._notavailable[dev_id] = motor

    def list_devices(self) -> dict[str, list[dict[str, Any]]]:
        """Return categorized status for connected and not_connected devices without low-level USB scans."""
        def _build_item(dev_id: str, motor: MotorBackend, is_connected: bool) -> dict[str, Any]:
            dev = self.cfg.get_device(dev_id) or {}
            serial_no = str(dev.get("serial") or getattr(motor, "serial", ""))
            port = str(dev.get("port") or getattr(motor, "_port", ""))
            return {
                "id": dev.get("id") or dev_id,
                "name": str(dev.get("name") or ""),
                "optical_path": str(dev.get("optical_path") or ""),
                "role": str(dev.get("role") or ""),
                "serial": serial_no,
                "port": port,
                "is_connected": is_connected,
                "motor": motor,
            }

        return {
            "connected": [
                _build_item(dev_id, m, True) for dev_id, m in self._available.items()
            ],
            "not_connected": [
                _build_item(dev_id, m, False) for dev_id, m in self._notavailable.items()
            ],
        }

    def get_motor(self, target: str | int | None = None) -> MotorBackend:
        """Resolve a motor by target identifier (id, name, serial, port, or optical_path) and return its handle."""
        # 1. Return single available motor directly if target is None
        if target is None:
            if len(self._available) == 1:
                return next(iter(self._available.values()))
            elif len(self._available) == 0 and len(self._notavailable) == 1:
                raise ConnectionError("Motor is configured but not connected to system.")
            raise ValueError("Target device must be specified when multiple devices are configured.")

        target_str = str(target).strip().lower()

        # 2. Leverage ConfigManager for resolution (id / name / serial / port / optical_path)
        dev_info = self.cfg.get_device(target)
        if dev_info:
            dev_id = str(dev_info.get("id"))
            if dev_id in self._available:
                return self._available[dev_id]
            if dev_id in self._notavailable:
                raise ConnectionError(f"Target motor '{target}' (ID: {dev_id}) is not physically connected.")

        # 3. Fallback: search available motors by attributes (name, port, serial)
        for dev_id, motor in self._available.items():
            if target_str == dev_id.lower():
                return motor
            motor_name = str(getattr(motor, "name", "") or "").strip().lower()
            if motor_name and target_str == motor_name:
                return motor
            motor_port = str(getattr(motor, "_port", "") or "").strip().lower()
            if motor_port and target_str == motor_port:
                return motor

        # 4. Search not-available motors too (useful for error messages)
        for dev_id in self._notavailable.keys():
            if target_str == dev_id.lower():
                raise ConnectionError(f"Target motor '{target}' (ID: {dev_id}) is not physically connected.")

        # 5. Device not found in configuration
        raise ValueError(f"Target device '{target}' not found in configuration.")

    def register_existing_motor(self, target: str | int, motor: MotorBackend) -> None:
        """Register an already-instantiated motor handle into the pool."""
        dev_info = self.cfg.get_device(target)
        dev_id = str(dev_info.get("id")) if dev_info else str(target).strip().lower()
        if dev_id:
            self._available[dev_id] = motor
            self._notavailable.pop(dev_id, None)


    def wait_for_settle(self, roles: list[str]) -> None:
        """Wait for motors matching roles to settle."""
        for r in roles:
            try:
                motor = self.get_motor(r)
                motor.wait_move()
            except ValueError:
                logger.warning("Motor for role '%s' not found.", r)

    def disconnect_all(self) -> None:
        """Disconnect all registered motors."""
        for motor in list(self._available.values()):
            try:
                motor.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting motor: %s", exc)

    def __enter__(self) -> MotorManager:
        """Session context manager enter — check for newly available motors."""
        for dev_id in list(self._notavailable.keys()):
            dev_info = self.cfg.get_device(dev_id) or {}
            dev_port = dev_info.get("port")
            dev_backend = dev_info.get("backend")

            if dev_port and _check_availability(dev_port):
                try:
                    motor = sm_get_motor(port=dev_port, blocking=False, backend=dev_backend)
                    self._available[dev_id] = motor
                    del self._notavailable[dev_id]
                    logger.info("Motor '%s' on port %s detected and moved to available.", dev_id, dev_port)
                except Exception as exc:
                    logger.warning("Failed to initialize motor '%s' on port %s: %s", dev_id, dev_port, exc)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Session context manager exit — automatically disconnect all motors."""
        self.disconnect_all()

