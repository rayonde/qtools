#!/usr/bin/env python3
"""
config.py
---------
YAML configuration management, servo naming conventions,
and package-level path utilities for the polarization controller.

Naming convention
-----------------
Each servo is named as {path}{wavelength}_{waveplate}_{order}.
The order is the physical slot index (1/2/3) within the 3-servo group,
independent of waveplate type. Example standard configuration:
    alice1550_qwp_1  —  slot 1, quarter-wave plate
    alice1550_hwp_2  —  slot 2, half-wave plate
    alice1550_qwp_3  —  slot 3, quarter-wave plate

Configuration file structure (SCServo-based)
--------------------------------------------
version: 1
exp: "experiment name"
author: ""
created_at: "2025-01-01 00:00:00"
updated_at: "2025-01-01 00:00:00"

connection:
    baudrate: 1000000
    servo_type: sts
    ids: [1, 2, 3]
    os_ports:                    # per-OS overrides (auto-populated)
        darwin:
        port: /dev/tty.usbserial-*
        linux:
        port: /dev/ttyUSB0
        win32:
        port: COM3

channels:
  - path: alice
    wavelength: 1550
    name: "Alice path 1550nm"
    servos:
      - name: alice1550_qwp_1  # auto-generated, do not edit manually
        alias: ""              # user-defined short name, e.g. "alice"
        servo_id: 1
        waveplate: QWP         # QWP or HWP
        order: 1               # physical slot index in beam path (1/2/3)
        retardance: 0.25       # waveplate retardance in units of pi
        loops: 2               # number of full rotations to simulate retardance
        zero_position: 512     # encoder value at reference zero / middle angle
        min_angle: -90.0       # software lower limit relative to zero (degrees)
        max_angle: 90.0        # software upper limit relative to zero (degrees)
        min_position: 205  # encoder for min_angle (= zero + min_angle/dps)
        max_position: 819  # encoder for max_angle (= zero + max_angle/dps)
        phy_angle_range: 300.0      # full physical rotation range (360° for STS)
        phy_position_range: 1023    # full physical encoder range (4096 for STS)
        deg_per_step: 0.2933    # degrees per encoder step (0.0879 for STS)
        speed: 10               # servo movement speed
        # ── per-servo calibration results (populated by calibration sweep) ──
        calibration_file: ""   # path to .npz calibration data file
        cal_offset_deg: 0.0     # calibration fit: angular offset
        cal_scale: 1.0          # calibration fit: scale factor
        a_wobble: 0.0           # calibration fit: wobble amplitude (sine)
        b_wobble: 0.0           # calibration fit: wobble amplitude (cosine)
        fast_axis_angle: 0.0    # measured fast axis angle (deg)
        cal_type: ""            # calibration type: 'single' / 'group'
        lock: false             # torque lock state
        notes: ""               # user notes
"""

from __future__ import annotations

import copy
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import yaml


# ══════════════════════════════════════════════════════════════
# YAML serialization helpers
# ══════════════════════════════════════════════════════════════

class FlowList(list):
    """Serialize as a flow-style (inline) YAML sequence: [a, b, c]."""
    pass


def _flow_list_representer(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)


yaml.add_representer(FlowList, _flow_list_representer)




# ══════════════════════════════════════════════════════════════
# Naming utilities
# ══════════════════════════════════════════════════════════════

def make_servo_name(path: str, wavelength: int | str, waveplate: str, order: int) -> str:
    """
    Generate a canonical servo name.

    Examples
    --------
    >>> make_servo_name("alice", 1550, "QWP", 1)
    'alice1550_qwp_1'
    >>> make_servo_name("alice", 1550, "HWP", 2)
    'alice1550_hwp_2'
    """
    return f"{path.lower()}{wavelength}_{waveplate.lower()}_{order}"


def parse_servo_name(name: str) -> dict:
    """
    Parse a servo name into its constituent fields.
    Format: {path}{wavelength}_{waveplate}_{order}

    Examples
    --------
    >>> parse_servo_name("alice1550_qwp_1")
    {'path': 'alice', 'wavelength': 1550, 'waveplate': 'QWP', 'order': 1}
    """
    parts = name.rsplit("_", 2)
    if len(parts) != 3:
        raise ValueError(
            f"Cannot parse name: {name!r}, "
            f"expected format {{path}}{{wavelength}}_{{waveplate}}_{{order}}"
        )
    path_wave, waveplate, order_str = parts

    i = len(path_wave)
    while i > 0 and path_wave[i - 1].isdigit():
        i -= 1
    if i == len(path_wave):
        raise ValueError(f"No wavelength digits found in name {name!r}.")

    return {
        "path": path_wave[:i],
        "wavelength": int(path_wave[i:]),
        "waveplate": waveplate.upper(),
        "order": int(order_str),
    }


def channel_key_string(path: str, wavelength: int | str) -> str:
    """Return a canonical channel key string, e.g. ``"alice1550"``.

    The format ``{path}{wavelength}`` mirrors the prefix of servo names
    (``alice1550_qwp_1``) so channel keys are naturally composable.
    """
    return f"{path.lower()}{int(wavelength)}"


def parse_channel_key(key_str: str) -> tuple[str, int]:
    """Parse ``"alice1550"`` → ``("alice", 1550)``.

    Splits from the right at the boundary between letters and digits,
    matching the convention used by :func:`parse_servo_name`.
    """
    key_str = key_str.strip().lower()
    if not key_str:
        raise ValueError(f"Empty channel key.")
    i = len(key_str)
    while i > 0 and key_str[i - 1].isdigit():
        i -= 1
    if i == 0:
        raise ValueError(f"No path prefix found in channel key: {key_str!r}.")
    if i == len(key_str):
        raise ValueError(f"No wavelength digits found in channel key: {key_str!r}.")
    return key_str[:i], int(key_str[i:])


# ══════════════════════════════════════════════════════════════
# Target resolution
# ══════════════════════════════════════════════════════════════


@dataclass
class TargetResolution:
    """Structured result of resolving a target string against a configuration."""
    channels: list[dict]                     # resolved channel dicts
    target_servo_name: str | None = None     # specific servo name, if target was a servo
    matched_by: str = ""                     # "all"|"channel_key"|"channel_path"|"servo_name"|"servo_id"
    channel_keys: list[str] = field(default_factory=list)  # "alice1550" style keys for display


def _find_owner_channel(cfg: "ConfigManager", servo_name: str) -> dict | None:
    """Return the channel dict that owns *servo_name*, or None."""
    for ch in cfg.channels:
        if any(s["name"] == servo_name for s in ch["servos"]):
            return ch
    return None


def resolve_target(cfg: "ConfigManager", target: str | int) -> TargetResolution:
    """Unified target resolution for the polarization controller.

    Resolves *target* against *cfg* using the following precedence:

    1. ``"all"`` — every channel in the config
    2. servo name exact match (e.g. ``"alice1550_qwp_1"``)
    3. numeric servo ID (e.g. ``1`` or ``"1"``)
    4. channel key (e.g. ``"alice1550"``, parsed via :func:`parse_channel_key`)
    5. path-only fallback — first channel whose ``path`` matches *target*

    Returns
    -------
    TargetResolution
        Always check ``channels`` — an empty list means the target could not
        be resolved.

    Raises
    ------
    ValueError
        If the target cannot be resolved to any channel or servo.
    """
    # ── "all" ───────────────────────────────────────────────────
    if isinstance(target, str) and target.strip().lower() == "all":
        return TargetResolution(
            channels=list(cfg.channels),
            matched_by="all",
            channel_keys=[channel_key_string(ch["path"], ch["wavelength"])
                          for ch in cfg.channels],
        )

    target_str = str(target).strip()

    # ── servo name ──────────────────────────────────────────────
    servo = cfg.get_servo(target_str)
    if servo is not None:
        owner_ch = _find_owner_channel(cfg, servo["name"])
        return TargetResolution(
            channels=[owner_ch] if owner_ch else [],
            target_servo_name=servo["name"],
            matched_by="servo_name",
            channel_keys=[channel_key_string(owner_ch["path"], owner_ch["wavelength"])]
            if owner_ch else [],
        )

    # ── servo ID (numeric) ──────────────────────────────────────
    try:
        sid = int(target_str)
    except ValueError:
        sid = None

    if sid is not None:
        servo = cfg.find_by_id(sid)
        if servo is not None:
            owner_ch = _find_owner_channel(cfg, servo["name"])
            return TargetResolution(
                channels=[owner_ch] if owner_ch else [],
                target_servo_name=servo["name"],
                matched_by="servo_id",
                channel_keys=[channel_key_string(owner_ch["path"], owner_ch["wavelength"])]
                if owner_ch else [],
            )

    # ── channel key: "{path}{wavelength}" ───────────────────────
    try:
        path, wavelength = parse_channel_key(target_str)
    except ValueError:
        pass
    else:
        ch = cfg.get_channel(path, wavelength)
        if ch is not None:
            return TargetResolution(
                channels=[ch],
                matched_by="channel_key",
                channel_keys=[channel_key_string(path, wavelength)],
            )

    # ── path-only (backward compat) ─────────────────────────────
    target_lower = target_str.lower()
    for ch in cfg.channels:
        if ch["path"].lower() == target_lower:
            return TargetResolution(
                channels=[ch],
                matched_by="channel_path",
                channel_keys=[channel_key_string(ch["path"], ch["wavelength"])],
            )

    raise ValueError(
        f"Target {target_str!r} not recognized as a channel key, channel path, "
        f"servo name, servo ID, or 'all'."
    )


# ══════════════════════════════════════════════════════════════
# SCServo hardware constants (for default values)
# ══════════════════════════════════════════════════════════════

# SCServo position range: 0–1023; middle = 512; full rotation = 300°
_SCS_POS_MAX = 1023
_SCS_DEG_MAX = 300.0
_SCS_ZERO_POS = 512                                          # middle encoder value
_SCS_ZERO_ANGLE = round(_SCS_ZERO_POS / _SCS_POS_MAX * _SCS_DEG_MAX, 4)  # ≈ 150.1466°
_SCS_DEG_PER_STEP = round(_SCS_DEG_MAX / _SCS_POS_MAX, 4)  # ≈ 0.2933°/step

# STServo position range: 0–4095; middle = 2048; full rotation = 360°
_STS_POS_MAX = 4096
_STS_DEG_MAX = 360.0
_STS_ZERO_POS = 2048
_STS_DEG_PER_STEP = round(_STS_DEG_MAX / _STS_POS_MAX, 4)  # ≈ 0.0879

# Per-type lookup — computes min/max_position from zero + angle/dps
def _build_servo_type_defaults(zero_pos: int, deg_max: float, pos_max: int,
                               deg_per_step: float) -> dict:
    min_angle = -90.0
    max_angle = 90.0
    min_pos = int(round(zero_pos + min_angle / deg_per_step))
    max_pos = int(round(zero_pos + max_angle / deg_per_step))
    return {
        "zero_position": zero_pos,
        "phy_zero_angle": round(zero_pos / pos_max * deg_max, 4),
        "min_angle": min_angle,
        "max_angle": max_angle,
        "min_position": min_pos,
        "max_position": max_pos,
        "phy_angle_range": deg_max,
        "phy_position_range": pos_max,
        "deg_per_step": deg_per_step,
    }

_SERVO_TYPE_DEFAULTS: dict[str, dict] = {
    "scs": _build_servo_type_defaults(_SCS_ZERO_POS, _SCS_DEG_MAX, _SCS_POS_MAX, _SCS_DEG_PER_STEP),
    "sts": _build_servo_type_defaults(_STS_ZERO_POS, _STS_DEG_MAX, _STS_POS_MAX, _STS_DEG_PER_STEP),
}


# ══════════════════════════════════════════════════════════════
# TDC backend resolution
# ══════════════════════════════════════════════════════════════

# The tdc package registers its S15 TDC1 backend under the name selected by
# ``tdc.backends.s15_tdc1.config.DEFAULT_TDC1_BACKEND`` (currently
# ``exp_s15_tdc1``).  Configs written before that switch still say
# ``s15_tdc1``, which is no longer registered.  ``_DEFAULT_TDC1_BACKEND`` is
# the fallback template value; ``resolve_tdc_backend`` repairs stale names at
# read time.
_DEFAULT_TDC1_BACKEND = "exp_s15_tdc1"


def resolve_tdc_backend(configured: str) -> str:
    """Return a TDC backend name that the tdc package actually registers.

    If *configured* is not in the tdc registry, fall back to the package's
    current default S15 TDC1 backend; otherwise return *configured* unchanged
    so an explicitly-chosen (e.g. ``s15_tdc2``) backend is preserved.
    """
    if not configured:
        return _DEFAULT_TDC1_BACKEND
    try:
        from qtools import tdc  # noqa: F401 — importing tdc registers all backends
        from qtools.tdc.connection import list_backends
        registered = list_backends()
    except Exception:
        return configured
    if configured in registered:
        return configured
    try:
        from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
        fallback = DEFAULT_TDC1_BACKEND
    except Exception:
        fallback = _DEFAULT_TDC1_BACKEND
    if fallback in registered:
        return fallback
    return configured


# ══════════════════════════════════════════════════════════════
# Default configuration templates
# ══════════════════════════════════════════════════════════════

_DEFAULT_CONFIG: dict = {
    "version": 1,
    "exp": "",
    "author": "",
    "created_at": "",
    "updated_at": "",
    "connection": {
        "baudrate": 1_000_000,
        "servo_type": "scs",
        "ids": [],
        "os_ports": {
            "darwin": {"port": ""},
            "linux":  {"port": ""},
            "win32":  {"port": ""},
        },
    },
    "detectors": {
        "tdc": {
            "backend": _DEFAULT_TDC1_BACKEND,
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
        "powermeter": {
            "backend": "s15",
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
    },
    "channels": [],
}

_DEFAULT_SERVO: dict = {
    "name": "",
    "alias": "",
    "servo_id": -1,
    "waveplate": "",          # QWP / HWP
    "order": 1,               # physical slot index (1/2/3)
    "retardance": 0.25,       # retardance in units of pi
    "loops": 2,               # number of full rotations for retardance
    # ── hardware (per-type) ──
    "zero_position": _SCS_ZERO_POS,          # 512 (2048 for STS)
    "phy_zero_angle": _SCS_ZERO_ANGLE,       # ~150.1466° (180.0° for STS)
    "min_position": 0,                       # encoder for min_angle — per-type
    "max_position": _SCS_POS_MAX,            # encoder for max_angle — per-type
    "phy_angle_range": _SCS_DEG_MAX,         # 300.0° (360.0° for STS)
    "phy_position_range": _SCS_POS_MAX,      # 1023 (4096 for STS)
    "deg_per_step": _SCS_DEG_PER_STEP,       # ~0.2933 (0.0879 for STS)
    # ── software limits (relative to zero) ──
    "min_angle": -90.0,                      # (degrees)
    "max_angle": 90.0,                       # (degrees)
    # ── other ──
    "speed": 10,
    # ── calibration ──
    "calibration_file": "",         # path to .npz calibration data file
    "cal_offset_deg": 0.0,          # (degrees)
    "cal_scale": 1.0,               # (dimensionless)
    "a_wobble": 0.0,                # (dimensionless)
    "b_wobble": 0.0,                # (dimensionless)
    "fast_axis_angle": 0.0,         # (degrees)
    "cal_type": "",                 # 'single' / 'group'
    "lock": False,
    "notes": "",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def os_key() -> str:
    """Return a normalized OS identifier string."""
    plat = sys.platform
    if plat == "darwin":
        return "darwin"
    elif plat.startswith("linux"):
        return "linux"
    elif plat == "win32":
        return "win32"
    return "unknown"


# ══════════════════════════════════════════════════════════════
# ConfigManager
# ══════════════════════════════════════════════════════════════

class ConfigManager:
    """
    YAML configuration manager for the polarization controller.

    Channels are uniquely identified by (path, wavelength), e.g. ("alice", 1550).
    Each channel contains one or more servos, with names auto-generated as
        {path}{wavelength}_{waveplate}_{order}

    All servo defaults follow SCServo hardware parameters (0–1023 position range,
    300° full range, 512 zero position).
    """

    def __init__(self, config_path: str | Path = "pctrl_config.yaml"):
        self.config_path = Path(config_path)
        self._cfg: dict = copy.deepcopy(_DEFAULT_CONFIG)

    @classmethod
    def resolve(cls, config_path: str | Path | None = None) -> "ConfigManager":
        """
        Find existing config or create a new template.

        1. If *config_path* is given, use it directly.
        2. Otherwise search current directory, then ``pctrl_config/`` subdirectory.
        3. If nothing is found, create ``pctrl_config/pctrl_config.yaml`` as a
           fresh template (the directory is created if it does not exist).

        Returns a :class:`ConfigManager` with the config already loaded.
        """
        if config_path is not None:
            path = Path(config_path)
        else:
            path = Path("pctrl_config.yaml")
            if not path.exists():
                alt = Path("pctrl_config") / "pctrl_config.yaml"
                if alt.exists():
                    path = alt
                else:
                    pctrl_dir = Path("pctrl_config")
                    pctrl_dir.mkdir(exist_ok=True)
                    path = pctrl_dir / "pctrl_config.yaml"

        mgr = cls(path)
        mgr.load()
        return mgr

    # ── File I/O ──────────────────────────────────────────────

    def load(self) -> bool:
        """Load configuration from disk. Returns False if file does not exist."""
        if not self.config_path.exists():
            return False
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            self._cfg = _deep_merge(_DEFAULT_CONFIG, data)
        return True

    def save(self) -> None:
        """Write YAML file (auto-updates timestamps)."""
        now = _now()
        self._cfg["updated_at"] = now
        if not self._cfg.get("created_at"):
            self._cfg["created_at"] = now
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(
                self._cfg, f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
            )
        print(f"Configuration saved -> {self.config_path}")

    # ── Connection properties ─────────────────────────────────

    def _os_port(self) -> dict:
        """Return the per-OS port dict, creating it if needed."""
        conn = self._cfg["connection"]
        return conn.setdefault("os_ports", {}).setdefault(os_key(), {})

    @property
    def port(self) -> str:
        """Active serial port.

        Prefer the per-OS override under ``connection.os_ports.<os>.port``.
        Fall back to the legacy flat ``connection.port`` key used by many
        configs and tests.
        """
        p = self._os_port().get("port", "") or ""
        if p:
            return p
        return self._cfg.get("connection", {}).get("port", "") or ""

    @port.setter
    def port(self, v: str) -> None:
        self._os_port()["port"] = v
        # Keep legacy flat key in sync for tools that still read it
        self._cfg.setdefault("connection", {})["port"] = v

    @property
    def baudrate(self) -> int:
        return self._cfg["connection"]["baudrate"]

    @baudrate.setter
    def baudrate(self, v: int) -> None:
        self._cfg["connection"]["baudrate"] = v

    @property
    def servo_type(self) -> str:
        return self._cfg["connection"]["servo_type"]

    @servo_type.setter
    def servo_type(self, v: str) -> None:
        self._cfg["connection"]["servo_type"] = v

    @property
    def servo_ids(self) -> list[int]:
        """Last discovered servo IDs stored in config."""
        return self._cfg["connection"].get("ids", [])

    @servo_ids.setter
    def servo_ids(self, ids: list[int]) -> None:
        self._cfg["connection"]["ids"] = list(ids)

    # ── Detector config (TDC / powermeter) ─────────────────────

    def _device_os_port(self, device_key: str) -> dict:
        """Return the per-OS port dict for *device_key*, creating it if needed."""
        dev = self._cfg.setdefault("detectors", {}).setdefault(device_key, {})
        return dev.setdefault("os_ports", {}).setdefault(os_key(), {})

    @property
    def tdc_config(self) -> dict:
        """Active TDC ``{port, backend}``, backend resolved against the tdc registry."""
        dev = self._cfg.setdefault("detectors", {}).setdefault("tdc", {})
        port = self._device_os_port("tdc").get("port", "")
        return {"port": port, "backend": resolve_tdc_backend(dev.get("backend", _DEFAULT_TDC1_BACKEND))}

    @property
    def pm_config(self) -> dict:
        """Active powermeter ``{port, backend}``."""
        dev = self._cfg.setdefault("detectors", {}).setdefault("powermeter", {})
        port = self._device_os_port("powermeter").get("port", "")
        return {"port": port, "backend": dev.get("backend", "s15")}

    def set_device_port(self, device_key: str, port: str) -> None:
        """Set the OS-resolved port for *device_key* in the main config."""
        self._device_os_port(device_key)["port"] = port

    @property
    def servos_by_id(self) -> dict[int, dict]:
        """All servo config dicts keyed by servo_id (mutable references)."""
        result = {}
        for ch in self._cfg["channels"]:
            for s in ch["servos"]:
                result[s["servo_id"]] = s
        return result

    # ── Channel management ────────────────────────────────────

    @property
    def channels(self) -> list[dict]:
        return self._cfg["channels"]

    def _channel_key(self, path: str, wavelength: int | str) -> tuple[str, int]:
        return path.lower(), int(wavelength)

    def get_channel(self, path: str, wavelength: int | str) -> Optional[dict]:
        """Get channel by (path, wavelength). Returns None if not found."""
        key = self._channel_key(path, wavelength)
        return next(
            (c for c in self._cfg["channels"]
             if (c["path"].lower(), int(c["wavelength"])) == key),
            None,
        )

# ── File I/O ──────────────────────────────────────────────
    def add_channel(
        self,
        path: str,
        wavelength: int | str,
        name: str = "",
    ) -> dict:
        """Add a new empty channel. Raises ValueError if it already exists."""
        if self.get_channel(path, wavelength) is not None:
            raise ValueError(f"Channel {path}{wavelength} already exists")
        channel: dict = {
            "path": path.lower(),
            "wavelength": int(wavelength),
            "name": name,
            "servos": [],
        }
        self._cfg["channels"].append(channel)
        self._cfg["channels"].sort(key=lambda c: (c["path"], int(c["wavelength"])))
        return channel

    def remove_channel(self, path: str, wavelength: int | str) -> bool:
        """Remove channel. Returns True if removed."""
        key = self._channel_key(path, wavelength)
        before = len(self._cfg["channels"])
        self._cfg["channels"] = [
            c for c in self._cfg["channels"]
            if (c["path"].lower(), int(c["wavelength"])) != key
        ]
        return len(self._cfg["channels"]) < before

    def resolve_target(self, target: str | int) -> TargetResolution:
        """Resolve a target string against this configuration.

        Convenience wrapper for :func:`resolve_target`.
        """
        return resolve_target(self, target)

    # ── Servo management ──────────────────────────────────────

    def _servo_type_defaults(self) -> dict:
        """Return per-type hardware defaults for the configured servo type."""
        st = self.servo_type.lower()
        return _SERVO_TYPE_DEFAULTS.get(st, _SERVO_TYPE_DEFAULTS["scs"])

    def add_servo(
        self,
        path: str,
        wavelength: int | str,
        waveplate: str,
        order: int,
        servo_id: int,
        alias: str = "",
        zero_position: int | None = None,
        deg_per_step: float | None = None,
        retardance: float = 0.25,
        loops: int = 2,
        calibration_file: str = "",
        notes: str = "",
    ) -> dict:
        """
        Add a servo to the specified channel. Auto-creates channel if needed.

        Parameters
        ----------
        path        : optical path name, e.g. 'alice'
        wavelength  : operating wavelength in nm, e.g. 1550
        waveplate   : waveplate type 'QWP' or 'HWP'
        order       : physical slot index within the group (1/2/3)
        servo_id    : servo hardware ID
        alias       : user-defined short name
        zero_position : encoder value at reference angle (default: type-dependent)
        deg_per_step  : degrees per encoder step (default: type-dependent)
        retardance  : waveplate retardance in units of pi
        loops       : number of full rotations to simulate retardance
        calibration_file : path to the npz calibration file
        """
        waveplate = waveplate.upper()
        if waveplate not in ("QWP", "HWP"):
            raise ValueError(f"waveplate must be 'QWP' or 'HWP', got: {waveplate!r}")

        ch = self.get_channel(path, wavelength)
        if ch is None:
            ch = self.add_channel(path, wavelength)

        name = make_servo_name(path, wavelength, waveplate, order)
        if any(s["name"] == name for s in ch["servos"]):
            raise ValueError(f"Servo {name!r} already exists in channel {path}{wavelength}")

        td = self._servo_type_defaults()
        if zero_position is None:
            zero_position = td["zero_position"]
        if deg_per_step is None:
            deg_per_step = td["deg_per_step"]

        phy_zero_angle = round(zero_position / td["phy_position_range"] * td["phy_angle_range"], 4)

        servo: dict = copy.deepcopy(_DEFAULT_SERVO)
        # Apply per-type hardware defaults (overriding the SCS-based template)
        servo.update({k: td[k] for k in (
            "zero_position", "phy_zero_angle", "min_angle", "max_angle",
            "min_position", "max_position", "phy_angle_range", "phy_position_range",
            "deg_per_step",
        )})
        servo.update({
            "name": name,
            "alias": alias,
            "servo_id": servo_id,
            "waveplate": waveplate,
            "order": order,
            "retardance": retardance,
            "loops": loops,
            "zero_position": zero_position,
            "phy_zero_angle": phy_zero_angle,
            "deg_per_step": deg_per_step,
            "calibration_file": calibration_file,
            "notes": notes,
        })
        ch["servos"].append(servo)
        ch["servos"].sort(key=lambda s: s["order"])
        return servo

    def get_servo(self, name: str) -> Optional[dict]:
        """Get servo config dict by name (mutable reference)."""
        for ch in self._cfg["channels"]:
            for s in ch["servos"]:
                if s["name"] == name:
                    return s
        return None

    def find_by_id(self, servo_id: int) -> Optional[dict]:
        """Reverse-lookup servo config by hardware ID."""
        for ch in self._cfg["channels"]:
            for s in ch["servos"]:
                if s["servo_id"] == servo_id:
                    return s
        return None

    def update_servo(self, name: str, **kwargs) -> None:
        """
        Update any fields of a servo config by name.

        Examples
        --------
        cfg.update_servo("alice1550_qwp_1", zero_position=480, speed=20)
        cfg.update_servo("alice1550_qwp_1", lock=True)
        """
        s = self.get_servo(name)
        if s is None:
            raise KeyError(f"Servo {name!r} does not exist")
        # Recompute phy_zero_angle if zero_position is updated
        if "zero_position" in kwargs and "phy_zero_angle" not in kwargs:
            td = self._servo_type_defaults()
            kwargs["phy_zero_angle"] = round(
                kwargs["zero_position"] / td["phy_position_range"] * td["phy_angle_range"], 4
            )
        # Recompute min_position/max_position when the fields they depend on
        # change, unless they are explicitly provided.
        if any(k in kwargs for k in ("zero_position", "min_angle", "max_angle", "deg_per_step")):
            zero = kwargs.get("zero_position", s.get("zero_position", 512))
            dps = kwargs.get("deg_per_step", s.get("deg_per_step", 0.2933))
            if "min_position" not in kwargs:
                min_ang = kwargs.get("min_angle", s.get("min_angle", -90.0))
                kwargs["min_position"] = int(round(zero + min_ang / dps))
            if "max_position" not in kwargs:
                max_ang = kwargs.get("max_angle", s.get("max_angle", 90.0))
                kwargs["max_position"] = int(round(zero + max_ang / dps))
        s.update(kwargs)

    def all_servos(self) -> list[dict]:
        """Return all servo config dicts across all channels."""
        return [s for ch in self._cfg["channels"] for s in ch["servos"]]

    def all_servo_ids(self) -> list[int]:
        """Return all assigned servo hardware IDs."""
        return [s["servo_id"] for s in self.all_servos() if s["servo_id"] >= 0]

    def save_servo_ids(self, ids: list[int]) -> None:
        """Persist the last discovered servo IDs into connection.ids."""
        self.servo_ids = ids

    # ── Summary display ───────────────────────────────────────

    def summary(self) -> None:
        print("\n" + "=" * 60)
        print("  Polarization Controller — Configuration Summary")
        print("=" * 60)
        conn = self._cfg["connection"]
        print(f"  Serial Port  : {conn.get('port') or '(not set)'}")
        print(f"  Baud Rate    : {conn.get('baudrate')}")
        print(f"  Servo Type   : {self.servo_type}")
        print(f"  Cached IDs   : {self.servo_ids or '(none)'}")
        if self._cfg.get("exp"):
            print(f"  Experiment   : {self._cfg['exp']}")
        if self._cfg.get("author"):
            print(f"  Author       : {self._cfg['author']}")
        print(f"  Channels     : {len(self.channels)}")
        for ch in self.channels:
            tag = f"{ch['path']}{ch['wavelength']}nm"
            print(f"\n  +-- {tag}  {ch.get('name', '')}")
            for s in ch["servos"]:
                sid = s["servo_id"]
                alias = f" ({s['alias']})" if s.get("alias") else ""
                print(
                    f"  |  {s['name']:<24}{alias}"
                    f"  ID={str(sid) if sid >= 0 else 'unassigned':<4}"
                    f"  zero={s['zero_position']:<5}"
                    f"  {s['deg_per_step']:.4f} deg/step"
                )
            print("  +" + "-" * 44)
        print()


# ══════════════════════════════════════════════════════════════
# CalConfigManager — calibration-specific configuration
# ══════════════════════════════════════════════════════════════

_CAL_DEFAULT_CONFIG: dict = {
    "version": 1,
    "created_at": "",
    "updated_at": "",
    "devices": {
        "tdc": {
            "backend": _DEFAULT_TDC1_BACKEND,
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
        "powermeter": {
            "backend": "s15",
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
    },
    "measurement": {
        "duration": 0.2,
        "samples": 1,
        "channels": [],
        "expert": False,
        "raw_data_dir": "pctrl_calibration_data",
    },
    "calibration": {
        "step_deg": 5.0,
        "speed_deg_s": 10.0,
        "basis": "h",
        "fast": False,
        "ml": False,
    },
}

_CAL_FILENAME = "pctrl_calibration_config.yaml"


class CalConfigManager:
    """Configuration for calibration runs (``pctrl_calibration_config.yaml``).

    Manages measurement device parameters and calibration-specific settings
    independently from the main servo config.
    """

    def __init__(self, config_path: str | Path | None = None):
        if config_path is not None:
            self.config_path = Path(config_path)
        else:
            self.config_path = Path(_CAL_FILENAME)
            if not self.config_path.exists():
                alt = Path("pctrl_config") / _CAL_FILENAME
                if alt.exists():
                    self.config_path = alt
                else:
                    pctrl_dir = Path("pctrl_config")
                    pctrl_dir.mkdir(exist_ok=True)
                    self.config_path = pctrl_dir / _CAL_FILENAME
        self._cfg = copy.deepcopy(_CAL_DEFAULT_CONFIG)
        self.load()

    def load(self) -> bool:
        if not self.config_path.exists():
            return False
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            self._cfg = _deep_merge(_CAL_DEFAULT_CONFIG, data)
        return True

    def save(self) -> None:
        now = _now()
        self._cfg["updated_at"] = now
        if not self._cfg.get("created_at"):
            self._cfg["created_at"] = now
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._cfg, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, indent=2)

    # -- measurement helpers ------------------------------------

    @property
    def meas_params(self) -> dict:
        return self._cfg["measurement"]

    def _device_os_port(self, device_key: str) -> dict:
        """Return the per-OS port dict for *device_key*, creating it if needed."""
        dev = self._cfg["devices"].setdefault(device_key, {})
        return dev.setdefault("os_ports", {}).setdefault(os_key(), {})

    @property
    def tdc_config(self) -> dict:
        dev = self._cfg["devices"]["tdc"]
        port = self._device_os_port("tdc").get("port", "")
        return {"port": port, "backend": resolve_tdc_backend(dev.get("backend", _DEFAULT_TDC1_BACKEND))}

    @property
    def pm_config(self) -> dict:
        dev = self._cfg["devices"]["powermeter"]
        port = self._device_os_port("powermeter").get("port", "")
        return {"port": port, "backend": dev.get("backend", "s15")}

    def set_device_port(self, device_key: str, port: str) -> None:
        """Set the OS-resolved port for *device_key*."""
        self._device_os_port(device_key)["port"] = port

    # -- calibration params -------------------------------------

    @property
    def cal_params(self) -> dict:
        return self._cfg["calibration"]


# ══════════════════════════════════════════════════════════════
# OptConfigManager — optimization-specific configuration
# ══════════════════════════════════════════════════════════════

_OPT_DEFAULT_CONFIG: dict = {
    "version": 1,
    "created_at": "",
    "updated_at": "",
    "devices": {
        "tdc": {
            "backend": _DEFAULT_TDC1_BACKEND,
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
        "powermeter": {
            "backend": "s15",
            "os_ports": {
                "darwin": {"port": ""},
                "linux":  {"port": ""},
                "win32":  {"port": ""},
            },
        },
    },
    "measurement": {
        "duration": 0.2,
        "samples": 1,
        "channels": [],
        "expert": False,
        "raw_data_dir": "pctrl_optimization_data",
    },
    "optimization": {
        "method": "Nelder-Mead",
        "maxiter": 100,
        "tol": 1e-4,
        "step_size_deg": 15.0,
        "speed_deg_s": 10.0,
        "settle_time": 0.1,
        "duration": 0.2,
        "samples": 1,
    },
}

_OPT_FILENAME = "pctrl_optimization_config.yaml"


class OptConfigManager:
    """Configuration for optimization runs (``pctrl_optimization_config.yaml``).

    Manages measurement device parameters and optimization-specific settings
    independently from the main servo config.
    """

    def __init__(self, config_path: str | Path | None = None):
        if config_path is not None:
            self.config_path = Path(config_path)
        else:
            self.config_path = Path(_OPT_FILENAME)
            if not self.config_path.exists():
                alt = Path("pctrl_config") / _OPT_FILENAME
                if alt.exists():
                    self.config_path = alt
                else:
                    pctrl_dir = Path("pctrl_config")
                    pctrl_dir.mkdir(exist_ok=True)
                    self.config_path = pctrl_dir / _OPT_FILENAME
        self._cfg = copy.deepcopy(_OPT_DEFAULT_CONFIG)
        self.load()

    def load(self) -> bool:
        if not self.config_path.exists():
            return False
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            self._cfg = _deep_merge(_OPT_DEFAULT_CONFIG, data)
        return True

    def save(self) -> None:
        now = _now()
        self._cfg["updated_at"] = now
        if not self._cfg.get("created_at"):
            self._cfg["created_at"] = now
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._cfg, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, indent=2)

    # -- measurement helpers ------------------------------------

    @property
    def meas_params(self) -> dict:
        return self._cfg["measurement"]

    def _device_os_port(self, device_key: str) -> dict:
        """Return the per-OS port dict for *device_key*, creating it if needed."""
        dev = self._cfg["devices"].setdefault(device_key, {})
        return dev.setdefault("os_ports", {}).setdefault(os_key(), {})

    @property
    def tdc_config(self) -> dict:
        dev = self._cfg["devices"]["tdc"]
        port = self._device_os_port("tdc").get("port", "")
        return {"port": port, "backend": resolve_tdc_backend(dev.get("backend", _DEFAULT_TDC1_BACKEND))}

    @property
    def pm_config(self) -> dict:
        dev = self._cfg["devices"]["powermeter"]
        port = self._device_os_port("powermeter").get("port", "")
        return {"port": port, "backend": dev.get("backend", "s15")}

    def set_device_port(self, device_key: str, port: str) -> None:
        """Set the OS-resolved port for *device_key*."""
        self._device_os_port(device_key)["port"] = port

    # -- optimization params ------------------------------------

    @property
    def opt_params(self) -> dict:
        return self._cfg["optimization"]
