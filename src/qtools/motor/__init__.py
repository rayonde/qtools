"""qtools.motor — Python interface and CLI for rotation stages.

Provides:
* Generic motor backend interface  (:class:`MotorBackend`)
* Physical K10CR1 stage backend  (:class:`K10CR1Backend`)
* Low-level APT-protocol driver  (:class:`ThorlabsK10CR1`)
* Device auto-discovery  (:func:`list_devices`)
* Convenience connection helper  (:func:`get_motor`)
"""

from qtools import __version__ as __version__

from qtools.motor.backends.motor import MotorBackend, list_devices
from qtools.motor.backends.k10cr1.k10cr1 import ThorlabsK10CR1
from qtools.motor.backends.k10cr1.stage import K10CR1Backend
from qtools.motor.connection import get_motor
from qtools.motor.config import MotorConfigManager

__all__ = [
    "MotorBackend",
    "K10CR1Backend",
    "ThorlabsK10CR1",
    "MotorConfigManager",
    "list_devices",
    "get_motor",
]


