"""S-Fifteen TDC1 Backend implementation.

Wraps `S15lib.instruments.usb_counter_fpga.TimestampTDC1`.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import CoincidenceResult, DeviceInfo, SinglesResult, TimestampResult
from qtools.tdc.backends.s15_tdc1.exp_backend import CHANNEL_COUNT, RESOLUTION_PS, find_tdc1_devices
from qtools.tdc.backends.s15_common import decode_pattern_channels
logger = logging.getLogger(__name__)

# Try importing from S15lib.  This must never crash module import: a broken
# or incomplete S15lib (e.g. a syntax error in one of its modules) should
# degrade to S15LIB_AVAILABLE=False so the CLI and backend registry load.
try:
    from S15lib.instruments.usb_counter_fpga import TimestampTDC1
    S15LIB_AVAILABLE = True
except Exception as exc:  # ImportError, SyntaxError, IndentationError, ...
    logger.warning("S15lib unavailable for the s15_tdc1 backend: %s", exc)
    S15LIB_AVAILABLE = False


@register_backend("s15_tdc1")
class S15TDC1Backend(TDCBackend):
    """Backend for S-Fifteen TDC1."""

    def __init__(self, device_path: Optional[str] = None) -> None:
        self._device_path = device_path
        self._dev = None
        self._connected = False

    @property
    def name(self) -> str:
        return "s15_tdc1"

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
            | BackendCapability.COINCIDENCE
            | BackendCapability.COINCIDENCE_SOFTWARE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return RESOLUTION_PS

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        if not S15LIB_AVAILABLE:
            raise ImportError(
                "S15lib is required to connect to physical S-Fifteen hardware. "
                "Please install it with `pip install s15lib`."
            )

        # Use parameter device_path or stored path, or auto-discover
        target_path = device_path or self._device_path
        if not target_path:
            devices = self.discover_devices()
            if not devices:
                raise ConnectionError("No S-Fifteen TDC1 devices found.")
            target_path = devices[0].device_path

        logger.info("Connecting to S-Fifteen TDC1 device at: %s", target_path)

        try:
            # Initialize device: mirror TimestampTDC1.__init__ minimal flow

            timestamp = TimestampTDC1(device_path=target_path)
            # update from justin to fix the fireware bug 
    

            # ── Clean serial buffer after all S15lib init/configure chatter ──
            timestamp._com.reset_input_buffer()

            self._dev = timestamp
            self._device_path = target_path
            self._connected = True

        except Exception as e:
            self._connected = False
            self._dev = None
            raise ConnectionError(f"Failed to connect to S15 TDC1 at {target_path}: {e}") from e

    def disconnect(self) -> None:
        if self._connected and self._dev is not None:
            try:
                if hasattr(self._dev, "_com") and self._dev._com is not None:
                    self._dev._com.reset_input_buffer()
                    self._dev._com.reset_output_buffer()
                    self._dev._com.close()
            except Exception as e:
                logger.warning("Error while closing S15 TDC1 serial connection: %s", e)

        self._dev = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_singles(self, integration_time: float) -> SinglesResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # TDC1 get_counts returns a list/tuple of counts for 4 channels
        counts_list = self._dev.get_counts(integration_time)
        self._dev._com.reset_input_buffer()
        self._dev._com.reset_output_buffer()
        
        counts = np.array(counts_list, dtype=np.uint64)
        
        # Calculate count rates
        count_rates = counts.astype(np.float64) / integration_time

        return SinglesResult(
            integration_time=integration_time,
            counts=counts,
            count_rates=count_rates,
        )

    def get_timestamps(self, duration: float) -> TimestampResult:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # Flush serial input buffer before and after timestamp acquisition
        # to prevent stale text-protocol bytes from corrupting the binary
        # timestamp stream (struct.unpack requires exact 4-byte alignment).
        self._dev._com.reset_input_buffer()

        # Retrieve raw timestamps from S15lib
        # t is a numpy array of timestamps in ns (float64)
        # p is a list of channel pattern strings, e.g. "0001", "0010"
        t, p = self._dev.get_timestamps(duration, highcount=False)

        # Convert pattern strings to integer masks
        p_masks = np.array([int(x, base=2) for x in p], dtype=np.uint8)

        # Convert timestamps from ns to ps
        timestamps_ps = (t * 1000).astype(np.int64)

        # Extract active channel for each event.
        # S15lib TDC1 encodes channels 1-4 as bits 0-3 in the binary string.
        # Multi-bit patterns are expanded (one row per channel, shared timestamp).
        timestamps_ps, channels_assigned = decode_pattern_channels(
            timestamps_ps, p_masks, CHANNEL_COUNT
        )

        total_time_ns = duration * 1e9

        return TimestampResult(
            timestamps=timestamps_ps,
            channels=channels_assigned,
            resolution_ps=RESOLUTION_PS,
            total_time_ns=total_time_ns,
        )
    
    def get_coincidence(
        self,
        duration: float,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        unit: str = "ns",
        window_start: int | float | None = None,
        window_stop: int | float | None = None,
        method: str = "software",
    ) -> CoincidenceResult:
        """Use TDC1's fixed ``pairs`` counter for hardware coincidence."""
        if method != "hardware":
            return super().get_coincidence(
                duration=duration,
                ch_start=ch_start,
                ch_stop=ch_stop,
                ch_stop_delay=ch_stop_delay,
                unit=unit,
                window_start=window_start,
                window_stop=window_stop,
                method=method,
            )
        if duration <= 0:
            raise ValueError("duration must be positive")
        if (ch_start, ch_stop) not in {(1, 3), (1, 4), (2, 3), (2, 4)}:
            raise ValueError(
                "TDC1 hardware pairs supports channel pairs (1,3), (1,4), "
                "(2,3), and (2,4) only"
            )
        if ch_stop_delay != 0:
            raise ValueError("TDC1 hardware pairs has no configurable channel delay")
        if window_start is not None or window_stop is not None:
            raise ValueError("TDC1 hardware pairs uses the device's fixed coincidence gate")
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        values = tuple(self._dev.get_counts_and_coincidences(duration))
        if len(values) < 8:
            raise RuntimeError(f"TDC1 pairs response has {len(values)} fields; expected at least 8")
        pair_index = {(1, 3): 4, (1, 4): 5, (2, 3): 6, (2, 4): 7}[(ch_start, ch_stop)]
        counts = np.asarray(values[:4], dtype=np.float64)
        return CoincidenceResult(
            count=int(values[pair_index]),
            acc_count_perbin=None,
            accidental_count=None,
            channel1_rate=float(counts[ch_start - 1] / duration),
            channel2_rate=float(counts[ch_stop - 1] / duration),
            integration_time=duration,
            order=2,
            accidental_method=None,
            method="hardware",
        )

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

        # TDC1 hardware uses one threshold for all channels.
        self._dev.threshold = float(threshold)

        # S15lib threshold setter writes "time ..." to serial and
        # readlines() may leave stale bytes in the input buffer.
        self._dev._com.reset_input_buffer()

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        return find_tdc1_devices()
