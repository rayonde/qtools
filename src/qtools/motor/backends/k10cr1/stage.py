from __future__ import annotations
import time
import logging
from qtools.motor.backends.motor import register_backend
from qtools.motor.backends.k10cr1.k10cr1 import ThorlabsK10CR1

logger = logging.getLogger(__name__)


VELOCITY_SCALE = 7330128.3  # raw_max_vel per deg/s  (73301283 / 10 deg/s)


@register_backend("k10cr1")
class K10CR1Backend:

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        from qtools.motor.backends.k10cr1.k10cr1 import list_devices as k10cr1_list
        return k10cr1_list()


    """Physical stage controller backend wrapping k10cr1.ThorlabsK10CR1.

    Args:
        port: Serial port path (e.g. 'COM3', '/dev/ttyUSB0').
              If empty string, port auto-discovery is used.
        blocking: Whether move/home commands block until complete.
    """

    def __init__(self, port: str = "", blocking: bool = True, config_mgr=None):
        self.port = port
        self.blocking = blocking
        self._config_mgr = config_mgr
        self._motor: ThorlabsK10CR1 | None = None
        self._model = ""
        self._serial_no = 0
        self.zero_offset = 0.0

    def connect(self) -> bool:
        try:
            logger.info(f"Connecting to K10CR1 on port '{self.port or 'auto'}'...")
            self._motor = ThorlabsK10CR1(port=self.port, blocking=self.blocking)
            # Query identity to confirm communication
            self._model, self._serial_no = self._motor.identity

            # Load zero_offset from config if available
            try:
                from qtools.motor.config import MotorConfigManager
                mgr = self._config_mgr or MotorConfigManager.resolve()
                entry = mgr.get_device(str(self._serial_no))
                if entry is not None:
                    self.zero_offset = float(entry.get("zero_offset", 0.0) or 0.0)
            except Exception as ex:
                logger.warning(f"Could not load zero_offset config: {ex}")

            logger.info(
                f"Connected to K10CR1: model={self._model}, serial={self._serial_no}, zero_offset={self.zero_offset}°"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to connect to K10CR1: {e}")
            self._motor = None
            return False

    def disconnect(self) -> None:
        if self._motor is not None:
            try:
                self._motor.close()
                logger.info("Disconnected K10CR1 (serial=%s).", self._serial_no)
            except Exception as e:
                logger.error(f"Error closing K10CR1 serial port: {e}")
            finally:
                self._motor = None

    def _require_connected(self):
        if self._motor is None:
            raise RuntimeError("K10CR1 stage is not connected. Call connect() first.")

    def get_position(self) -> float:
        """Return current angle in degrees [0, 360), relative to zero_offset."""
        self._require_connected()
        raw_angle = self._motor.angle
        return (raw_angle - self.zero_offset) % 360.0

    def move_to(self, position: float) -> None:
        """Move to absolute angle in degrees, relative to zero_offset."""
        self._require_connected()
        raw_target = (float(position) + self.zero_offset) % 360.0
        self._motor.angle = raw_target

    def move_by(self, displacement: float) -> None:
        """Move by a relative angle in degrees."""
        self._require_connected()
        steps = self._motor.deg2pos(displacement)
        self._motor.move(steps)

    def home(self) -> None:
        """Go to home position (physical home, zero_offset is NOT applied here).

        Runs two passes: first at high velocity to find the limit switch quickly,
        second at 1/100 speed for encoder alignment.
        """
        self._require_connected()
        logger.info("Homing motor (serial=%s)...", self._serial_no)

        # Pass 1: fast home to find limit switch
        self._motor.params_homing = {"home_velocity": 73301283}
        self._motor.home()
        self.wait_move()
        logger.info("Homing pass 1 (fast) — home at %d (encoder pos)", self._motor.position)

        # Pass 2: slow home for precise encoder alignment
        self._motor.params_homing = {"home_velocity": 733013}  # 1/100 speed
        self._motor.home()
        self.wait_move()
        logger.info("Homing pass 2 (slow) — home at %d (encoder pos)", self._motor.position)

    def zero(self) -> None:
        """Move to software zero (0.0°) — the offset-corrected origin."""
        self.move_to(0.0)

    def wait_move(self) -> None:
        """Block until movement is complete."""
        self._require_connected()
        while self._motor.is_moving():
            time.sleep(0.05)

    def stop(self) -> None:
        """Stop motor movement."""
        self._require_connected()
        self._motor.stop(abrupt=False)

    def set_zero_offset(self, offset_deg: float | None = None) -> None:
        """Set the software zero offset.

        If offset_deg is None, the current physical position is set as the zero offset.
        Saves this setting to ``motor_config.yaml``.
        """
        self._require_connected()
        if offset_deg is None:
            self.zero_offset = self._motor.angle
        else:
            self.zero_offset = float(offset_deg) % 360.0

        # Save to config
        try:
            from qtools.motor.config import MotorConfigManager
            mgr = self._config_mgr or MotorConfigManager.resolve()
            serial_str = str(self._serial_no)
            mgr.upsert_device(
                key=serial_str,
                serial=serial_str,
                zero_offset=self.zero_offset,
            )
            mgr.save()
            logger.info(f"Saved zero_offset = {self.zero_offset}° for SN: {serial_str}")
        except Exception as ex:
            logger.error(f"Failed to save zero_offset config: {ex}")

    def get_velocity(self) -> float:
        """Return maximum velocity in degrees per second."""
        self._require_connected()
        raw_max_vel = self._motor.params_velocity["max_velocity"]
        return raw_max_vel / VELOCITY_SCALE

    def set_velocity(self, speed_deg_s: float) -> None:
        """Set maximum velocity in degrees per second."""
        self._require_connected()
        raw_val = int(speed_deg_s * VELOCITY_SCALE)
        if raw_val <= 0:
            raise ValueError("Velocity must be positive.")
        self._motor.params_velocity = {"max_velocity": raw_val}
        logger.info(f"Set motor velocity to {speed_deg_s}°/s (raw={raw_val})")

    def get_stage_name(self) -> str:
        if self._motor is None:
            return f"K10CR1 (port={self.port or 'auto'})"
        return f"K10CR1 {self._model} (serial={self._serial_no})"

