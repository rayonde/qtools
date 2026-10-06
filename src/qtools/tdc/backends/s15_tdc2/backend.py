"""S-Fifteen TDC2 Backend implementation.

Wraps `S15lib.instruments.TimestampTDC2`.

NOTE: This backend is Linux-only because it relies on:
  - Linux kernel USB drivers for Cypress FX2/FX3 (device path /dev/ioboards/usbtmst*)
  - The `readevents7` binary (invoked as a subprocess by S15lib)
  - libusb (optional, for Phase 2 C native implementation)
"""

from __future__ import annotations

import glob
import logging
import os
import platform
from typing import List, Optional

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import DeviceInfo, SinglesResult, TimestampResult
from qtools.tdc.backends.s15_tdc2.config import CHANNEL_COUNT, RESOLUTION_PS, DEFAULT_DEVICE_PATH
from qtools.tdc.backends.s15_common import decode_pattern_channels

logger = logging.getLogger(__name__)

# Try importing S15lib.  This must never crash module import: a broken or
# incomplete S15lib (e.g. a syntax error in one of its modules) should degrade
# to S15LIB_AVAILABLE=False so the CLI and the backend registry still load.
try:
    from S15lib.instruments import TimestampTDC2
    S15LIB_AVAILABLE = True
except Exception as exc:  # ImportError, SyntaxError, IndentationError, ...
    logger.warning("S15lib unavailable for the s15_tdc2 backend: %s", exc)
    S15LIB_AVAILABLE = False


def _parse_binary_timestamps(filename: str, highres_tscard: bool = True):
    """Reads raw timestamp binary file into time and patterns vectors.

    Adapted from S15lib.g2lib.g2lib._data_extractor.
    """
    if not os.path.exists(filename) or os.path.getsize(filename) == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.uint32)

    with open(filename, "rb") as f:
        data = np.fromfile(file=f, dtype="=I").reshape(-1, 2)
        if highres_tscard:
            # 4ps time resolution card format (TDC2)
            t = ((np.uint64(data[:, 0]) << 22) + (data[:, 1] >> 10)) / 256.0
        else:
            # Standard resolution format (TDC1)
            t = ((np.uint64(data[:, 0]) << 17) + (data[:, 1] >> 15)) / 8.0
        p = data[:, 1] & 0xF
        return t, p


@register_backend("s15_tdc2")
class S15TDC2Backend(TDCBackend):
    """Backend for S-Fifteen TDC2.

    .. warning::
       This backend is only supported on **Linux**. It relies on
       Linux-specific USB device paths (``/dev/ioboards/usbtmst*``),
       the ``readevents7`` binary, and kernel USB drivers for Cypress
       FX2/FX3. It will **not** work on macOS or Windows.
    """

    def __init__(self, device_path: Optional[str] = None) -> None:
        self._device_path = device_path or DEFAULT_DEVICE_PATH
        self._dev = None
        self._connected = False

    @property
    def name(self) -> str:
        return "s15_tdc2"

    @property
    def vendor(self) -> str:
        return "S-Fifteen Instruments"

    @property
    def channel_count(self) -> int:
        return CHANNEL_COUNT

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
        return RESOLUTION_PS

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        # Cross-platform guard: this backend is Linux-only
        if platform.system() != "Linux":
            raise OSError(
                "The s15_tdc2 backend is only supported on Linux. "
                "It requires Linux-specific USB device paths (/dev/ioboards/usbtmst*) "
                "and the readevents7 binary. "
                f"Detected OS: {platform.system()}. "
                "Use the 'simulator' backend for development on other platforms."
            )

        if not S15LIB_AVAILABLE:
            raise ImportError(
                "S15lib is required to connect to physical S-Fifteen hardware. "
                "Please install it with `pip install s15lib`."
            )

        target_path = device_path or self._device_path
        readevents_path = kwargs.get("readevents", "/usr/bin/readevents7")
        outfile_path = kwargs.get("tmpfile", "/tmp/quick_timestamp")

        logger.info("Connecting to S-Fifteen TDC2 device at: %s", target_path)

        try:
            timestamp = TimestampTDC2(
                device_path=target_path,
                readevents_path=readevents_path,
                outfile_path=outfile_path,
            )
            # Set default threshold
            timestamp.threshold = kwargs.get("threshold", 0.6)
            timestamp.fast = kwargs.get("fast", False)

            self._dev = timestamp
            self._device_path = target_path
            self._connected = True

        except Exception as e:
            raise ConnectionError(f"Failed to connect to TDC2: {e}") from e

    def disconnect(self) -> None:
        if not self._connected or self._dev is None:
            return
        logger.info("Disconnecting S-Fifteen TDC2")
        self._dev = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_singles(self, integration_time: float) -> SinglesResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # TimestampTDC2.get_counts returns:
        # [c1, c2, c3, c4, actual_duration_seconds] if return_actual_duration is True
        data = self._dev.get_counts(
            duration=integration_time,
            return_actual_duration=True,
            ignore_rollover=True,
        )
        counts = np.array(data[:4], dtype=np.uint64)
        actual_duration = data[4]

        # Calculate count rates
        count_rates = counts.astype(np.float64) / actual_duration

        return SinglesResult(
            integration_time=actual_duration,
            counts=counts,
            count_rates=count_rates,
        )

    def get_timestamps(self, duration: float) -> TimestampResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # Run readevents7 subprocess to collect timestamps to self._outfile_path
        self._dev._call_with_duration(["-a1", "-X"], duration=duration)

        # Parse the output binary file
        t, p = _parse_binary_timestamps(self._dev._outfile_path, highres_tscard=True)

        if len(t) == 0:
            return TimestampResult(
                timestamps=np.array([], dtype=np.int64),
                channels=np.array([], dtype=np.uint8),
                resolution_ps=RESOLUTION_PS,
                total_time_ns=duration * 1e9,
            )

        # Convert timestamps from nanoseconds to picoseconds
        timestamps_ps = (t * 1000.0).astype(np.int64)

        # Decode channel pattern masks (1, 2, 4, 8) into 1-based physical channel indices (1, 2, 3, 4).
        # Multi-bit patterns are expanded (one row per channel, shared timestamp).
        timestamps_ps, channels_assigned = decode_pattern_channels(
            timestamps_ps, p, CHANNEL_COUNT
        )

        total_time_ns = duration * 1e9

        return TimestampResult(
            timestamps=timestamps_ps,
            channels=channels_assigned,
            resolution_ps=RESOLUTION_PS,
            total_time_ns=total_time_ns,
        )

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        voltage_V = float(threshold) / 1000.0 if threshold > 10 else float(threshold)
        self._dev.threshold = voltage_V

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        # TDC2 is connected via a USB-FIFO bridge (FTDI FT2232H / Cypress FX2).
        # We can probe standard device files.
        devices: List[DeviceInfo] = []

        if platform.system() != "Linux":
            return devices

        # Check standard Linux path
        if os.path.exists(DEFAULT_DEVICE_PATH):
            devices.append(
                DeviceInfo(
                    backend_name="s15_tdc2",
                    device_path=DEFAULT_DEVICE_PATH,
                    description="S-Fifteen TDC2 USB Device",
                )
            )

        # Also check /dev/ioboards/usbtmst*
        for path in glob.glob("/dev/ioboards/usbtmst*"):
            if path != DEFAULT_DEVICE_PATH:
                devices.append(
                    DeviceInfo(
                        backend_name="s15_tdc2",
                        device_path=path,
                        description="S-Fifteen TDC2 USB Device",
                    )
                )

        return devices
