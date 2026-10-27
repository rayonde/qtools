"""Shared utility and helper functions for CLI commands."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, List


def _parse_channel(val: Any) -> int | tuple[int, ...] | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, (tuple, list)):
        return tuple(val)
    s = str(val).strip()
    if not s:
        return None
    if "," in s:
        return tuple(int(x.strip()) for x in s.split(",") if x.strip())
    return int(s)


def _cleanup(stages, meas_mgr: Any = None) -> None:
    for s in stages:
        if s:
            try:
                if hasattr(s, "disconnect"):
                    s.disconnect()
            except Exception:
                pass
    if meas_mgr is not None and hasattr(meas_mgr, "disconnect_all"):
        meas_mgr.disconnect_all()


def _connect_motor(
    *,
    port: str | None = None,
    name: str | None = None,
) -> Any:
    """Connect a single motor via qtools.motor and wrap it."""
    from qtools.pmeas.backends.motor import MotorBackend

    m = MotorBackend(port=port or "", name=name or "")
    if not m.connect():
        raise ConnectionError(
            f"Failed to connect motor (port={port!r}, name={name!r})."
        )
    return m


def _resolve_motor(
    port: str | None = None,
    name: str | None = None,
    device_id: str | None = None,
    device: str | None = None,
    allow_multiple: bool = False,
    motor_mgr: Any = None,
) -> list[Any]:
    """Resolve one or more motors from CLI identifiers using MotorManager."""
    from qtools.pmeas.config import ConfigManager
    from qtools.pmeas.motor_manager import MotorManager

    cfg = ConfigManager.resolve()
    mm = motor_mgr or MotorManager(cfg)

    target: str | None = port or name or device_id or device

    if target is not None:
        try:
            stage = mm.get_motor(target)
            return [stage]
        except (ValueError, ConnectionError):
            pass

    if allow_multiple and mm._available:
        return list(mm._available.values())

    try:
        stage = mm.get_motor()
        return [stage]
    except Exception:
        pass

    dev_status = mm.list_devices()
    connected = dev_status.get("connected", [])
    if not connected:
        print("[ERROR] No motor devices detected. Check USB/power.")
        sys.exit(1)

    if len(connected) == 1:
        return [connected[0]["motor"]]

    if allow_multiple:
        return [item["motor"] for item in connected]

    print("\nMultiple K10CR1 devices detected. Please select one:")
    for i, item in enumerate(connected, 1):
        print(f"  [{i}] {item['name'] or item['id']} (Port: {item['port']}, SN: {item['serial']})")
    print()
    while True:
        try:
            choice = input(f"Select device (1-{len(connected)}): ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(connected):
                    selected = connected[idx - 1]["motor"]
                    print(f"Selected device index {choice} ({connected[idx - 1]['port']})")
                    return [selected]
            print(f"Invalid selection. Please enter a number between 1 and {len(connected)}.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)


def _motor_alias(stage) -> str:
    from qtools.pmeas.config import ConfigManager
    cfg = ConfigManager.resolve()
    serial = str(getattr(stage, "serial", "") or "")
    dev = cfg.get_device(serial) or {}
    return dev.get("optical_path") or dev.get("path") or "A"


def _has_device_flags(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "port", None)
        or getattr(args, "name", None)
        or getattr(args, "id", None)
    )


def _resolve_motor_pair(args: argparse.Namespace, motor_mgr: Any = None):
    """Resolve a pair of motors (Alice / Bob) for two-arm scans using MotorManager."""
    from qtools.pmeas.config import ConfigManager
    from qtools.pmeas.motor_manager import MotorManager

    cfg = ConfigManager.resolve()
    mm = motor_mgr or MotorManager(cfg)

    port = getattr(args, "port", None) or None
    name = getattr(args, "name", None) or None
    did = getattr(args, "id", None) or None
    fix_device = getattr(args, "fix", None)
    sweep_device = getattr(args, "sweep", None)

    stage_a = None
    stage_b = None

    if port or name or did:
        try:
            stage_a = _resolve_motor(port=port, name=name, device_id=did, motor_mgr=mm)[0]
        except Exception:
            pass

    if fix_device and stage_a is None:
        try:
            stage_a = _resolve_motor(device=fix_device, motor_mgr=mm)[0]
        except Exception:
            pass

    if sweep_device:
        try:
            stage_b = _resolve_motor(device=sweep_device, motor_mgr=mm)[0]
        except Exception:
            pass

    if stage_a is None:
        try:
            stage_a = mm.get_motor("alice")
        except Exception:
            pass

    if stage_b is None:
        try:
            stage_b = mm.get_motor("bob")
        except Exception:
            pass

    # Fallback to remaining available motors in mm
    available_motors = list(mm._available.values())
    if stage_a is None and available_motors:
        stage_a = available_motors[0]
    if stage_b is None:
        for m in available_motors:
            if m is not stage_a:
                stage_b = m
                break

    if stage_a is None or stage_b is None:
        raise LookupError(
            "Need two connected motor stages. Check 'pmeas motor list' or register devices."
        )

    name_a = _motor_alias(stage_a)
    name_b = _motor_alias(stage_b)
    return stage_a, stage_b, name_a, name_b


def _add_device_pair_args(p: argparse.ArgumentParser, suppress: bool = False) -> None:
    h = argparse.SUPPRESS if suppress else None
    p.add_argument("--port", default=None,
                   help=h if suppress else "Serial port for the first motor (second is auto-detected)")
    p.add_argument("--name", default=None,
                   help=h if suppress else "Device name for the first motor (second is auto-detected)")
    p.add_argument("--id", default=None,
                   help=h if suppress else "Device index for the first motor (second is auto-detected)")


def _print_available_devices(connected, polmeas_devices):
    for i, (p, label) in enumerate(connected, 1):
        sn = "unknown"
        m = re.search(r"SN=([a-zA-Z0-9]+)", label)
        if m:
            sn = re.sub(r"\D", "", m.group(1))
        pname = "(unconfigured)"
        for d in polmeas_devices:
            if str(d.get("serial") or "") == sn:
                pname = d.get("name", "(unconfigured)")
                break
        print(f"  [{i}] {pname}  (Port: {p}, SN: {sn})")


def _parse_angle(val: str, label: str = "Angle") -> float:
    cleaned = val.lower().strip()
    if cleaned == "zero":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        print(f"[ERROR] {label} must be a number or 'zero'. Got '{val}'")
        sys.exit(1)


def _disconnect_motors(stages):
    for s in stages:
        if s is not None:
            try:
                if hasattr(s, "disconnect"):
                    s.disconnect()
            except Exception:
                pass
