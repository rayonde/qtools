import logging
import os
import yaml
from typing import Any

logger = logging.getLogger(__name__)


class MockServo:
    """Mock implementation for SCS/STS servos for offline testing/simulation."""

    def __init__(self, port: str, baudrate: int, servo_type: str = "scs") -> None:
        self.port = port
        self.baudrate = baudrate
        self._servo_type = servo_type.lower()
        self._default_pos = 512 if self._servo_type == "scs" else 2048
        self._is_open = True
        self.speed = 10.0  # default speed, matches SCServo/STServo
        
        # State storage mapped by servo_id
        self._angles = {}
        self._target_angles = {}
        self._speeds = {}
        self._limits = {}
        self._locked = {}
        self._moving = {}
        
        # Compatibility fields for calibration script
        self.positions = {}
        self._handler = self
        
        # Prepopulate default configured IDs
        self._active_ids = self._get_configured_ids()
        
        # Set default values for prepopulated IDs
        default_max_deg = 300.0 if self._servo_type == "scs" else 360.0
        initial_deg = 150.0 if self._servo_type == "scs" else 180.0
        for sid in self._active_ids:
            self._angles[sid] = initial_deg
            self._target_angles[sid] = initial_deg
            self._speeds[sid] = 10.0
            self._limits[sid] = (0.0, default_max_deg)
            self._locked[sid] = True
            self._moving[sid] = False
            self.positions[sid] = self._angle_to_pos(initial_deg)


    def _get_configured_ids(self) -> list[int]:
        configured_ids = [1, 2, 3]  # Default fallback
        try:
            path = "polarization_config.yaml"
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                ids = []
                for ch in data.get("channels", []):
                    for s in ch.get("servos", []):
                        ids.append(s["servo_id"])
                if ids:
                    configured_ids = list(set(ids))
        except Exception:
            pass
        return sorted(configured_ids)

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def port_handler(self) -> Any:
        return MockPortHandler(self.port)

    def close(self) -> None:
        self._is_open = False

    def list_servos(self, stop_on_empty: bool = True) -> list[int]:
        """Return mock online servo IDs.

        *stop_on_empty* is accepted for API compatibility with hardware backends.
        """
        return self._active_ids

    @property
    def servo_ids(self) -> list[int]:
        return self.list_servos()

    def _angle_to_pos(self, angle: float) -> int:
        max_pos = 1023 if self._servo_type == "scs" else 4095
        max_deg = 300.0 if self._servo_type == "scs" else 360.0
        return int(round(angle * max_pos / max_deg))

    def _pos_to_angle(self, pos: int) -> float:
        max_pos = 1023 if self._servo_type == "scs" else 4095
        max_deg = 300.0 if self._servo_type == "scs" else 360.0
        return round(float(pos) * max_deg / max_pos, 4)

    def ping(self, servo_id: int | list[int] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        if not isinstance(servo_id, list):
            servo_id = [servo_id]
        return all(sid in self._active_ids for sid in servo_id)

    def lock(self, servo_id: int | list[int] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        for sid in servo_id:
            if sid in self._active_ids:
                self._locked[sid] = True
        return True

    def unlock(self, servo_id: int | list[int] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        for sid in servo_id:
            if sid in self._active_ids:
                self._locked[sid] = False
        return True

    def release(self, servo_id: int | list[int] | None = None) -> bool:
        return self.unlock(servo_id)

    def move(self, servo_id: int, position: int, speed: int, acc: int) -> tuple[int, int]:
        """Move mock servo to position (compatibility method)."""
        self.positions[servo_id] = position
        self._target_angles[servo_id] = self._pos_to_angle(position)
        self._angles[servo_id] = self._target_angles[servo_id]
        return 0, 0  # COMM_SUCCESS, error=0

    def set_id(self, old_id: int, new_id: int) -> bool:
        if old_id not in self._active_ids:
            return False
        if new_id in self._active_ids and new_id != old_id:
            return False
            
        # Migrate state
        self._active_ids = [new_id if x == old_id else x for x in self._active_ids]
        self._angles[new_id] = self._angles.pop(old_id, 0.0)
        self._target_angles[new_id] = self._target_angles.pop(old_id, 0.0)
        self._speeds[new_id] = self._speeds.pop(old_id, 10.0)
        self._limits[new_id] = self._limits.pop(old_id, (0.0, 300.0 if self._servo_type == "scs" else 360.0))
        self._locked[new_id] = self._locked.pop(old_id, True)
        self._moving[new_id] = self._moving.pop(old_id, False)
        return True

    def get_limits(self, servo_id: int | list[int] | None = None) -> list[tuple[float, float, int, int]] | None:
        """Return list of (min_angle, max_angle, min_pos, max_pos) per servo."""
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        default_max_deg = 300.0 if self._servo_type == "scs" else 360.0
        result = []
        for sid in servo_id:
            mn, mx = self._limits.get(sid, (0.0, default_max_deg))
            result.append((mn, mx, self._angle_to_pos(mn), self._angle_to_pos(mx)))
        return result

    def set_limits(self, servo_id: int | list[int] | None = None,
                   min_val: float | list[float] | None = None,
                   max_val: float | list[float] | None = None) -> list[bool] | None:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
            
        if min_val is None or max_val is None:
            raise ValueError("min_val and max_val must be specified")
        if not isinstance(min_val, list):
            min_val = [min_val] * len(servo_id)
        if not isinstance(max_val, list):
            max_val = [max_val] * len(servo_id)
            
        results = []
        for sid, mn, mx in zip(servo_id, min_val, max_val):
            if sid in self._active_ids:
                self._limits[sid] = (mn, mx)
                results.append(True)
            else:
                results.append(False)
        return results

    def set_speed(self, servo_id: int | list[int] | None = None,
                  speed: float | list[float] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
            
        if speed is None:
            speed = 10.0
        if not isinstance(speed, list):
            speed = [speed] * len(servo_id)
            
        for sid, spd in zip(servo_id, speed):
            if sid in self._active_ids:
                self._speeds[sid] = float(spd)
                self.speed = float(spd)  # keep instance var in sync
        return True

    def get_speed(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        return [self._speeds.get(sid, 10.0) for sid in servo_id]

    def set_angle(self, servo_id: int | list[int] | None = None,
                  angle: float | list[float] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
            
        if angle is None:
            raise ValueError("angle must be specified")
        elif not isinstance(angle, list):
            angle = [angle] * len(servo_id)
            
        for sid, ang in zip(servo_id, angle):
            if sid in self._active_ids:
                # Clamp to limits if defined
                mn, mx = self._limits.get(sid, (0.0, 300.0 if self._servo_type == "scs" else 360.0))
                clamped_ang = max(mn, min(mx, ang))
                self._target_angles[sid] = clamped_ang
                self._angles[sid] = clamped_ang  # Instant movement in mock
        return True

    def rotate(self, servo_id: int | list[int] | None = None,
               angle: float | list[float] | None = None) -> bool:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
            
        if angle is None:
            raise ValueError("angle must be specified")
        elif not isinstance(angle, list):
            angle = [angle] * len(servo_id)
            
        current_targets = [self._target_angles.get(sid, 0.0) for sid in servo_id]
        new_targets = [curr + delta for curr, delta in zip(current_targets, angle)]
        return self.set_angle(servo_id, new_targets)

    def set_pos(self, servo_id: int | list[int] | None = None,
                position: int | list[int] | None = None) -> list[bool] | None:
        """Set raw encoder position(s)."""
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        if position is None:
            raise ValueError("position must be specified")
        elif not isinstance(position, list):
            position = [position] * len(servo_id)
        for sid, pos in zip(servo_id, position):
            if sid in self._active_ids:
                self.positions[sid] = pos
                self._target_angles[sid] = self._pos_to_angle(pos)
                self._angles[sid] = self._target_angles[sid]
        return [True] * len(servo_id)

    def rotate_pos(self, servo_id: int | list[int] | None = None,
                   delta: int | list[int] | None = None) -> list[bool] | None:
        """Rotate by raw encoder delta."""
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        if delta is None:
            raise ValueError("delta must be specified")
        elif not isinstance(delta, list):
            delta = [delta] * len(servo_id)
        new_positions = [self.positions.get(sid, self._default_pos) + d
                         for sid, d in zip(servo_id, delta)]
        return self.set_pos(servo_id, new_positions)

    # ── Deadband (mock) ───────────────────────────────────────

    def get_deadband(self, servo_id: int) -> dict | None:
        """Mock: return default deadband values."""
        return {"cw": 4, "ccw": 4}

    def set_deadband(self, servo_id: int | list[int] | None = None,
                      cw: int = 2, ccw: int | None = None) -> bool:
        """Mock: simulate setting deadband."""
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        for sid in servo_id:
            logger.info("MockServo ID %d deadband set: CW=%d, CCW=%d", sid, cw, ccw or cw)
        return True

    def get_angle(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        return [self._angles.get(sid, 0.0) for sid in servo_id]

    def get_target_angles(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        return [self._target_angles.get(sid, 0.0) for sid in servo_id]

    def is_moving(self, servo_id: int | list[int] | None = None) -> list[bool] | None:
        if servo_id is None:
            servo_id = self.list_servos()
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        return [self._moving.get(sid, False) for sid in servo_id]

    # Low-level protocol emulation methods for backwards compatibility
    def WritePosEx(self, servo_id: int, position: int, speed: int, acc: int) -> tuple[int, int]:
        self._target_angles[servo_id] = self._pos_to_angle(position)
        self._angles[servo_id] = self._target_angles[servo_id]
        self.positions[servo_id] = position
        return 0, 0  # COMM_SUCCESS, error=0

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]:
        # returns position, comm_result, error
        ang = self._angles.get(servo_id, 0.0)
        pos = self._angle_to_pos(ang)
        return pos, 0, 0

    def ReadPosSpeed(self, servo_id: int) -> tuple[int, int, int, int]:
        # returns pos, speed, comm_result, error
        ang = self._angles.get(servo_id, 0.0)
        pos = self._angle_to_pos(ang)
        spd = int(self._speeds.get(servo_id, 10.0))
        return pos, spd, 0, 0

    def ReadMoving(self, servo_id: int) -> tuple[int, int, int]:
        # returns moving, comm_result, error
        moving = 1 if self._moving.get(servo_id, False) else 0
        return moving, 0, 0

    def write1ByteTxRx(self, servo_id: int, register: int, value: int) -> tuple[int, int]:
        if register == 40 or register == 37:  # Torque enable address
            self._locked[servo_id] = bool(value)
        return 0, 0

    def read1ByteTxRx(self, servo_id: int, register: int) -> tuple[int, int, int]:
        # returns value, comm_result, error
        if register == 40 or register == 37:
            val = 1 if self._locked.get(servo_id, True) else 0
            return val, 0, 0
        return 0, 0, 0

    def write2ByteTxRx(self, servo_id: int, register: int, value: int) -> tuple[int, int]:
        return 0, 0

    def read2ByteTxRx(self, servo_id: int, register: int) -> tuple[int, int, int]:
        return 0, 0, 0

    def LockEprom(self, servo_id: int) -> tuple[int, int]:
        return 0, 0

    def unLockEprom(self, servo_id: int) -> tuple[int, int]:
        return 0, 0


class MockPortHandler:
    def __init__(self, port: str = "MOCK_PORT"):
        self.port_name = port
        self.is_open = True

    def openPort(self) -> bool:
        self.is_open = True
        return True

    def closePort(self) -> None:
        self.is_open = False

    def setBaudRate(self, baudrate: int) -> bool:
        return True


class MockSmsSts:
    def __init__(self):
        self.positions = {}
        self.torque_enable = {}
        self.registers = {}

    def WritePosEx(self, servo_id: int, position: int, speed: int, acc: int) -> tuple[int, int]:
        self.positions[servo_id] = position
        return 0, 0  # COMM_SUCCESS, error=0

    def ReadPosSpeed(self, servo_id: int) -> tuple[int, int, int, int]:
        pos = self.positions.get(servo_id, 512)
        return pos, 0, 0, 0  # pos, speed, result, error

    def ReadMoving(self, servo_id: int) -> tuple[int, int, int]:
        return 0, 0, 0  # moving, result, error

    def write1ByteTxRx(self, servo_id: int, register: int, value: int) -> tuple[int, int]:
        if register == 40:
            self.torque_enable[servo_id] = value
        self.registers[(servo_id, register)] = value
        return 0, 0

    def ping(self, servo_id: int) -> tuple[int, int, int]:
        """Return (model_number, result, error). result==0 is COMM_SUCCESS."""
        try:
            path = "polarization_config.yaml"
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                configured_ids = []
                for ch in data.get("channels", []):
                    for s in ch.get("servos", []):
                        configured_ids.append(s["servo_id"])
                if configured_ids:
                    if servo_id in configured_ids:
                        return 0, 0, 0
                    return 0, 1, 0
        except Exception:
            pass
        if servo_id in (1, 2, 3):
            return 0, 0, 0
        return 0, 1, 0

