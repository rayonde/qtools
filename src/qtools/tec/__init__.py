"""TEC (Thermoelectric Cooler) Controller subpackage for SenseFuture (光测未来) hardware."""

from __future__ import annotations

from qtools.tec.connection import (
    BaseTransport,
    MockSerialTransport,
    SerialTransport,
    find_serial_device,
    list_serial_ports,
)
from qtools.tec.controller import TEC, SenseFutureTEC, TECChannel, _round
from qtools.tec.enums import (
    ERROR_BIT_MAP,
    TEC_MODEL_MAP,
    PowerMode,
    SensorModel,
    TECMode,
    TECPolarity,
)
from qtools.tec.exceptions import (
    TECConnectionError,
    TECDeviceNotFoundError,
    TECError,
    TECProtocolError,
)

__all__ = [
    "TEC",
    "SenseFutureTEC",
    "TECChannel",
    "TECMode",
    "TECPolarity",
    "SensorModel",
    "PowerMode",
    "TEC_MODEL_MAP",
    "ERROR_BIT_MAP",
    "TECError",
    "TECConnectionError",
    "TECDeviceNotFoundError",
    "TECProtocolError",
    "find_serial_device",
    "list_serial_ports",
    "BaseTransport",
    "SerialTransport",
    "MockSerialTransport",
    "_round",
]
