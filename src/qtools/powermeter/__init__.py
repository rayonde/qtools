"""
qtools.powermeter: A unified interface for different optical power meters.
Supports Thorlabs, LBTEK, S15, and Mock backends.
"""

from qtools import __version__ as __version__

from qtools.powermeter.backends.powermeter import (
    PowerMeter,
    register_backend,
    get_backend_class,
    list_available_backends,
)
from qtools.powermeter.backends.base import BasePowerMeter
from qtools.powermeter.connection import get_device
from qtools.powermeter.measurement import read, measure_power, compute_statistics, export, format_power
from qtools.powermeter.api import measure

__all__ = [
    "PowerMeter",
    "BasePowerMeter",
    "register_backend",
    "get_backend_class",
    "list_available_backends",
    "get_device",
    "read",
    "measure_power",
    "compute_statistics",
    "export",
    "format_power",
    "measure",
]
