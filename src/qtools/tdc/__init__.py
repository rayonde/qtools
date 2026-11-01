"""TDC - Cross-platform Time-to-Digital Converter toolkit.

Supports multiple TDC hardware backends:
- S-Fifteen TDC1 (serial)
- S-Fifteen TDC2 (USB)
- CIQTEK TDC1610 (Ethernet)
- IDQ ID900 and ID1000
- Siminics FT10xx (Windows USB)
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("qtools")
except PackageNotFoundError:
    try:
        __version__ = version("tdc")
    except PackageNotFoundError:
        __version__ = "0.1.0-dev"

import qtools.tdc.backends  # noqa: F401
from qtools.tdc.api import coincidence
from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import (
    auto_discover,
    discover_all,
    display_devices,
    get_backend,
    get_tdc,
    list_backends,
    list_tdc,
)
from qtools.tdc.measurement import TDC
from qtools.tdc.data import (
    CoincidenceResult,
    DataWriter,
    DeviceInfo,
    HeraldingGateResult,
    MarkerEvent,
    MultiCoincidenceResult,
    SinglesResult,
    TimestampResult,
    combine_samples,
    convert_time_unit,
    load_hdf5,
    load_ts_binary,
    read_log,
    save_hdf5,
    save_ts_binary,
)

__all__ = [
    "TDCBackend",
    "BackendCapability",
    "SinglesResult",
    "TimestampResult",
    "CoincidenceResult",
    "MultiCoincidenceResult",
    "HeraldingGateResult",
    "MarkerEvent",
    "combine_samples",
    "convert_time_unit",
    "load_ts_binary",
    "load_hdf5",
    "DeviceInfo",
    "DataWriter",
    "read_log",
    "save_ts_binary",
    "save_hdf5",
    "get_backend",
    "get_tdc",
    "list_tdc",
    "list_backends",
    "auto_discover",
    "discover_all",
    "display_devices",
    "TDC",
    "coincidence",
]
