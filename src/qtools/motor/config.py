"""Configuration management for qtools.motor devices.

``MotorConfigManager`` is the single entry point for all config operations.
Use :meth:`MotorConfigManager.resolve` to get an instance.
"""

from __future__ import annotations

import copy
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from qtools.motor._path import get_config_path  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEVICE_FIELDS = {
    "id", "name", "optical_path", "role", "wavelength", "waveplate",
    "port", "zero_offset", "serial",
    "theta_0", "target_angles", "phi_rad", "visibility", "r_squared",
    # polmeas-owned extras tolerated when sharing polmeas_config.yaml
    "bases", "calibration",
}

_DEFAULT_CONFIG: dict = {
    "version": 1,
    "created_at": "",
    "updated_at": "",
    "devices": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* dictionary."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to load %s", path)
        return {}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False,
                           sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        logger.exception("Failed to save %s", path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _normalize_device(info: dict[str, Any], serial: str = "") -> dict[str, Any]:
    """Return a canonical device dict.

    Ensures ``id``, ``serial`` and ``zero_offset`` are present.
    Keeps only keys in ``_DEVICE_FIELDS``.
    """
    entry: dict[str, Any] = {}
    for key, value in info.items():
        if key in _DEVICE_FIELDS:
            entry[key] = value

    sn = str(entry.get("serial") or serial or "")
    if sn:
        entry["serial"] = sn

    # id defaults to optical_path → name → serial
    if not entry.get("id"):
        entry["id"] = (
            entry.get("optical_path")
            or entry.get("name")
            or sn
            or "device"
        )
    entry["id"] = str(entry["id"])

    entry.setdefault("name", entry["id"])
    entry.setdefault("optical_path", "")
    entry.setdefault("role", "")
    entry.setdefault("wavelength", 0)
    entry.setdefault("waveplate", "")
    entry.setdefault("port", "")
    entry.setdefault("zero_offset", float(entry.get("zero_offset", 0.0) or 0.0))
    return entry


def _coerce_devices(devices: Any) -> list[dict[str, Any]]:
    """Normalize *devices* to a list of device entries.

    Accepts the canonical list form, or a legacy ``{serial|id: info}`` dict.
    """
    if isinstance(devices, list):
        out: list[dict[str, Any]] = []
        for i, info in enumerate(devices):
            if not isinstance(info, dict):
                continue
            sn = str(info.get("serial") or "")
            entry = _normalize_device(info, sn)
            if not entry.get("id"):
                entry["id"] = entry.get("name") or sn or str(i + 1)
            out.append(entry)
        return out

    if isinstance(devices, dict):
        out = []
        for key, info in devices.items():
            if not isinstance(info, dict):
                continue
            sn = str(info.get("serial") or key)
            entry = _normalize_device(info, sn)
            # If the dict key looks like a logical id (non-digit), prefer it as id
            if not info.get("id") and not str(key).isdigit():
                entry["id"] = str(key)
            elif not entry.get("id"):
                entry["id"] = entry.get("name") or sn or str(key)
            out.append(entry)
        return out

    return []


def _match_device(dev: dict[str, Any], key: str) -> bool:
    """True if *dev* matches lookup *key* (id / name / optical_path / role / serial)."""
    k = str(key).strip().lower()
    if not k:
        return False
    return k in {
        str(dev.get("id", "")).lower(),
        str(dev.get("name", "")).lower(),
        str(dev.get("optical_path", "")).lower(),
        str(dev.get("role", "")).lower(),
        str(dev.get("serial", "")).lower(),
    }


# ---------------------------------------------------------------------------
# MotorConfigManager
# ---------------------------------------------------------------------------

class MotorConfigManager:
    """Manages ``motor_config.yaml`` configuration lifecycle.

    Both standalone ``motor_config.yaml`` and embedded ``polmeas_config.yaml``
    store devices as a list under the ``devices`` key.
    """

    DEFAULT_FILENAME = "motor_config.yaml"

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            config_path = Path.cwd() / self.DEFAULT_FILENAME
        self.config_path = Path(config_path)
        self._cfg: dict = copy.deepcopy(_DEFAULT_CONFIG)

    @classmethod
    def resolve(cls, config_path: str | Path | None = None) -> "MotorConfigManager":
        """Find existing config or prepare a default path.

        1. If *config_path* is given, use it directly.
        2. Honor ``MOTOR_CONFIG`` / :func:`get_config_path`.
        3. Fall back to ``motor_config/motor_config.yaml``.
        """
        if config_path is not None:
            path = Path(config_path)
        else:
            path = get_config_path()
            if not path.exists():
                alt = Path("motor_config") / cls.DEFAULT_FILENAME
                if alt.exists():
                    path = alt
        mgr = cls(path)
        mgr.load_or_create()
        return mgr

    # ── File I/O ──────────────────────────────────────────────────

    def load(self) -> bool:
        """Load configuration from disk. Returns ``False`` if file does not exist."""
        if not self.config_path.exists():
            return False
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if data and isinstance(data, dict):
                # Prefer explicit devices key; otherwise treat whole file as
                # a bare device map/list only when it has no meta keys.
                if "devices" in data:
                    devices = _coerce_devices(data.get("devices"))
                else:
                    devices = _coerce_devices(data)
                merged = _deep_merge(copy.deepcopy(_DEFAULT_CONFIG), data)
                merged["devices"] = devices
                self._cfg = merged
            return True
        except Exception:
            logger.exception("Failed to load %s", self.config_path)
            return False

    def load_or_create(self) -> bool:
        """Load existing config, or initialize a fresh default one."""
        if self.load():
            return True
        self._cfg = copy.deepcopy(_DEFAULT_CONFIG)
        return False

    def save(self) -> None:
        """Write configuration to disk.

        If the file on disk already has a ``devices`` key (e.g. polmeas_config)
        → replace only that key, keep other top-level keys.
        Otherwise → write the full ``_cfg`` document.
        """
        now = _now()
        self._cfg["updated_at"] = now
        if not self._cfg.get("created_at"):
            self._cfg["created_at"] = now

        # Always persist devices as a list
        self._cfg["devices"] = _coerce_devices(self._cfg.get("devices", []))

        existing = _read_yaml(self.config_path)

        if "devices" in existing:
            existing["devices"] = self._cfg["devices"]
            # refresh timestamps if present
            if "updated_at" in existing or "created_at" in existing:
                existing["updated_at"] = now
                existing.setdefault("created_at", self._cfg.get("created_at", now))
            _atomic_write(self.config_path, existing)
        else:
            _atomic_write(self.config_path, self._cfg)

        logger.info("Saved %s", self.config_path)

    # ── Device access ──────────────────────────────────────────────

    def get_device(self, key: str | int) -> dict[str, Any] | None:
        """Find a device by id, name, optical_path, serial, or 1-based index."""
        devices = self.get_all_devices()
        k = str(key).strip()

        # 1-based index
        if k.isdigit():
            idx = int(k)
            if 1 <= idx <= len(devices):
                return devices[idx - 1]

        for dev in devices:
            if _match_device(dev, k):
                return dev
        return None

    def upsert_device(self, key: str | int = "", **fields: Any) -> dict[str, Any]:
        """Create or update a device entry.

        *key* is matched against id / name / optical_path / serial.
        If no match, a new entry is appended.  ``id`` defaults to
        ``optical_path`` → ``name`` → ``serial`` → *key*.
        """
        devices = self._cfg.setdefault("devices", [])
        if not isinstance(devices, list):
            devices = _coerce_devices(devices)
            self._cfg["devices"] = devices

        k = str(key).strip() if key != "" else ""
        sn = str(fields.get("serial") or "")

        existing: dict[str, Any] | None = None
        if k:
            existing = self.get_device(k)
        if existing is None and sn:
            existing = self.get_device(sn)

        if existing is not None:
            # update in place (same object in the list)
            for f, v in fields.items():
                if f in _DEVICE_FIELDS or f in ("bases", "calibration"):
                    existing[f] = v
            if sn:
                existing["serial"] = sn
            return _normalize_device(existing, existing.get("serial", sn))

        entry = _normalize_device(fields, sn)
        if k and not fields.get("id"):
            # use key as id when it doesn't look like a bare serial-only create
            if not k.isdigit() or not sn:
                entry["id"] = k
        if not entry.get("id"):
            entry["id"] = entry.get("optical_path") or entry.get("name") or sn or "device"
        devices.append(entry)
        return entry

    def get_all_devices(self) -> list[dict[str, Any]]:
        """Return the device list ``[{id, name, ...}, ...]``."""
        devices = self._cfg.get("devices", [])
        if not isinstance(devices, list):
            devices = _coerce_devices(devices)
            self._cfg["devices"] = devices
        return list(devices)

    # ── Interactive naming wizard ──────────────────────────────────

    def prompt_device_info(self, serial_no: int | str) -> dict[str, Any]:
        """Return the device entry for *serial_no*, prompting the user if new.

        Name convention: ``<optical_path><wavelength>_<role>_<waveplate>``
        e.g. ``alice1550_basis_hwp``.  ``id`` defaults to *optical_path*.
        """
        serial_str = str(serial_no)

        existing = self.get_device(serial_str)
        if existing is not None:
            return existing

        try:
            print("\n" + "=" * 60)
            print(f"[=] New device detected (Serial: {serial_no}).")
            print("Please configure this device:")
            print("  Format: <optical_path><wavelength>_<role>_<waveplate>")
            print("  e.g.    alice1550_basis_hwp")
            print("=" * 60)

            while True:
                optical_path = input("1. Optical path (e.g. alice): ").strip().lower()
                if re.match(r"^[a-zA-Z]+$", optical_path):
                    break
                print("   Use alphabetic characters only.")

            while True:
                wl_str = input("2. Wavelength in nm (e.g. 1550): ").strip()
                if wl_str.isdigit():
                    wavelength = int(wl_str)
                    break
                print("   Use digits only.")

            while True:
                role = input("3. Stage role (e.g. basis, state): ").strip().lower()
                if re.match(r"^[a-zA-Z0-9_\-]+$", role):
                    break
                print("   Use alphanumeric, underscore or hyphen.")

            while True:
                waveplate = input("4. Waveplate type (hwp / qwp): ").strip().lower()
                if waveplate in ("hwp", "qwp"):
                    break
                print("   Must be 'hwp' or 'qwp'.")

            name = f"{optical_path}{wavelength}_{role}_{waveplate}"
            print(f"\n[OK] Generated name: {name}")

            entry = self.upsert_device(
                key=optical_path,
                id=optical_path,
                name=name,
                optical_path=optical_path,
                wavelength=wavelength,
                role=role,
                waveplate=waveplate,
                zero_offset=0.0,
                serial=serial_str,
            )
            self.save()
            print(f"[OK] Saved to {self.config_path}\n")
            return entry

        except (KeyboardInterrupt, EOFError):
            print("\n[Naming cancelled — using temporary name.]")
            return _normalize_device({
                "id": f"unknown_{serial_str}",
                "name": f"unknown_{serial_str}",
                "optical_path": "unknown",
                "wavelength": 0,
                "role": "unknown",
                "waveplate": "unknown",
                "zero_offset": 0.0,
            }, serial_str)



