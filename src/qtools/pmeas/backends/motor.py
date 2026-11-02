"""Motor hardware interface for qtools.pmeas.

Single import point for all qtools.motor symbols used across this package.

Usage::

    from qtools.pmeas.backends.motor import MotorBackend, get_motor, list_motors
"""

from qtools.motor import (
    MotorBackend,
    MotorConfigManager,
    MotorDeviceInfo,
    get_motor,
    list_motors,
)

__all__ = [
    "MotorBackend",
    "MotorConfigManager",
    "get_motor",
    "list_motors",
    "MotorDeviceInfo",
]
