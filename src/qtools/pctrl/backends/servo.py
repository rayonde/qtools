#!/usr/bin/env python3
"""
servo.py — Unified servo backend for qtools.pctrl.

ServoBackend exposes a consistent API regardless of the hardware.
Application code interacts with ServoBackend using high-level methods.
"""

from __future__ import annotations

import logging
from typing import Any

from .scservo import SCServo
from .stservo import STServo
from .mockservo import MockServo

logger = logging.getLogger(__name__)

class ServoBackend:

    def __init__(
        self,
        port: str,
        baudrate: int = 1_000_000,
        servo_type: str = "scs",
        mock: bool = False,
    ) -> None:
        self._servo_type = servo_type.lower()
        if mock:
            self._impl = MockServo(port, baudrate, self._servo_type)
        else:
            if self._servo_type == "scs":
                self._impl = SCServo(port, baudrate)
            elif self._servo_type == "sts":
                self._impl = STServo(port, baudrate)
            else:
                raise ValueError(f"Unsupported servo type: {self._servo_type}")
        
    def __getattr__(self, name: str) -> Any:
        # Delegate undefined attribute access to the underlying implementation class
        if self._impl is not None:
            return getattr(self._impl, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @property
    def servo_ids(self) -> list[int]:
        """Return a list of servo IDs present on the bus."""
        return self._impl.list_servos()

    @property
    def is_open(self) -> bool:
        """Return True if the connection is active."""
        return self._impl.is_open

    @property
    def type(self) -> str | None:
        """The active servo protocol/type name ('scs' or 'sts')."""
        return self._servo_type

    @property
    def port_handler(self):
        """Raw PortHandler instance."""
        return self._impl.port_handler

    def close(self) -> None:
        """Close the serial port connection."""
        self._impl.close()

    def angle_to_pos(self, angle: float) -> int:
        return self._impl._angle_to_pos(angle)

    def pos_to_angle(self, pos: int) -> float:
        return self._impl._pos_to_angle(pos)
    # ------------------------------------------------------------------
    # High-level Delegated API 
    # ------------------------------------------------------------------

    def ping(self, servo_id: int | list[int] | None = None) -> Any:
        """
        Ping a servo or multiple servos.
        :param servo_id: Can be a single ID (int), a list/tuple of IDs, 
                         or None (default) to broadcast ping to all servos.
        """
        return self._impl.ping(servo_id)

    def lock(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Enable torque lock (servo holds position).
        :param servo_id: Can be a single ID (int), a list/tuple of IDs, 
                         or None (default) to broadcast lock to all servos.
        """
        return self._impl.lock(servo_id)

    def unlock(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Disable torque lock (servo rotates freely).
        """
        return self._impl.release(servo_id)

    def release(self, servo_id: int | list[int] | None = None) -> bool:
        """
        Disable torque lock (servo rotates freely).
        """
        return self._impl.release(servo_id)

    def move(self, servo_id: int, position: int, speed: int, acc: int) -> tuple[int, int]:
        """Move the servo to a position with speed and acc."""
        return self._impl.move(servo_id, position, speed, acc)

    def set_id(self, new_id: int, old_id: int | None = None) -> bool:
        """Change the servo's ID."""
        servo_ids = self.servo_ids
        if old_id is None:
            if len(servo_ids) > 1:
                raise ValueError("Multiple servos found on the bus. Please specify old_id.")
            elif len(servo_ids) == 0:
                raise ValueError("No servos found on the bus.")
            else:
                old_id = servo_ids[0]
        return self._impl.set_id(old_id, new_id)

    def get_limits(self, servo_id: int | list[int] | None = None) -> list[tuple[float, float, int, int]]  | None:
        """Get the hardware min and max angle/position limits."""
        return self._impl.get_limits(servo_id)

    def set_limits(self, servo_id: int | list[int] | None = None, 
                   min_val: float | list[float] | None = None, 
                   max_val: float | list[float] | None = None) -> list[bool] | None:
        """Set hardware min and max angle/position limits."""
        return self._impl.set_limits(servo_id, min_val, max_val)

    def set_speed(self, servo_id: int | list[int] | None = None, 
                 speed: float | list[float] | None = None) -> list[bool] | None:
        """Set the speed of the servo."""
        return self._impl.set_speed(servo_id, speed)
    
    def get_speed(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the speed of the servo."""
        return self._impl.get_speed(servo_id)

    def set_angle(self, servo_id: int | list[int] | None = None, 
                 angle: float | list[float] | None = None) -> list[bool] | None:
        """Set the angle of the servo."""
        return self._impl.set_angle(servo_id, angle)
    
    def get_angle(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the angle of the servo."""
        return self._impl.get_angle(servo_id)

    def get_target_angles(self, servo_id: int | list[int] | None = None) -> list[float] | None:
        """Get the target angles of the servo(s)."""
        return self._impl.get_target_angles(servo_id)

    def is_moving(self, servo_id: int | list[int] | None = None) -> list[bool] | None:
        """Check if the servo(s) is moving."""
        return self._impl.is_moving(servo_id)

    def rotate(self, servo_id: int | list[int] | None = None,
              angle: float | list[float] | None = None) -> list[bool] | None:
        """Rotate the servo by a specified angle."""
        return self._impl.rotate(servo_id, angle)

    def set_pos(self, servo_id: int | list[int] | None = None,
                position: int | list[int] | None = None) -> list[bool] | None:
        """Set raw encoder position(s)."""
        return self._impl.set_pos(servo_id, position)

    def rotate_pos(self, servo_id: int | list[int] | None = None,
                   delta: int | list[int] | None = None) -> list[bool] | None:
        """Rotate by a raw encoder delta."""
        return self._impl.rotate_pos(servo_id, delta)

    # ── Deadband ───────────────────────────────────────────────

    def get_deadband(self, servo_id: int) -> dict | None:
        """Read CW/CCW deadband values from a servo's EEPROM.

        Returns ``{"cw": int, "ccw": int}`` or ``None`` on comm failure.
        """
        return self._impl.get_deadband(servo_id)

    def set_deadband(self, servo_id: int | list[int] | None = None,
                      cw: int = 2, ccw: int | None = None) -> bool:
        """Set CW/CCW deadband on servo(s) and persist to EEPROM."""
        return self._impl.set_deadband(servo_id, cw=cw, ccw=ccw)