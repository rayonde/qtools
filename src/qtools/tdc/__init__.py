"""TDC - Cross-platform Time-to-Digital Converter toolkit.

Supports multiple TDC hardware backends:
- S-Fifteen TDC1 (serial)
- S-Fifteen TDC2 (USB)
- CIQTEK TDC1610 (Ethernet)
- IDQ TDC (placeholder)
- Simulator (for testing)
"""

import sys
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("qtools")
except PackageNotFoundError:
    try:
        __version__ = version("tdc")
    except PackageNotFoundError:
        __version__ = "0.1.0-dev"

from qtools.tdc.backends.base import TDCBackend, BackendCapability
from qtools.tdc.data import (
    SinglesResult,
    TimestampResult,
    G2Result,
    TripletResult,
    GateResult,
    DeviceInfo,
    DataWriter,
    read_log,
    save_ts_binary,
    save_hdf5,
)
from qtools.tdc.connection import (
    get_backend,
    get_device,
    list_backends,
    auto_discover,
    discover_all,
    display_devices,
)

from qtools.tdc.api import TDC, count_rate, singles, g2, pairs, triplet, gate
import qtools.tdc.backends  # noqa: F401

# Backward compatibility alias
sys.modules.setdefault("tdc", sys.modules[__name__])

__all__ = [
    "TDCBackend",
    "BackendCapability",
    "SinglesResult",
    "TimestampResult",
    "G2Result",
    "TripletResult",
    "GateResult",
    "DeviceInfo",
    "DataWriter",
    "read_log",
    "save_ts_binary",
    "save_hdf5",
    "get_backend",
    "get_device",
    "list_backends",
    "auto_discover",
    "discover_all",
    "display_devices",
    "TDC",
    "count_rate",
    "singles",
    "g2",
    "pairs",
    "triplet",
    "gate",
]
