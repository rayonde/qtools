import time
import logging
from typing import Any

from .stservo_sdk import PortHandler, sts, COMM_SUCCESS, STS_ID, STS_TORQUE_ENABLE, STS_GOAL_SPEED_L, STS_GOAL_POSITION_L, STS_MIN_ANGLE_LIMIT_L, STS_MAX_ANGLE_LIMIT_L, STS_CW_DEAD, STS_CCW_DEAD

logger = logging.getLogger(__name__)

# Constants
STS_ID_ADDRESS = STS_ID
STS_POS_ENCODE = 4095
STS_DEGREE_MAX = 360.0
DEFAULT_SPEED = 10
TIMEOUT = 5


class STServo:
    """Concrete hardware implementation for STS-series servos using sts."""

    def __init__(self, port: str, baudrate: int) -> None:
        self._port_handler = PortHandler(port)
        if not self._port_handler.openPort():
            raise ConnectionError(f"Failed to open serial port {port}")
        
        if not self._port_handler.setBaudRate(baudrate):
            self._port_handler.closePort()
            raise ConnectionError(f"Failed to set baud rate {baudrate} on {port}")
        
        self._handler = sts(self._port_handler)
        self.speed = DEFAULT_SPEED

    def __getattr__(self, name: str) -> Any:
        # Delegate to self._handler
        if self._handler is not None:
            return getattr(self._handler, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @property
    def servo_ids(self) -> list[int]:
        return self.list_servos()

    @property
    def is_open(self) -> bool:
        if self._port_handler is None:
            return False
        return getattr(self._port_handler, "is_open", True)

    @property
    def port_handler(self) -> Any:
        return self._port_handler

    def close(self) -> None:
        """Close connection."""
        if self._port_handler is not None:
            try:
                self._port_handler.closePort()
            except Exception:
                pass
            self._port_handler = None
            self._handler = None

    def _angle_to_pos(self, angle: float) -> int:
        max_pos = STS_POS_ENCODE 
        max_deg = STS_DEGREE_MAX
        return int(round(angle * max_pos / max_deg))

    def _pos_to_angle(self, pos: int) -> float:
        max_pos = STS_POS_ENCODE 
        max_deg = STS_DEGREE_MAX
        return round(float(pos) * max_deg / max_pos, 4)

    def list_servos(self, stop_on_empty: bool = True) -> list[int]:
        """Scan the bus for responding servo IDs."""
        import qtools.pctrl.backends.stservo_sdk.STservo_sdk.port_handler as ph_mod
        old_latency = ph_mod.LATENCY_TIMER
        ph_mod.LATENCY_TIMER = 5  # Reduce latency timeout to 5ms
        
        found = []
        consecutive_empty = 0
        try:
            for sid in range(1, 254):
                _, res, _ = self._handler.ping(sid)
                if res == COMM_SUCCESS:
                    found.append(sid)
                    consecutive_empty = 0
                else:
                    if found:
                        consecutive_empty += 1
                        if stop_on_empty and consecutive_empty >= 5:
                            break
        finally:
            ph_mod.LATENCY_TIMER = old_latency
        return found

    def ping(self, servo_id: int | list[int] | None = None) -> bool:
        """Ping a servo or multiple servos. Returns True if all are online."""
        if servo_id is None:
            servo_id = self.list_servos()
        if not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        for sid in servo_id:
            _, res, _ = self._handler.ping(sid)
            if res != COMM_SUCCESS:
                return False
        return True

    def set_id(self, old_id: int, new_id: int) -> bool:
        """Renew ID of the servo."""
        # unlock EPROM
        sts_comm_result, sts_error = self._handler.unLockEprom(old_id)
        if sts_comm_result != COMM_SUCCESS:
            logger.error("%s", self._handler.getTxRxResult(sts_comm_result))
            return False
        elif sts_error != 0:
            logger.error("%s", self._handler.getRxPacketError(sts_error))
            return False

        # renew ID 
        sts_comm_result, sts_error = self._handler.write1ByteTxRx(old_id, STS_ID_ADDRESS, new_id)
        if sts_comm_result != COMM_SUCCESS:
            logger.error("%s", self._handler.getTxRxResult(sts_comm_result))
            return False
        else:
            # lock EPROM after successfully changing ID
            self._handler.LockEprom(new_id)
            logger.info("Succeeded to change the Servo ID: %s -> %s", old_id, new_id)
        
        if sts_error != 0:
            logger.error("%s", self._handler.getRxPacketError(sts_error))
            return False
        return True

    def lock(self, servo_id: int | list[int] | None = None) -> bool:
        """Lock the motor torque of servo(s) (enable torque)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]

        success = True
        for sid in servo_id:
            res, err = self._handler.write1ByteTxRx(sid, STS_TORQUE_ENABLE, 1)
            if res != COMM_SUCCESS:
                logger.error("Servo %d torque lock failed: %s", sid, self._handler.getTxRxResult(res))
                success = False
            elif err != 0:
                logger.error("Servo %d torque lock error: %s", sid, self._handler.getRxPacketError(err))
                success = False
            else:
                logger.info("Servo ID %d torque is enabled", sid)
        return success

    def unlock(self, servo_id: int | list[int] | None = None) -> bool:
        """Release the motor torque of servo(s) (disable torque)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]

        success = True
        for sid in servo_id:
            res, err = self._handler.write1ByteTxRx(sid, STS_TORQUE_ENABLE, 0)
            if res != COMM_SUCCESS:
                logger.error("Servo %d torque unlock failed: %s", sid, self._handler.getTxRxResult(res))
                success = False
            elif err != 0:
                logger.error("Servo %d torque unlock error: %s", sid, self._handler.getRxPacketError(err))
                success = False
            else:
                logger.info("Servo ID %d torque is unlocked", sid)
        return success
    
    def release(self, servo_id: int | list[int] | None = None) -> bool:
        """Alias for unlock."""
        return self.unlock(servo_id)

    # ── Deadband ───────────────────────────────────────────────

    def get_deadband(self, servo_id: int) -> dict | None:
        """Read CW/CCW deadband values from a servo's EEPROM.

        Returns ``{"cw": int, "ccw": int}`` or ``None`` on comm failure.
        """
        cw, res_cw, err_cw = self._handler.read1ByteTxRx(servo_id, STS_CW_DEAD)
        ccw, res_ccw, err_ccw = self._handler.read1ByteTxRx(servo_id, STS_CCW_DEAD)
        if res_cw != COMM_SUCCESS or res_ccw != COMM_SUCCESS:
            logger.error(
                "Servo %d deadband read failed: cw_res=%s, ccw_res=%s",
                servo_id,
                self._handler.getTxRxResult(res_cw),
                self._handler.getTxRxResult(res_ccw),
            )
            return None
        if err_cw != 0 or err_ccw != 0:
            logger.error(
                "Servo %d deadband read error: cw_err=%s, ccw_err=%s",
                servo_id,
                self._handler.getRxPacketError(err_cw),
                self._handler.getRxPacketError(err_ccw),
            )
            return None
        logger.info("Servo ID %d deadband: CW=%d, CCW=%d", servo_id, cw, ccw)
        return {"cw": cw, "ccw": ccw}

    def set_deadband(self, servo_id: int | list[int] | None = None,
                      cw: int = 2, ccw: int | None = None) -> bool:
        """Set CW/CCW deadband on servo(s) and persist to EEPROM.

        Parameters
        ----------
        servo_id : int or list[int] or None
            Target servo ID(s).  ``None`` = all servos on the bus.
        cw : int
            Clockwise deadband value (default 2).
        ccw : int or None
            Counter-clockwise deadband value (defaults to *cw*).
        """
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        if ccw is None:
            ccw = cw

        results: list[bool] = []
        for sid in servo_id:
            ok = True
            # Unlock EEPROM
            res, err = self._handler.unLockEprom(sid)
            if res != COMM_SUCCESS:
                logger.error("Servo %d EEPROM unlock failed: %s", sid, self._handler.getTxRxResult(res))
                results.append(False)
                continue
            time.sleep(0.05)

            # Write CW deadband
            res, err = self._handler.write1ByteTxRx(sid, STS_CW_DEAD, cw)
            if res != COMM_SUCCESS:
                logger.error("Servo %d CW deadband write failed: %s", sid, self._handler.getTxRxResult(res))
                ok = False
            elif err != 0:
                logger.error("Servo %d CW deadband write error: %s", sid, self._handler.getRxPacketError(err))
                ok = False

            # Write CCW deadband
            res, err = self._handler.write1ByteTxRx(sid, STS_CCW_DEAD, ccw)
            if res != COMM_SUCCESS:
                logger.error("Servo %d CCW deadband write failed: %s", sid, self._handler.getTxRxResult(res))
                ok = False
            elif err != 0:
                logger.error("Servo %d CCW deadband write error: %s", sid, self._handler.getRxPacketError(err))
                ok = False

            # Lock EEPROM
            self._handler.LockEprom(sid)
            time.sleep(0.05)

            results.append(ok)
            if ok:
                logger.info("Servo ID %d deadband set: CW=%d, CCW=%d", sid, cw, ccw)
        return all(results) if results else False

    def move(self, servo_id: int, position: int, speed: int, acc: int) -> tuple[int, int]:
        """Move the servo to a position with speed and acc (for compatibility)."""
        res, err = self._handler.WritePosEx(servo_id, position, speed, acc)
        return res, err

    def set_speed(self, servo_id: int | list[int] | None = None, speed: float | list[float] | None = None) -> bool:
        """Set the speed of the servo(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        if speed is None:
            speed = self.speed
        elif not isinstance(speed, list):
            speed = [speed]
        
        success = True
        for sid, spd in zip(servo_id, speed):
            # sts_toscs converts host speed to scs/sts speed representation
            res, err = self._handler.write2ByteTxRx(sid, STS_GOAL_SPEED_L, self._handler.sts_toscs(spd, 15))
            if res != COMM_SUCCESS:
                logger.error("Servo %d speed set failed: %s", sid, self._handler.getTxRxResult(res))
                success = False
            elif err != 0:
                logger.error("Servo %d speed set error: %s", sid, self._handler.getRxPacketError(err))
                success = False
            else:
                logger.info("Servo ID %d speed is set to %d", sid, spd)
                self.speed = spd  # keep instance var in sync for set_angle()
        return success

    def get_speed(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the speed of the servo(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        speeds = []
        for sid in servo_id:
            val, res, err = self._handler.read2ByteTxRx(sid, STS_GOAL_SPEED_L)
            if res != COMM_SUCCESS:
                logger.error("Servo %d speed get failed: %s", sid, self._handler.getTxRxResult(res))
                speeds.append(0.0)
            elif err != 0:
                logger.error("Servo %d speed get error: %s", sid, self._handler.getRxPacketError(err))
                speeds.append(0.0)
            else:
                real_spd = self._handler.sts_tohost(val, 15)
                logger.info("Servo ID %d speed is %d", sid, real_spd)
                speeds.append(float(real_spd))
        return speeds

    def set_angle(self, servo_id: int | list[int] | None = None, angle: float | list[float] | None = None) -> bool:
        """Set the angle of the servo(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        if angle is None:
            raise ValueError("angle must be specified")
        elif not isinstance(angle, list):
            angle = [angle] * len(servo_id)
        
        # 1. Single servo
        if len(servo_id) == 1:
            sid, ang = servo_id[0], angle[0]
            pos = self._angle_to_pos(ang)
            res, err = self._handler.WritePosEx(sid, pos, self.speed, 0)
            if res != COMM_SUCCESS:
                logger.error("Servo %d angle set failed: %s", sid, self._handler.getTxRxResult(res))
                return False
            elif err != 0:
                logger.error("Servo %d angle set error: %s", sid, self._handler.getRxPacketError(err))
                return False
            logger.info("Servo ID %d angle is set to %f", sid, ang)
            return True
            
        # 2. Multiple servos
        else:
            self._handler.groupSyncWrite.clearParam()
            for sid, ang in zip(servo_id, angle):
                pos = self._angle_to_pos(ang)
                self._handler.SyncWritePosEx(sid, pos, self.speed, 0)
            
            res = self._handler.groupSyncWrite.txPacket()
            if res != COMM_SUCCESS:
                logger.error("SyncWritePosEx failed: %s", self._handler.getTxRxResult(res))
                return False
            logger.info("SyncWritePosEx succeeded for servos %s to angles %s", servo_id, angle)
            return True

    def rotate(self, servo_id: int | list[int] | None = None, angle: float | list[float] | None = None) -> bool:
        """Rotate the servo(s) relatively by adding angle as a delta."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        if angle is None:
            raise ValueError("angle must be specified")
        elif not isinstance(angle, list):
            angle = [angle] * len(servo_id)

        current_targets = self.get_target_angles(servo_id)
        if not current_targets:
            return False
        
        new_targets = [curr + delta for curr, delta in zip(current_targets, angle)]
        return self.set_angle(servo_id, new_targets)

    def set_pos(self, servo_id: int | list[int] | None = None,
                position: int | list[int] | None = None) -> list[bool] | None:
        """Set raw encoder position(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        if position is None:
            raise ValueError("position must be specified")
        elif not isinstance(position, list):
            position = [position] * len(servo_id)
        results = []
        for sid, pos in zip(servo_id, position):
            res, err = self._handler.WritePosEx(sid, pos, self.speed, 0)
            results.append(res == COMM_SUCCESS and err == 0)
        return results

    def rotate_pos(self, servo_id: int | list[int] | None = None,
                   delta: int | list[int] | None = None) -> list[bool] | None:
        """Rotate by raw encoder delta."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        if delta is None:
            raise ValueError("delta must be specified")
        elif not isinstance(delta, list):
            delta = [delta] * len(servo_id)
        new_positions = []
        for sid, d in zip(servo_id, delta):
            pos, _, _ = self._handler.ReadPos(sid)
            new_positions.append(pos + d)
        return self.set_pos(servo_id, new_positions)

    def get_angle(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the current angle of the servo(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        angles = []
        for sid in servo_id:
            val, res, err = self._handler.ReadPos(sid)
            if res != COMM_SUCCESS:
                logger.error("Servo %d position get failed: %s", sid, self._handler.getTxRxResult(res))
                angles.append(0.0)
            elif err != 0:
                logger.error("Servo %d position get error: %s", sid, self._handler.getRxPacketError(err))
                angles.append(0.0)
            else:
                real_ang = self._pos_to_angle(val)
                logger.info("Servo ID %d position is %f", sid, real_ang)
                angles.append(real_ang)
        return angles

    def get_target_angles(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the target angles of the servo(s)."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        angles = []
        for sid in servo_id:
            val, res, err = self._handler.read2ByteTxRx(sid, STS_GOAL_POSITION_L)
            if res != COMM_SUCCESS:
                logger.error("Servo %d target angle get failed: %s", sid, self._handler.getTxRxResult(res))
                angles.append(0.0)
            elif err != 0:
                logger.error("Servo %d target angle get error: %s", sid, self._handler.getRxPacketError(err))
                angles.append(0.0)
            else:
                real_ang = self._pos_to_angle(val)
                logger.info("Servo ID %d target angle is %f", sid, real_ang)
                angles.append(real_ang)
        return angles

    def get_limits(self, servo_id: int | list[int] | None = None) -> list[tuple[float, float, int, int]] | None:
        """Get the hardware min and max angle/position limits.

        Returns list of (min_angle, max_angle, min_pos, max_pos) per servo.
        """
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        limits = []
        for sid in servo_id:
            min_val, res1, err1 = self._handler.read2ByteTxRx(sid, STS_MIN_ANGLE_LIMIT_L)
            max_val, res2, err2 = self._handler.read2ByteTxRx(sid, STS_MAX_ANGLE_LIMIT_L)
            if res1 != COMM_SUCCESS or res2 != COMM_SUCCESS:
                logger.error("Servo %d limits get failed: min_res=%s, max_res=%s", 
                             sid, self._handler.getTxRxResult(res1), self._handler.getTxRxResult(res2))
                limits.append((0.0, 0.0, 0, 0))
            elif err1 != 0 or err2 != 0:
                logger.error("Servo %d limits get error: min_err=%s, max_err=%s", 
                             sid, self._handler.getRxPacketError(err1), self._handler.getRxPacketError(err2))
                limits.append((0.0, 0.0, 0, 0))
            else:
                real_min = self._pos_to_angle(min_val)
                real_max = self._pos_to_angle(max_val)
                logger.info("Servo ID %d limits are: min=%f, max=%f", sid, real_min, real_max)
                limits.append((real_min, real_max, int(min_val), int(max_val)))
        return limits

    def set_limits(self, servo_id: int | list[int] | None = None, 
                   min_val: float | list[float] | None = None, 
                   max_val: float | list[float] | None = None) -> list[bool] | None:
        """Set the hardware min and max angle/position limits."""
        if servo_id is None:
            servo_id = self.servo_ids
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
            min_pos = self._angle_to_pos(mn)
            max_pos = self._angle_to_pos(mx)
            
            # EPROM must be unlocked before writing limits
            self._handler.unLockEprom(sid)
            time.sleep(0.05)
            
            res1, err1 = self._handler.write2ByteTxRx(sid, STS_MIN_ANGLE_LIMIT_L, min_pos)
            res2, err2 = self._handler.write2ByteTxRx(sid, STS_MAX_ANGLE_LIMIT_L, max_pos)
            
            # Lock EPROM after writing
            self._handler.LockEprom(sid)
            time.sleep(0.05)
            
            if res1 != COMM_SUCCESS or res2 != COMM_SUCCESS:
                logger.error("Servo %d limits set failed: min_res=%s, max_res=%s", 
                             sid, self._handler.getTxRxResult(res1), self._handler.getTxRxResult(res2))
                results.append(False)
            elif err1 != 0 or err2 != 0:
                logger.error("Servo %d limits set error: min_err=%s, max_err=%s", 
                             sid, self._handler.getRxPacketError(err1), self._handler.getRxPacketError(err2))
                results.append(False)
            else:
                logger.info("Servo ID %d limits set successfully: min=%f, max=%f", sid, mn, mx)
                results.append(True)
        return results

    def is_moving(self, servo_id: int | list[int] | None = None) -> list[bool] | None:
        """Check if the servo(s) is moving."""
        if servo_id is None:
            servo_id = self.servo_ids
        elif not isinstance(servo_id, list):
            servo_id = [servo_id]
        
        moving_status = []
        for sid in servo_id:
            val, res, err = self._handler.ReadMoving(sid)
            if res != COMM_SUCCESS:
                logger.error("Servo %d moving status get failed: %s", sid, self._handler.getTxRxResult(res))
                moving_status.append(False)
            elif err != 0:
                logger.error("Servo %d moving status get error: %s", sid, self._handler.getRxPacketError(err))
                moving_status.append(False)
            else:
                logger.info("Servo ID %d moving status is %d", sid, val)
                moving_status.append(bool(val))
        return moving_status


StServo = STServo
