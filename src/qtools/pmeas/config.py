"""Configuration manager for polarization measurement.

``polmeas_config.yaml`` is the single source of truth for:
- Experiment metadata (exp, author)
- Registered motor devices (``devices: [{id, name, ...}, ...]`` — same shape
  as :mod:`qtools.motor`, so the motor package can read/write this file via
  ``MOTOR_CONFIG``)
- Dual detector connection settings (tdc and powermeter)
- Task scan parameters (calibration, scan, chsh)
- Device-keyed calibration history (synchronised with registered devices)
"""

from __future__ import annotations

import copy
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

logger = logging.getLogger(__name__)

# Make YAML safe_dump handle numpy scalars and arrays
_yaml_np_types = (
    (np.floating, lambda d, o: d.represent_float(float(o))),
    (np.integer, lambda d, o: d.represent_int(int(o))),
    (np.bool_, lambda d, o: d.represent_bool(bool(o))),
    (np.ndarray, lambda d, o: d.represent_list(o.tolist())),
)
for _typ, _fn in _yaml_np_types:
    yaml.SafeDumper.add_representer(_typ, _fn)


_DEFAULT_DEVICE_TEMPLATE: dict = {
    "id": 1,
    "name": "stage_1",
    "optical_path": "",
    "role": "hwp",
    "wavelength": 1550,
    "waveplate": "hwp",
    "port": "",
    "serial": "",
    "zero_offset": 0.0,
    "calibration": {
        "fast_axis": 0.0,
        "theta_0": 0.0,
        "zero_offset": 0.0,
        "retardance": 180.0,
        "visibility": 1.0,
        "phi_rad": 0.0,
        "r_squared": 1.0,
        "cal_file": "",
    },
    "bases": {"H": 0.0, "V": 45.0, "D": 22.5, "A": 67.5},
}


def _create_device_entry(dev_id: int, **kwargs) -> dict:
    """Create a fresh device dict from _DEFAULT_DEVICE_TEMPLATE with overrides."""
    entry = copy.deepcopy(_DEFAULT_DEVICE_TEMPLATE)
    entry["id"] = dev_id
    name = kwargs.get("name") or kwargs.get("optical_path") or f"stage_{dev_id}"
    entry["name"] = str(name)
    entry["optical_path"] = str(kwargs.get("optical_path") or name)
    for k, v in kwargs.items():
        if v is not None:
            entry[k] = v
    wp = str(entry.get("waveplate") or entry.get("role") or "").lower()
    entry["calibration"]["retardance"] = 180.0 if wp != "qwp" else 90.0
    return entry


# ═══════════════════════════════════════════════════════════════════════════
# Default config skeleton
# ═══════════════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG: dict = {
    "version": 1,
    "exp": "",
    "author": "",
    "created_at": "",
    "updated_at": "",

    # ── Registered motor devices (list of entries with integer id) ──
    "devices": [
        _create_device_entry(1, name="alice", optical_path="alice"),
        _create_device_entry(2, name="bob", optical_path="bob"),
    ],

    # ── Detector / instrument connections ─────
    "detectors": {
        "tdc": {"backend": "", "port": ""},
        "powermeter": {"backend": "", "port": ""},
    },

    # ── Task defaults: Calibration ────────────
    "calibration": {
        "detector": "powermeter",
        "meas_type": "power",
        "start_angle": 0.0,
        "end_angle": 360.0,
        "step_angle": 5.0,
        "duration": 1.0,
        "repetitions": 100,
        "wavelength_nm": 1560.0,
        "auto_range": True,
        "verify": True,
    },

    # ── Task defaults: Pairs Scan ──────
    "scan": {
        "detector": "tdc",
        "meas_type": "pairs",
        "thresvolt": 0.6,
        "channels": [1, 2],
        "ch_start": 0,
        "ch_stop": 1,
        "bin_offset": 0,
        "peak": 0,
        "loffset": 0,
        "roffset": 0,
        "window_start": None,
        "window_stop": None,
        "delay_bin": 0,
        "bins": 500,
        "unit": "ns",
        "ts_bin": 1.0,
        "start_angle": 0.0,
        "end_angle": 180.0,
        "step_angle": 5.0,
        "duration": 1.0,
        "repetitions": 5,
        "subtract_accidentals": True,
        "bases": ["H", "V", "D", "A"],
    },

    # ── Task defaults: CHSH Bell Scan ─────────
    "chsh": {
        "detector": "tdc",
        "meas_type": "pairs",
        "thresvolt": 0.6,
        "channels": [1, 2],
        "ch_start": 0,
        "ch_stop": 1,
        "bin_offset": 0,
        "peak": 0,
        "loffset": 0,
        "roffset": 0,
        "window_start": None,
        "window_stop": None,
        "delay_bin": 0,
        "bins": 500,
        "unit": "ns",
        "ts_bin": 1.0,
        "start_offset": 0.0,
        "end_offset": 90.0,
        "step_offset": 3.0,
        "duration": 1.0,
        "repetitions": 5,
        "subtract_accidentals": True,
    },

    # ── Calibration results (keyed by device id) ────────────
    "calibration_results": {},
}

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dictionary."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# ConfigManager
# ═══════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """Manages ``polmeas_config.yaml`` configuration lifecycle."""

    DEFAULT_FILENAME = "polmeas_config.yaml"

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            config_path = Path.cwd() / self.DEFAULT_FILENAME
        self.config_path = Path(config_path)
        self._cfg: dict = copy.deepcopy(_DEFAULT_CONFIG)
        self._archive_dir: Path | None = None

    @classmethod
    def resolve(cls, config_path: str | Path | None = None) -> ConfigManager:
        """Find an existing config file or return a manager ready to create a default."""
        if config_path is not None:
            path = Path(config_path)
        else:
            path = Path(cls.DEFAULT_FILENAME)
            if not path.exists():
                alt = Path("polmeas_config") / cls.DEFAULT_FILENAME
                if alt.exists():
                    path = alt
                else:
                    alt_dir = Path("polmeas_config")
                    if alt_dir.exists() and alt_dir.is_dir():
                        path = alt_dir / cls.DEFAULT_FILENAME

        mgr = cls(path)
        mgr.load_or_create()
        return mgr

    # ── Dotted key accessors ─────────────────────────────────────────────

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Read a nested config value via dotted path string."""
        node: Any = self._cfg
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return copy.deepcopy(node) if isinstance(node, (dict, list)) else node

    def set_value(self, dotted_key: str, value: Any) -> None:
        """Set a nested config value via dotted path string."""
        parts = dotted_key.split(".")
        node = self._cfg
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    # ── Properties & Archive ────────────────────────────────────────────

    @property
    def archive_dir(self) -> Path:
        if self._archive_dir is None:
            self._archive_dir = self.config_path.parent / ".polmeas_archive"
            self._archive_dir.mkdir(exist_ok=True)
        return self._archive_dir

    def archive(self, tag: str = "") -> Optional[Path]:
        """Explicitly create a timestamped backup copy of the configuration file."""
        if not self.config_path.exists():
            return None
        self.archive_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        tag_suffix = f"_{tag}" if tag else ""
        archive_name = f"polmeas_config_{ts}{tag_suffix}.yaml"
        archive_path = self.archive_dir / archive_name
        try:
            shutil.copy2(self.config_path, archive_path)
            logger.info("Archived config -> %s", archive_path)
            return archive_path
        except Exception:
            logger.exception("Failed to archive config to %s", archive_path)
            return None

    def list_archives(self) -> list[Path]:
        if not self.archive_dir.exists():
            return []
        return sorted(
            self.archive_dir.glob("polmeas_config_*.yaml"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def load_archive(self, name: str) -> Optional[dict]:
        stem = name.replace("polmeas_config_", "").replace(".yaml", "")
        candidates = [
            self.archive_dir / f"polmeas_config_{stem}.yaml",
            self.archive_dir / name,
            self.archive_dir / f"{name}.yaml",
        ]
        for path in candidates:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        return yaml.safe_load(fh)
                except Exception:
                    return None
        return None

    def restore_archive(self, name: str) -> bool:
        data = self.load_archive(name)
        if data is None or not isinstance(data, dict):
            return False
        self._cfg = _deep_merge(copy.deepcopy(_DEFAULT_CONFIG), data)
        self.save()
        return True

    # ── File I/O ────────────────────────────────────────────────────────

    def load(self) -> bool:
        """Load config from disk."""
        if not self.config_path.exists():
            return False
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if data and isinstance(data, dict):
                self._cfg = _deep_merge(copy.deepcopy(_DEFAULT_CONFIG), data)
            return True
        except Exception:
            logger.exception("Failed to load %s", self.config_path)
            return False

    def load_or_create(self) -> bool:
        """Load existing config, or create a fresh default one."""
        if self.load():
            return True
        self._cfg = copy.deepcopy(_DEFAULT_CONFIG)
        return False

    def save(self) -> None:
        """Write configuration to disk."""
        now = _now()
        self._cfg["updated_at"] = now
        if not self._cfg.get("created_at"):
            self._cfg["created_at"] = now

        # Ensure devices is normalized
        _ = self.devices

        out = {k: v for k, v in self._cfg.items() if v not in ({}, [], "", None)}
        # Always keep structural keys even when empty
        for keep in ("version", "created_at", "updated_at", "exp", "author",
                     "devices", "detectors", "calibration_results"):
            if keep in self._cfg:
                out[keep] = self._cfg[keep]

        with open(self.config_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                out,
                fh,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
            )

    # ── Devices management ──────────────────────────────────────────────

    @property
    def devices(self) -> list[dict]:
        """Return the device list ``[{id, name, ...}, ...]``."""
        devs = self._cfg.setdefault("devices", [])
        if not isinstance(devs, list):
            devs = []
            self._cfg["devices"] = devs
        return devs

    def upsert_device(self, key: str | int = "", path: str = "", **kwargs) -> dict:
        """Create or update a device by id / name / serial / optical_path / port.

        Matching priority (first match wins):
          1. *key*     — id, name, serial, port, or optical_path
          2. *serial*  — from kwargs
          3. *port*    — from kwargs
          4. *optical_path* — from kwargs (or *path*)
        """
        devices = self.devices
        dev = self.get_device(key) if key != "" else None

        if dev is None and kwargs.get("serial"):
            dev = self.get_device(kwargs["serial"])
        if dev is None and kwargs.get("port"):
            dev = self.get_device(kwargs["port"])
        if dev is None and path:
            dev = self.get_device(path)
        if dev is None and kwargs.get("optical_path"):
            dev = self.get_device(kwargs["optical_path"])

        if path:
            kwargs["optical_path"] = path

        if dev is not None:
            # Merge into existing device — preserve existing id
            # Remove 'id' from kwargs to avoid overwriting with a string (e.g. 'alice')
            kwargs.pop("id", None)
            for k, v in kwargs.items():
                if v is not None and v != "":
                    dev[k] = v
            return dev

        raw_id = kwargs.get("id")
        try:
            dev_id = int(raw_id) if raw_id is not None else len(devices) + 1
        except (ValueError, TypeError):
            dev_id = len(devices) + 1

        new_dev = _create_device_entry(dev_id, **kwargs)
        devices.append(new_dev)
        return new_dev

    def register_device(self, serial: str | int, **kwargs) -> dict:
        """Register or update a device by serial number."""
        sn = str(serial)
        return self.upsert_device(key=sn, serial=sn, **kwargs)

    def get_device(self, key: str | int) -> Optional[dict]:
        """Find a unique device by id (int), name, serial, or port (fallback to optical_path).

        Matching priority (best match first):
          1. serial  — exact match (strongest signal)
          2. port    — exact match (strong physical tie)
          3. name    — exact match
          4. integer id — exact match
          5. optical_path — fallback
        """
        if key is None or key == "":
            return None

        devices = self.devices
        k_str = str(key).strip().lower()

        # 1. Serial — strongest unique identifier
        for dev in devices:
            if str(dev.get("serial", "")).lower() == k_str and k_str:
                return dev

        # 2. Port — strong physical tie
        for dev in devices:
            if str(dev.get("port", "")).lower() == k_str and k_str:
                return dev

        # 3. Name — exact match
        for dev in devices:
            if str(dev.get("name", "")).lower() == k_str:
                return dev

        # 4. Integer id
        if str(key).isdigit() or isinstance(key, int):
            idx = int(key)
            for dev in devices:
                if dev.get("id") == idx:
                    return dev

        # 5. Fallback — id as string
        for dev in devices:
            if str(dev.get("id", "")).lower() == k_str:
                return dev

        # 6. Fallback — optical_path (return first only if unique)
        path_matches = [
            dev for dev in devices
            if str(dev.get("optical_path", "")).lower() == k_str
        ]
        if len(path_matches) == 1:
            return path_matches[0]
        if path_matches:
            # Prefer one with a real port/serial over a bare entry
            for dev in path_matches:
                if dev.get("port") or dev.get("serial"):
                    return dev
            return path_matches[0]

        return None

    def get_devices_by_group(self, group: str) -> list[dict]:
        """Return all devices belonging to an optical_path group (e.g. 'alice', 'bob')."""
        g = group.strip().lower()
        return [
            dev for dev in self.devices
            if str(dev.get("optical_path", "")).lower() == g
        ]

    def get_all_devices(self) -> list[dict]:
        """Return all devices."""
        return list(self.devices)

    # ── Calibrations management ─────────────────────────────────────────

    @property
    def calibration_results(self) -> dict:
        return self._cfg.setdefault("calibration_results", {})

    def add_calibration(self, device_key: str, data: dict) -> None:
        """Add/update a calibration record keyed by device id, and sync to devices.

        If a record already exists for *device_key*, *data* is merged into it;
        otherwise a new record is created.
        """
        existing = self.calibration_results.get(device_key, {})
        entry = copy.deepcopy(existing) if existing else {}
        for k, v in data.items():
            if v is not None and v != "":
                entry[k] = v
        entry.setdefault("timestamp", _now())
        entry.setdefault("fast_axis", entry.get("theta_0", entry.get("zero_offset", 0.0)))

        self.calibration_results[device_key] = entry

        dev = self.get_device(device_key)
        if dev:
            # Sync top-level device fields
            # NOTE: zero_offset is intentionally NOT synced — it is a manual motor
            # parameter that should never be overwritten by calibration fits.
            for k in ("bases",):
                if k in entry:
                    dev[k] = entry[k]
            # Only update the structured calibration sub-dict with its own keys;
            # never write top-level cal_entry fields (scan, timestamp, bases, …) into it.
            _CAL_SUBKEYS = {"fast_axis", "theta_0", "zero_offset", "retardance", "visibility",
                            "phi_rad", "r_squared", "cal_file"}
            cal_update = {k: v for k, v in entry.items() if k in _CAL_SUBKEYS}
            # Derive retardance from phi_rad when present
            if "phi_rad" in entry and "retardance" not in cal_update:
                cal_update["retardance"] = float(np.degrees(entry["phi_rad"]))
            dev.setdefault("calibration", {}).update(cal_update)

    def get_calibration(self, device_key: str = "latest") -> Optional[dict]:
        cals = self.calibration_results
        if not cals:
            return None
        if device_key in cals:
            return cals[device_key]
        if device_key == "latest":
            max_key = max(cals.keys(), key=lambda k: (cals[k].get("timestamp", ""), k))
            return cals[max_key]
        dev = self.get_device(device_key)
        if dev:
            for k in (str(dev.get("id")), dev.get("name"), dev.get("serial")):
                if k and k in cals:
                    return cals[k]
        return None

    def latest_zero_offset(self, device_key: str | None = None) -> Optional[float]:
        cal = self.get_calibration(device_key or "latest")
        return cal.get("theta_0") if cal else None

    def latest_bases(self, device_key: str | None = None) -> Optional[dict[str, float]]:
        cal = self.get_calibration(device_key or "latest")
        return cal.get("bases") if cal else None

    # ── Detector Auto-Scan ───────────────────────────────────────────────

    def scan_detectors(self, save: bool = True) -> dict[str, dict]:
        """Auto-detect connected PowerMeter and TDC devices, update detectors config, and optionally save."""
        detectors = self._cfg.setdefault("detectors", {})

        # 1. Scan PowerMeter
        pm_info = {"backend": "", "port": ""}
        try:
            from qtools.powermeter.cli import auto_detect_connected_device as pm_auto_detect
            addr, backend = pm_auto_detect()
            if addr and backend:
                pm_info = {"backend": backend, "port": addr}
        except Exception as ex:
            logger.debug("PowerMeter auto-scan skipped/failed: %s", ex)

        # 2. Scan TDC
        tdc_info = {"backend": "", "port": ""}
        try:
            from qtools.tdc.connection import discover_all as tdc_discover_all
            tdc_devs = tdc_discover_all(method="usb", timeout=1.0)
            if not tdc_devs:
                tdc_devs = tdc_discover_all(method="ethernet", timeout=1.0)
            if tdc_devs:
                dev = tdc_devs[0]
                tdc_info = {
                    "backend": getattr(dev, "backend_name", "") or "",
                    "port": getattr(dev, "device_path", "") or "",
                }
        except Exception as ex:
            logger.debug("TDC auto-scan skipped/failed: %s", ex)

        detectors["powermeter"] = pm_info
        detectors["tdc"] = tdc_info

        if save:
            self.save()
        return detectors

    # ── Summary ─────────────────────────────────────────────────────────

    def summary(self) -> None:
        cfg = self._cfg
        print("\n" + "=" * 60)
        print("  Polarization Measurement — Config Summary")
        print("=" * 60)

        exp = cfg.get("exp", "")
        author = cfg.get("author", "")
        print(f"  Experiment: {exp or '(unnamed)'}" + (f"  |  Author: {author}" if author else ""))
        print(f"  Updated:    {cfg.get('updated_at', '')}")

        devices = self.devices
        print(f"\n  Devices ({len(devices)}):")
        if not devices:
            print("    (none)")
        else:
            for dev in devices:
                cal = dev.get("calibration") or {}
                fa = cal.get("fast_axis")
                fa_s = f"fast_axis={fa:.4f} deg" if isinstance(fa, (int, float)) else ""
                cal_file = cal.get("cal_file", "")
                bases = dev.get("bases", {})
                bases_s = "  ".join(f"{b}={a:.4f}" for b, a in bases.items()) if bases else ""
                parts = [p for p in [
                    dev.get("optical_path", "?"),
                    dev.get("name", "?"),
                    f"role={dev.get('role','?')}",
                    f"wp={dev.get('waveplate','?')}",
                    f"wl={dev.get('wavelength','?')}nm",
                    fa_s,
                    f"cal={cal_file}" if cal_file else "",
                ] if p]
                print(f"    [{dev.get('optical_path','?')}]  " + "  ".join(parts))
                if bases_s:
                    print(f"      bases: {bases_s}")

        det = cfg.get("detectors", {})
        tdc = det.get("tdc", {})
        pm = det.get("powermeter", {})
        print(f"\n  Detectors:")
        print(f"    TDC:        {tdc.get('backend','?') or '(none)'}  @  {tdc.get('port','(none)')}")
        print(f"    Powermeter: {pm.get('backend','?') or '(none)'}  @  {pm.get('port','(none)')}")
        print("=" * 60 + "\n")
