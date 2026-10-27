#!/usr/bin/env python3
"""
servo_manager.py
----------------
Servo bus connection management and configuration.

Contains:
  - find_serial_ports / auto_discover: serial port scanning and servo discovery
  - ServoManager: servo connection lifecycle (connect, disconnect, limits, torque)
"""

from __future__ import annotations

import glob
import logging
import time
from typing import Optional
from qtools.pctrl.backends import ServoBackend, COMM_SUCCESS
from qtools.pctrl.config import ConfigManager, os_key

logger = logging.getLogger(__name__)
# ══════════════════════════════════════════════════════════════
# Serial port utilities
# ══════════════════════════════════════════════════════════════

def find_serial_ports() -> list[str]:
    """Return a list of all available USB serial port device names."""
    key = os_key()
    if key == "darwin":
        patterns = [
            "/dev/tty.usbserial-*", "/dev/cu.usbserial-*",
            "/dev/tty.SLAB_USBtoUART*", "/dev/cu.SLAB_USBtoUART*",
            "/dev/tty.usbmodem*", "/dev/cu.usbmodem*",
        ]
        ports = [p for pat in patterns for p in glob.glob(pat)]
    elif key == "linux":
        ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    elif key == "win32":
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
    else:
        ports = []
    return sorted(set(ports))


def auto_discover(
    baudrate: int = 1_000_000,
    servo_type: str = "sts",
) -> Optional[dict]:
    """
    Scan all available serial ports and return the first one with responding servos.

    Returns
    -------
    {'port': str, 'baudrate': int, 'servo_ids': list[int]} or None
    """

    ports = find_serial_ports()
    if not ports:
        logger.warning("No USB serial ports detected. Check connections.")
        return None

    logger.info("Detected serial ports: %s", ports)
    for port in ports:
        logger.info("Scanning %s ...", port)
        try:
            backend = ServoBackend(port=port, baudrate=baudrate, servo_type=servo_type)
            ids = backend.list_servos()
            backend.close()
        except Exception:
            logger.debug("Failed to open %s", port, exc_info=True)
            continue

        if ids:
            logger.info("Found servo IDs on %s: %s", port, ids)
            return {"port": port, "baudrate": baudrate, "servo_ids": ids}
        else:
            logger.debug("No response on %s", port)

    logger.warning("No response from servos on any serial ports.")
    return None


# ══════════════════════════════════════════════════════════════
# Angle-limit helpers (user / EEPROM frame)
# ══════════════════════════════════════════════════════════════

def servo_encoder_for_angle(s: dict, angle_deg: float) -> int:
    """Raw encoder position for a waveplate-relative angle (user frame).

    ``encoder = zero_position + angle / deg_per_step`` — the same conversion
    the ``set`` command and ``move_to_angle`` use.
    """
    zero = int(s.get("zero_position", 512))
    dps = float(s.get("deg_per_step", 0.2933))
    return int(round(zero + angle_deg / dps))


def write_eeprom_limits(ph_sts, s: dict, min_pos: int, max_pos: int) -> tuple[int, int, bool]:
    """Write raw encoder limits ``[min_pos, max_pos]`` to a servo's EEPROM.

    The EEPROM angle-limit registers hold raw encoder positions, so the
    values are written through ``set_limits`` in the servo-physical frame
    (``pos_to_angle``).  Because the physical map and the backend's
    ``angle_to_pos``/``pos_to_angle`` are linear with the same ratio, the
    raw values survive the round-trip exactly: ``angle_to_pos(pos_to_angle(E))
    == E``.

    Values are clamped to ``[0, min(phy_position_range, backend_max)]`` so a
    raw position outside the register range (e.g. the STS 4096-vs-4095
    discrepancy) is never written.  Returns the (possibly clamped) positions
    actually written and whether the EEPROM write succeeded.
    """
    pos_max_conf = int(s.get("phy_position_range", 1023))
    backend_max = ph_sts.angle_to_pos(float(s.get("phy_angle_range", 300.0)))
    clamp_max = min(pos_max_conf, backend_max)
    min_pos = max(0, min(int(min_pos), clamp_max))
    max_pos = max(0, min(int(max_pos), clamp_max))
    if min_pos > max_pos:      # guard against an inverted limit
        min_pos, max_pos = max_pos, min_pos

    results = ph_sts.set_limits(s["servo_id"],
                                ph_sts.pos_to_angle(min_pos),
                                ph_sts.pos_to_angle(max_pos))
    ok = bool(results) and all(results) if isinstance(results, list) else bool(results)
    return min_pos, max_pos, ok


# ══════════════════════════════════════════════════════════════
# ServoManager — singleton device connection manager
# ══════════════════════════════════════════════════════════════
class ServoManager:
    """Manages servo bus connections and configuration."""

    def __init__(self, config_path: Optional[str] = None,
                 port: Optional[str] = None,
                 cfg: Optional[ConfigManager] = None,
                 mock_mode: bool = False):

        if cfg is not None:
            self.cfg = cfg
        else:
            self.cfg = ConfigManager.resolve(config_path)
        if port:
            self.cfg.port = port
        self._mock_mode = mock_mode

        if not self._mock_mode and not self.cfg.port:
            disc = auto_discover(baudrate=self.cfg.baudrate, servo_type=self.cfg.servo_type)
            if disc:
                self.cfg.port = disc["port"]
                self.cfg.baudrate = disc["baudrate"]
            else:
                raise ConnectionError(
                    "No servos discovered. Check connections or enable mock mode (--mock)."
                )

        self._servo_backend = ServoBackend(
            port=self.cfg.port,
            baudrate=self.cfg.baudrate,
            servo_type=self.cfg.servo_type,
            mock=self._mock_mode,
        )

        self.servo_ids = self._servo_backend.list_servos()
        if not self._mock_mode and self.cfg.port:
            self.save_config()

    # ── config ──────────────────────────────────────────────────

    @property
    def config_data(self) -> dict:
        """*Deprecated.*  Use ``cfg`` (the :class:`ConfigManager`) directly.

        This property still works for backward compatibility but will emit
        a ``DeprecationWarning``.
        """
        import warnings
        warnings.warn(
            "ServoManager.config_data is deprecated. Use the ConfigManager API directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.cfg._cfg

    def save_config(self) -> None:
        """Persist current configuration to disk."""
        self.cfg.save()


    # ── mock mode ───────────────────────────────────────────────

    @property
    def mock_mode(self) -> bool:
        return self._mock_mode

    @mock_mode.setter
    def mock_mode(self, enabled: bool) -> None:
        self._mock_mode = enabled

    # ── servo connection ────────────────────────────────────────

    @property
    def backend(self) -> ServoBackend:
        """The connected ServoBackend instance."""
        return self._servo_backend

    def disconnect(self) -> None:
        """Close the servo connection."""
        if self._servo_backend is not None:
            try:
                self._servo_backend.close()
                logger.info("Closed servo connection.")
            except Exception as e:
                logger.warning("Error closing servo connection: %s", e)
            self._servo_backend = None
    
    # ──  group helpers ────────────────────────────────────────
    # returns a list of servo IDs that are in the same group
    # which is the first path segment of the servo name or
    # the path in the config
    def get_group_servo_ids(self, path_name: str) -> list[int]:
        """Return servo IDs for all servos in channels matching *path_name*.

        *path_name* can be a path (``"alice"``), a channel key
        (``"alice1550"``), a servo name, a servo ID, or ``"all"``.
        """
        from qtools.pctrl.config import resolve_target

        try:
            resolution = resolve_target(self.cfg, path_name)
        except ValueError:
            return []

        ids: list[int] = []
        for ch in resolution.channels:
            for s in ch["servos"]:
                if resolution.target_servo_name is not None:
                    if s["name"] == resolution.target_servo_name:
                        ids.append(s["servo_id"])
                else:
                    ids.append(s["servo_id"])
        return ids
    
    def group_limits(self, path_name: str) -> dict[int, tuple[float, float, int, int]]:
        """Return servo_id -> (min_angle, max_angle, min_pos, max_pos) for a group."""

        # retrieve the servo limits from the backend
        servo_ids = self.get_group_servo_ids(path_name)
        res_dict = self.retrive_limits(servo_ids)
        return res_dict

    # ── angle limits helpers ───────────────────────────────────
    
    def retrive_limits(self, servo_ids: int | list[int] | None = None) -> dict[int, tuple[float, float, int, int]]:
        """Read hardware (EEPROM) limits and sync config without corrupting the user frame.

        The EEPROM angle-limit registers hold RAW encoder positions.  ``get_limits``
        also returns their servo-physical angles, which are NOT in the config's
        waveplate-relative frame, so only the raw positions are persisted
        (``min_position``/``max_position``) and ``min_angle``/``max_angle`` are
        recomputed as ``(pos - zero_position) * deg_per_step``.
        """
        if servo_ids is None:
            servo_ids = self._servo_backend.list_servos()
        if isinstance(servo_ids, int):
            servo_ids = [servo_ids]
        limits_list = self._servo_backend.get_limits(servo_ids) or []

        result: dict[int, tuple[float, float, int, int]] = {}
        updated_any = False
        for sid, (phy_min, phy_max, min_pos, max_pos) in zip(servo_ids, limits_list):
            s = self.cfg.servos_by_id.get(sid)
            if s is not None:
                zero = int(s.get("zero_position", 512))
                dps = float(s.get("deg_per_step", 0.2933))
                min_pos, max_pos = int(min_pos), int(max_pos)
                s["min_position"] = min_pos
                s["max_position"] = max_pos
                s["min_angle"] = round((min_pos - zero) * dps, 4)
                s["max_angle"] = round((max_pos - zero) * dps, 4)
                updated_any = True
                result[sid] = (s["min_angle"], s["max_angle"], min_pos, max_pos)
            else:
                result[sid] = (phy_min, phy_max, int(min_pos), int(max_pos))
        if updated_any:
            self.save_config()
        return result


    def lock(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Enable torque lock (servo holds position).
        """
        return self.backend.lock(servo_id)
    
    def unlock(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Disable torque lock (servo rotates freely).
        """
        return self.backend.unlock(servo_id)
    
    def release(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Disable torque lock (servo rotates freely).
        """
        return self.backend.unlock(servo_id)

    # ── calibration / optimization helpers ───────────────────────

    def _resolve_servo(self, name: str) -> dict:
        """Look up servo config dict by name. Raises KeyError if not found."""
        s = self.cfg.get_servo(name)
        if s is None:
            raise KeyError(f"Servo '{name}' not found in config")
        return s

    def move_to_angle(self, name: str, angle_deg: float,
                      speed_deg_s: float = 10.0, acc: int = 20) -> None:
        """Move a servo to a waveplate-relative angle (degrees).

        *angle_deg* is relative to the servo's configured ``zero_position``,
        i.e. in the same frame as ``min_angle`` / ``max_angle``.  The encoder
        target is ``zero_position + angle_deg / deg_per_step``, clamped to
        ``[min_position, max_position]`` so a servo is never commanded past
        its configured software limits.
        """
        s = self._resolve_servo(name)
        sid = s["servo_id"]
        zero = int(s.get("zero_position", 512))
        dps = float(s.get("deg_per_step", 0.2933))
        lo_pos = int(s.get("min_position", 0))
        hi_pos = int(s.get("max_position", 1023))
        speed_steps = self.backend.angle_to_pos(speed_deg_s)
        pos = int(round(zero + angle_deg / dps))
        pos = max(lo_pos, min(hi_pos, pos))
        self.backend.move(sid, pos, speed_steps, acc)

    def get_limits(self, name: str) -> tuple[float, float]:
        """Return (min_angle, max_angle) in servo-native degrees for a servo."""
        s = self._resolve_servo(name)
        limits = self.backend.get_limits(s["servo_id"])
        if limits:
            return limits[0][0], limits[0][1]
        return 0.0, 300.0

    def get_servo_center(self, name: str) -> float:
        """Return the waveplate-0 reference angle in the config frame.

        Angles are defined relative to ``zero_position`` (same frame as
        ``min_angle`` / ``max_angle``), so the center is always 0 degrees.
        """
        return 0.0

    def get_angle(self, name: str) -> float:
        """Return the current angle relative to the configured zero (degrees).

        Equivalent to ``(position - zero_position) * deg_per_step`` — the same
        convention the ``set`` command uses.
        """
        s = self._resolve_servo(name)
        pos, _, result, _ = self.backend.ReadPosSpeed(s["servo_id"])
        if result != COMM_SUCCESS:
            return 0.0
        zero = int(s.get("zero_position", 512))
        dps = float(s.get("deg_per_step", 0.2933))
        return (pos - zero) * dps

    def set_speed(self, name: str, speed_deg_s: float) -> None:
        """Set servo movement speed (deg/s)."""
        s = self._resolve_servo(name)
        speed_steps = self.backend.angle_to_pos(speed_deg_s)
        self.backend.set_speed(s["servo_id"], speed_steps)

    def wait_for_settle(self, names: list[str], timeout: float = 5.0) -> None:
        """Block until all named servos stop moving or timeout expires."""
        ids = [self._resolve_servo(n)["servo_id"] for n in names]
        start = time.time()
        while time.time() - start < timeout:
            all_stopped = True
            for sid in ids:
                moving_list = self.backend.is_moving(sid)
                if moving_list and moving_list[0]:
                    all_stopped = False
                    break
            if all_stopped:
                break
            time.sleep(0.05)



