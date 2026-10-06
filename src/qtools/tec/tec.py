#!/usr/bin/env python3
"""Communicates with 光测未来 TEC device.

Notes:
    The full serial specification is available in their document:
    'RD105_SPEC_通讯协议_v1.3.0.pdf'.
"""

from __future__ import annotations

import sys
from pathlib import Path

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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m qtools.tec.tec [SERIAL_PORT] [--mock]")
        print("Example: python -m qtools.tec.tec /dev/ttyUSB0")
        print("         python -m qtools.tec.tec --mock")
        sys.exit(0)

    is_mock = "--mock" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--mock"]
    path = args[0] if args else ""

    log_name = f"{Path(path).name}_tec.log" if path else "tec.log"
    device = TEC(path, logfile=log_name, is_mock=is_mock)
    print("Device:", device)
    print("Is ON?", device.active())
    print("Current setpoint:", device.settemp)
    print("Current temperature:", device.temp)
