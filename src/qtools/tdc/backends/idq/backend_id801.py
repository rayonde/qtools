"""IDQ ID801 TDC Backend implementation.

Wraps the IDQ ID801 Python driver and dynamic C library (libtdcbase.so).
Supports 8 physical channels with 81 ps typical resolution over USB.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import DeviceInfo, SinglesResult, TimestampResult

logger = logging.getLogger(__name__)

# Dynamic import configuration to support bundled TDC_ID801 or cloned repository
ID801_AVAILABLE = False
ID801_CLASS = None
SignalCond_ENUM = None

def _resolve_id801_import():
    global ID801_AVAILABLE, ID801_CLASS, SignalCond_ENUM
    if ID801_AVAILABLE:
        return True

    # 1. Try global import first
    try:
        from id801.id801 import ID801, SignalCond
        ID801_CLASS = ID801
        SignalCond_ENUM = SignalCond
        ID801_AVAILABLE = True
        return True
    except ImportError:
        pass

    # 2. Try bundled TDC_ID801/src in this package directory
    current_dir = Path(__file__).resolve().parent
    bundled_src = current_dir / "TDC_ID801" / "src"
    if bundled_src.exists() and str(bundled_src) not in sys.path:
        sys.path.insert(0, str(bundled_src))
        try:
            from id801.id801 import ID801, SignalCond
            ID801_CLASS = ID801
            SignalCond_ENUM = SignalCond
            ID801_AVAILABLE = True
            return True
        except ImportError:
            pass

    # 3. Try parent directories for 'idq_id801_tdc' workspace
    for parent in current_dir.parents:
        cand = parent / "idq_id801_tdc" / "src"
        if cand.exists() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
            try:
                from id801.id801 import ID801, SignalCond
                ID801_CLASS = ID801
                SignalCond_ENUM = SignalCond
                ID801_AVAILABLE = True
                return True
            except ImportError:
                pass

    return False

_resolve_id801_import()


@register_backend("idq_id801")
@register_backend("id801")
@register_backend("idq")
class ID801Backend(TDCBackend):
    """Backend implementation for IDQ ID801 8-channel USB TDC."""

    def __init__(self, device_path: Optional[str] = None) -> None:
        self._device_path = device_path
        self._dev = None
        self._connected = False
        self._resolution_ps = 81.0  # Default IDQ ID801 resolution is 81 ps

    @property
    def name(self) -> str:
        return "id801"

    @property
    def vendor(self) -> str:
        return "IDQ (ID Quantique)"

    @property
    def channel_count(self) -> int:
        return 8  # ID801 supports 8 input channels

    @property
    def capabilities(self) -> BackendCapability:
        return (
            BackendCapability.SINGLES
            | BackendCapability.TIMESTAMPS
            | BackendCapability.HIST_SOFTWARE
            | BackendCapability.COINCIDENCE_SOFTWARE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return self._resolution_ps

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        _resolve_id801_import()
        if not ID801_AVAILABLE or ID801_CLASS is None:
            raise ImportError(
                "IDQ ID801 Python driver wrapper is required. "
                "Ensure 'idq-id801' is installed or 'TDC_ID801/src' is present in the idq directory."
            )

        # Allow custom path to libtdcbase.so
        lib_path = kwargs.get("lib_path")
        
        # If no lib_path is specified, look in bundled folder then parent workspaces
        if lib_path is None:
            current_dir = Path(__file__).resolve().parent
            bundled_so = current_dir / "TDC_ID801" / "src" / "id801" / "libtdcbase.so"
            if bundled_so.exists():
                lib_path = str(bundled_so)
            else:
                for parent in current_dir.parents:
                    local_so = parent / "idq_id801_tdc" / "src" / "id801" / "libtdcbase.so"
                    if local_so.exists():
                        lib_path = str(local_so)
                        break

        logger.info("Connecting to IDQ ID801 device...")
        try:
            if lib_path:
                logger.debug("Loading IDQ shared library from: %s", lib_path)
                self._dev = ID801_CLASS(lib_path=lib_path)
            else:
                self._dev = ID801_CLASS()
                
            self._dev.initialize()
            
            # Fetch actual timebase (resolution) from the hardware
            try:
                timebase_sec = self._dev.get_timebase()
                self._resolution_ps = timebase_sec * 1e12
                logger.info("Detected IDQ ID801 Timebase: %.2f ps", self._resolution_ps)
            except Exception as e:
                logger.warning("Could not read hardware timebase, falling back to default 81.0 ps: %s", e)

            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to IDQ ID801: {e}") from e

    def disconnect(self) -> None:
        if not self._connected or self._dev is None:
            return
        logger.info("Disconnecting IDQ ID801")
        try:
            self._dev.__del__()
        except Exception:
            pass
        self._dev = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_singles(self, integration_time: float) -> SinglesResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # Exposure time in milliseconds (min 1ms, round up)
        exp_time_ms = max(int(integration_time * 1000.0), 1)

        # wait_to_get_coinc_counters_for waits for self-exposure period
        counts_list, labels, updates = self._dev.wait_to_get_coinc_counters_for(
            exp_time_ms, coinc_win=500
        )
        
        # Elements 0 to 7 are the count rates (counts/exposure) for channels 1-8
        counts = np.array(counts_list[:8], dtype=np.uint64)
        
        # Calculate count rates
        actual_duration = float(exp_time_ms) / 1000.0
        count_rates = counts.astype(np.float64) / actual_duration

        return SinglesResult(
            integration_time=actual_duration,
            counts=counts,
            count_rates=count_rates,
        )

    def get_timestamps(self, duration: float) -> TimestampResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # Exposure time in milliseconds
        exp_time_ms = max(int(duration * 1000.0), 1)

        # get_timestamps blocks for exp_time_ms and returns raw timestamps (in units of 81 ps)
        # and 0-based channel indices (0 to 7)
        raw_timestamps, raw_channels = self._dev.get_timestamps(exp_time_ms)

        # Convert raw timestamps to picoseconds
        timestamps_ps = (raw_timestamps.astype(np.float64) * self._resolution_ps).astype(np.int64)
        # Convert 0-based C-DLL channels to 1-based physical channels (1..N)
        channels_assigned = (raw_channels + 1).astype(np.uint8)

        total_time_ns = duration * 1e9

        return TimestampResult(
            timestamps=timestamps_ps,
            channels=channels_assigned,
            resolution_ps=self._resolution_ps,
            total_time_ns=total_time_ns,
        )

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        if SignalCond_ENUM is None:
            raise RuntimeError("SignalCond enum is not loaded.")

        channels_to_set = range(1, self.channel_count + 1) if channel is None else [channel]
        for ch in channels_to_set:
            if not (1 <= ch <= self.channel_count):
                raise ValueError(f"Invalid channel index: {ch}")

            self._dev.configure_signal_conditioning(
                channel=ch - 1,
                conditioning=SignalCond_ENUM.SCOND_MISC,
                edge=1,  # 1 = Rising edge
                term=1,  # 1 = 50 Ohm Termination ON
                threshold=threshold,
            )

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        """Discover ID801 USB devices."""
        devices: List[DeviceInfo] = []
        
        # Quick USB vendor check using sysfs on Linux
        import glob
        for path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(path, "r") as f:
                    vid = f.read().strip()
                if vid.lower() == "16c0":
                    devices.append(
                        DeviceInfo(
                            backend_name="id801",
                            device_path="usb://16c0",
                            description="IDQ ID801 Time Tagging Box (USB)",
                        )
                    )
            except Exception:
                pass
                
        return devices
