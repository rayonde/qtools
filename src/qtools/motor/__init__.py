"""qtools.motor — Python interface and CLI for rotation stages.

Provides:
* Generic motor backend interface  (:class:`MotorBackend`)
* Physical K10CR1 stage backend  (:class:`K10CR1Backend`)
* Low-level APT-protocol driver  (:class:`ThorlabsK10CR1`)
* Device auto-discovery  (:func:`list_motors`)
* Convenience connection helper  (:func:`get_motor`)
"""

from qtools import __version__ as __version__

from qtools.motor.backends.motor import (
    MotorBackend,
    MotorDeviceInfo,
    list_motors,
)
from qtools.motor.backends.k10cr1.k10cr1 import ThorlabsK10CR1
from qtools.motor.backends.k10cr1.stage import K10CR1Backend
from qtools.motor.backends.kdc101.kdc101 import KDC101Error, ThorlabsKDC101
from qtools.motor.backends.kdc101.stage import (
    DEFAULT_KDC101_STAGE_SETTINGS,
    DEFAULT_KDC101_TRAVEL_MODE,
    KDC101Backend,
)
from qtools.motor.connection import get_motor
from qtools.motor.config import MotorConfigManager

__all__ = [
    "MotorBackend",
    "K10CR1Backend",
    "KDC101Backend",
    "DEFAULT_KDC101_STAGE_SETTINGS",
    "DEFAULT_KDC101_TRAVEL_MODE",
    "ThorlabsK10CR1",
    "ThorlabsKDC101",
    "KDC101Error",
    "MotorConfigManager",
    "list_motors",
    "MotorDeviceInfo",
    "get_motor",
]


