"""
Backward compatibility module for BasePowerMeter.
Re-exports PowerMeter as BasePowerMeter.
"""

from qtools.powermeter.backends.powermeter import (
    PowerMeter,
    register_backend,
    get_backend_class,
    list_available_backends,
)

BasePowerMeter = PowerMeter

__all__ = [
    "PowerMeter",
    "BasePowerMeter",
    "register_backend",
    "get_backend_class",
    "list_available_backends",
]
