"""Siminics FT10xx backend for the unified qtools TDC API."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from collections.abc import Iterable
from typing import Any

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import (
    CoincidenceResult,
    DeviceInfo,
    SinglesResult,
    TimestampResult,
)

from .errors import SiminicsError
from .models import ITTRResult, MarkerEvent, ParsedTTTR, T1HistogramResult, TTTREvent
from .parser import parse_blocks
from .sdk import SiminicsSDK

logger = logging.getLogger(__name__)

FT1010 = 0x1010
FT1040 = 0x1040
FT1080 = 0x1080
MODEL_CHANNELS = {FT1010: 1, FT1040: 4, FT1080: 8}
MODEL_NAMES = {FT1010: "FT1010", FT1040: "FT1040", FT1080: "FT1080"}

MODE_T1 = 0x01
MODE_T2 = 0x02
MODE_T3 = 0x03
MODE_CO = 0x04
MODE_ITTR_T = 0x06
MODE_ITTR_M = 0x07

DEFAULT_RESOLUTION_PS = 64.0
DEFAULT_TTTR_MODE = "T2"
DEFAULT_BINS = 65_536


def _check_positive(value: float, name: str) -> float:
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


@register_backend("siminics")
class SiminicsBackend(TDCBackend):
    """Backend for Siminics FT1010/FT1040/FT1080 TCSPC instruments.

    Channels use the qtools convention CH1..CHN.  M1..M4 are sideband Marker
    inputs and are exposed through :meth:`get_last_markers` and
    :meth:`get_tttr_events`, not as ordinary counting channels.
    """

    def __init__(
        self,
        device_path: str | None = None,
        *,
        dev_id: int = 0,
        board: int = 0,
        model: int | str | None = None,
        sdk: SiminicsSDK | None = None,
        resolution_ps: float = DEFAULT_RESOLUTION_PS,
        tttr_mode: str = DEFAULT_TTTR_MODE,
        sync_period_ps: float | None = None,
        poll_interval: float = 0.001,
        task_timeout: float | None = None,
    ) -> None:
        self._device_path = device_path
        self._dev_id = int(dev_id)
        self._board = int(board)
        self._sdk = sdk or SiminicsSDK()
        self._connected = False
        self._active_mode: int | None = None
        self._dev_type: int | None = self._parse_model(model)
        self._channel_count = MODEL_CHANNELS.get(self._dev_type or FT1080, 8)
        self._resolution_ps = _check_positive(resolution_ps, "resolution_ps")
        self._tttr_mode = self._validate_tttr_mode(tttr_mode)
        self._sync_period_ps = (
            None if sync_period_ps is None else _check_positive(sync_period_ps, "sync_period_ps")
        )
        self._poll_interval = float(poll_interval)
        if not np.isfinite(self._poll_interval) or self._poll_interval < 0:
            raise ValueError("poll_interval must be a finite non-negative number")
        self._task_timeout = None if task_timeout is None else float(task_timeout)
        if self._task_timeout is not None and (
            not np.isfinite(self._task_timeout) or self._task_timeout < 0
        ):
            raise ValueError("task_timeout must be a finite non-negative number")
        self._last_parsed: ParsedTTTR | None = None
        self._last_markers: tuple[MarkerEvent, ...] = ()
        self._last_events: tuple[TTTREvent, ...] = ()
        self._last_ittr: ITTRResult | None = None

    # -- identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "siminics"

    @property
    def vendor(self) -> str:
        return "Siminics"

    @property
    def channel_count(self) -> int:
        return self._channel_count

    @property
    def capabilities(self) -> BackendCapability:
        return (
            BackendCapability.SINGLES
            | BackendCapability.TIMESTAMPS
            | BackendCapability.HIST_HARDWARE
            | BackendCapability.HIST_SOFTWARE
            | BackendCapability.COINCIDENCE
            | BackendCapability.COINCIDENCE_SOFTWARE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return self._resolution_ps

    @property
    def model(self) -> str | None:
        return MODEL_NAMES.get(self._dev_type) if self._dev_type is not None else None

    @property
    def tttr_mode(self) -> str:
        return self._tttr_mode

    @property
    def sync_period_ps(self) -> float | None:
        return self._sync_period_ps

    # -- connection -------------------------------------------------------

    @staticmethod
    def _parse_model(model: int | str | None) -> int | None:
        if model is None:
            return None
        if isinstance(model, str):
            normalized = model.upper().replace("-", "")
            for code, name in MODEL_NAMES.items():
                if normalized == name:
                    return code
            raise ValueError(f"Unsupported Siminics model: {model!r}")
        model = int(model)
        if model not in MODEL_CHANNELS:
            raise ValueError(f"Unsupported Siminics device type: 0x{model:x}")
        return model

    @staticmethod
    def _validate_tttr_mode(mode: str) -> str:
        mode = str(mode).upper()
        if mode not in {"T2", "T3"}:
            raise ValueError("tttr_mode must be 'T2' or 'T3'")
        return mode

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Siminics device not connected")

    def connect(self, device_path: str | None = None, **kwargs: Any) -> None:
        if self._connected:
            return
        if device_path is not None:
            self._device_path = device_path
        if self._device_path:
            parsed = str(self._device_path)
            if parsed.lower().startswith("siminics://"):
                self._dev_id = int(parsed.split("://", 1)[1].split("/", 1)[0])

        self._sdk.load()
        try:
            self._sdk.init()
            if not self._sdk.connected(self._dev_id):
                raise ConnectionError(f"No Siminics device connected at index {self._dev_id}")
            detected = self._sdk.device_type(self._dev_id)
            if detected not in MODEL_CHANNELS:
                raise ConnectionError(
                    f"Unsupported Siminics device type 0x{int(detected):x}; "
                    "this backend supports FT1010, FT1040, and FT1080"
                )
            self._dev_type = detected
            self._channel_count = MODEL_CHANNELS[detected]
            self._device_path = f"siminics://{self._dev_id}"
            self._connected = True
        except Exception:
            try:
                self._sdk.uninit()
            except Exception:
                logger.debug("Siminics cleanup after failed connect failed", exc_info=True)
            raise

    def disconnect(self) -> None:
        if not self._connected and not self._sdk.loaded:
            return
        try:
            if self._active_mode is not None:
                try:
                    self._sdk.invoke("StopTask", self._active_mode)
                except Exception:
                    logger.debug("Siminics task stop during disconnect failed", exc_info=True)
            self._sdk.uninit()
        finally:
            self._connected = False
            self._active_mode = None
            self._last_parsed = None
            self._last_markers = ()
            self._last_events = ()
            self._last_ittr = None

    def is_connected(self) -> bool:
        return self._connected

    # -- configuration ----------------------------------------------------

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        """Set comparator thresholds in the vendor's native integer units."""

        self._ensure_connected()
        value = round(float(threshold))
        if channel is None:
            self._sdk.check("SetStartThreshold", self._dev_id, self._board, value)
            for ch in range(self._channel_count):
                self._sdk.check("SetStopThreshold", self._dev_id, self._board, ch, value)
            return
        self._validate_channel(channel)
        self._sdk.check("SetStopThreshold", self._dev_id, self._board, channel - 1, value)

    def set_resolution(self, resolution_ps: float) -> None:
        """Set TTTR/T1 resolution using the V2.2 exponent selector."""

        self._ensure_connected()
        resolution_ps = _check_positive(resolution_ps, "resolution_ps")
        exponent = round(float(np.log2(resolution_ps)))
        if not np.isclose(resolution_ps, 2**exponent) or not (0 <= exponent <= 25):
            raise ValueError("Siminics resolution must be a power of two from 1 to 33554432 ps")
        self._sdk.check("SetTimeWindowRes", self._dev_id, exponent)
        self._resolution_ps = float(2**exponent)

    def set_edge(self, edge: int, channel: int | None = None) -> None:
        self._ensure_connected()
        if int(edge) not in (0, 1):
            raise ValueError("edge must be 0 (rising) or 1 (falling)")
        if channel is None:
            self._sdk.check("SetStartEdge", self._dev_id, int(edge))
            for ch in range(self._channel_count):
                self._sdk.check("SetStopEdge", self._dev_id, self._board, ch, int(edge))
        else:
            self._validate_channel(channel)
            self._sdk.check("SetStopEdge", self._dev_id, self._board, channel - 1, int(edge))

    def set_delay(self, delay_ns: float, channel: int | None = None) -> None:
        self._ensure_connected()
        delay_ns = float(delay_ns)
        if channel is None:
            self._sdk.check("SetStartDelay", self._dev_id, self._board, delay_ns)
        else:
            self._validate_channel(channel)
            self._sdk.check("SetStopDelay", self._dev_id, self._board, channel - 1, delay_ns)

    def set_impedance(self, impedance: int, channel: int | None = None) -> None:
        """Set input impedance (0 = high impedance, 1 = 50 ohm)."""

        self._ensure_connected()
        if int(impedance) not in (0, 1):
            raise ValueError("impedance must be 0 (high) or 1 (50 ohm)")
        if channel is None:
            self._sdk.check("SetStartImpedence", self._dev_id, int(impedance))
            for ch in range(self._channel_count):
                self._sdk.check("SetStopImpedence", self._dev_id, self._board, ch, int(impedance))
        else:
            self._validate_channel(channel)
            self._sdk.check("SetStopImpedence", self._dev_id, self._board, channel - 1, int(impedance))

    def set_start_frequency_divider(self, divider: int) -> None:
        """Set SYNC/start frequency division (1, 2, 4, or 8)."""

        self._ensure_connected()
        if int(divider) not in (1, 2, 4, 8):
            raise ValueError("divider must be one of 1, 2, 4, or 8")
        self._sdk.check("SetStartFreqDiv", self._dev_id, int(divider))

    def _validate_channel(self, channel: int) -> None:
        if not 1 <= int(channel) <= self._channel_count:
            raise ValueError(f"channel must be in 1..{self._channel_count}, got {channel}")

    # -- task helpers -----------------------------------------------------

    def _wait_task(self, *, timeout: float | None = None) -> None:
        timeout = self._task_timeout if timeout is None else timeout
        started = time.monotonic()
        while True:
            if int(self._sdk.invoke("IsTaskCompleted")) == 0:
                return
            if timeout is not None and time.monotonic() - started >= timeout:
                raise TimeoutError(f"Siminics task did not finish within {timeout:g}s")
            if self._poll_interval:
                time.sleep(self._poll_interval)

    def _collect_memory_task(self, mode: int, duration: float) -> tuple[bytes, ...]:
        del duration  # The vendor task owns the acquisition duration.
        deadline = (
            None
            if self._task_timeout is None
            else time.monotonic() + self._task_timeout
        )
        memory_mode_enabled = False
        try:
            self._sdk.check("SetMemoryDataMode", True)
            memory_mode_enabled = True
            self._sdk.check("StartTask", mode)
            self._active_mode = mode
            blocks: list[bytes] = []
            while True:
                block = self._sdk.get_memory_data(self._dev_id)
                if block is not None:
                    _, payload = block
                    if payload:
                        blocks.append(payload)
                if int(self._sdk.invoke("IsTaskCompleted")) == 0:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Siminics task did not finish within {self._task_timeout:g}s"
                    )
                if self._poll_interval:
                    time.sleep(self._poll_interval)
            while True:
                block = self._sdk.get_memory_data(self._dev_id)
                if block is None:
                    break
                _, payload = block
                if payload:
                    blocks.append(payload)
            return tuple(blocks)
        finally:
            if self._active_mode == mode:
                try:
                    self._sdk.invoke("StopTask", mode)
                except Exception:
                    logger.debug("Siminics task stop after acquisition failed", exc_info=True)
                finally:
                    self._active_mode = None
            if memory_mode_enabled:
                try:
                    self._sdk.check("SetMemoryDataMode", False)
                except Exception:
                    logger.debug("Siminics memory mode cleanup failed", exc_info=True)

    # -- generic acquisition ---------------------------------------------

    def get_singles(self, integration_time: float) -> SinglesResult:
        self._ensure_connected()
        integration_time = _check_positive(integration_time, "integration_time")
        mode = MODE_T1
        self._sdk.check("SetFileMode", mode, 0, 0)
        self._sdk.check("SetStatisticsTime", mode, integration_time)
        self._sdk.check("EnableT1", self._dev_id, self._board, (1 << self._channel_count) - 1)
        self._sdk.check("StartTask", mode)
        self._active_mode = mode
        try:
            self._wait_task(timeout=self._task_timeout)
            counts = np.zeros(self._channel_count, dtype=np.uint64)
            for index in range(self._channel_count):
                _, stop_count = self._sdk.signal_status(self._dev_id, self._board, index)
                counts[index] = stop_count
        finally:
            try:
                self._sdk.invoke("StopTask", mode)
            except Exception:
                logger.debug("Siminics T1 task stop failed", exc_info=True)
            finally:
                self._active_mode = None
        return SinglesResult(
            integration_time=integration_time,
            channels=np.arange(1, self._channel_count + 1, dtype=np.uint8),
            counts=counts,
            count_rates=counts.astype(np.float64) / integration_time,
        )

    def get_timestamps(self, duration: float) -> TimestampResult:
        self._ensure_connected()
        duration = _check_positive(duration, "duration")
        self._last_parsed = None
        self._last_markers = ()
        self._last_events = ()
        mode_number = MODE_T2 if self._tttr_mode == "T2" else MODE_T3
        mask = (1 << self._channel_count) - 1
        self._sdk.check("EnableTTTR", self._dev_id, self._board, mask)
        self._sdk.check("SetFileMode", mode_number, 0, 0)
        self._sdk.check("SetStatisticsTime", mode_number, duration)
        self._sdk.check("SetTTTREndMode", 0, 0)
        blocks = self._collect_memory_task(mode_number, duration)
        parsed = parse_blocks(
            blocks,
            mode=self._tttr_mode,
            resolution_ps=self._resolution_ps,
            sync_period_ps=self._sync_period_ps,
            byteorder="big",
        )
        self._last_parsed = parsed
        self._last_markers = parsed.markers
        self._last_events = parsed.events
        return TimestampResult(
            timestamps=parsed.timestamps,
            channels=parsed.channels,
            resolution_ps=self._resolution_ps,
            total_time_ns=duration * 1e9,
        )

    # -- Siminics-specific extensions ------------------------------------

    def get_tttr_events(self, duration: float | None = None) -> tuple[TTTREvent, ...]:
        """Return the most recent full TTTR stream, including Marker records."""

        if duration is not None:
            self.get_timestamps(duration)
        if self._last_parsed is None:
            raise RuntimeError("No TTTR acquisition has been performed")
        return self._last_events

    def get_last_markers(self) -> tuple[MarkerEvent, ...]:
        """Return Marker events from the most recent TTTR acquisition."""

        return self._last_markers

    def get_markers(self, duration: float | None = None) -> tuple[MarkerEvent, ...]:
        """Acquire (optionally) and return Marker events from a TTTR stream.

        Marker records are sideband labels in the vendor stream, not ordinary
        counting channels.  Supplying ``duration`` starts a new acquisition;
        omitting it returns the markers from the most recent acquisition.
        """

        if duration is not None:
            self.get_timestamps(duration)
        return self._last_markers

    def get_last_ittr(self) -> ITTRResult | None:
        """Return the most recent ITTR result, if one has been acquired."""

        return self._last_ittr

    def get_t1_histogram(
        self,
        duration: float,
        *,
        channel: int = 1,
        bins: int = DEFAULT_BINS,
        resolution_ps: float | None = None,
    ) -> T1HistogramResult:
        self._ensure_connected()
        self._validate_channel(channel)
        duration = _check_positive(duration, "duration")
        if int(bins) < 65_536 or int(bins) > 1_048_576:
            raise ValueError("bins must be in the range 65536..1048576")
        if resolution_ps is not None:
            self.set_resolution(resolution_ps)
        mask = 1 << (channel - 1)
        self._sdk.check("EnableT1", self._dev_id, self._board, mask)
        self._sdk.check("SetFileMode", MODE_T1, 0, 0)
        self._sdk.check("SetT1Interval", 0.1)
        self._sdk.check("SetMaxBarValue", int(bins))
        self._sdk.check("SetBinSize", self._dev_id, int(bins))
        self._sdk.check("SetStatisticsTime", MODE_T1, duration)
        self._sdk.check("StartTask", MODE_T1)
        self._active_mode = MODE_T1
        try:
            self._wait_task(timeout=self._task_timeout)
            values = (ctypes.c_ulonglong * int(bins))()
            self._sdk.check("GetT1Data", self._board, channel - 1, values)
            histogram = np.ctypeslib.as_array(values).copy().astype(np.uint64)
        finally:
            try:
                self._sdk.invoke("StopTask", MODE_T1)
            except Exception:
                logger.debug("Siminics histogram task stop failed", exc_info=True)
            finally:
                self._active_mode = None
        return T1HistogramResult(
            channel=channel,
            histogram=histogram,
            bin_width_ps=self._resolution_ps,
            integration_time=duration,
            resolution_ps=self._resolution_ps,
        )

    def get_ittr(
        self,
        duration: float,
        *,
        mode: str = "ITTR-T",
        interval_us: int = 1000,
        channels: Iterable[int] | None = None,
    ) -> ITTRResult:
        self._ensure_connected()
        duration = _check_positive(duration, "duration")
        self._last_ittr = None
        normalized = str(mode).upper().replace("_", "-")
        if normalized not in {"ITTR-T", "ITTR-M"}:
            raise ValueError("mode must be 'ITTR-T' or 'ITTR-M'")
        if int(interval_us) <= 0:
            raise ValueError("interval_us must be positive")
        selected = tuple(range(1, self._channel_count + 1) if channels is None else channels)
        if not selected:
            raise ValueError("channels must contain at least one channel")
        for channel in selected:
            self._validate_channel(int(channel))
        mode_number = MODE_ITTR_T if normalized == "ITTR-T" else MODE_ITTR_M
        mask = sum(1 << (channel - 1) for channel in selected)
        self._sdk.check("EnableITTR", self._dev_id, self._board, mask)
        self._sdk.check("SetFileMode", mode_number, 0, 0)
        self._sdk.check("SetITTRInterval", self._dev_id, self._board, int(interval_us))
        self._sdk.check("SetITTREndMode", 0, 0)
        self._sdk.check("SetStatisticsTime", mode_number, duration)
        blocks = self._collect_memory_task(mode_number, duration)
        overflow = ctypes.c_uint(0)
        try:
            self._sdk.check("GetIttrDataOverflow", self._dev_id, self._board, ctypes.byref(overflow))
            overflow_value: int | None = int(overflow.value)
        except SiminicsError:
            overflow_value = None
        result = ITTRResult(
            mode=normalized,
            channels=selected,
            integration_time=duration,
            interval_us=int(interval_us),
            raw_blocks=blocks,
            data_overflow=overflow_value,
        )
        self._last_ittr = result
        return result

    def get_coincidence(
        self,
        duration: float,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: float = 0,
        unit: str = "ns",
        window_start: float | None = None,
        window_stop: float | None = None,
        method: str = "software",
    ) -> CoincidenceResult:
        if method != "hardware":
            return super().get_coincidence(
                duration, ch_start, ch_stop, ch_stop_delay, unit, window_start, window_stop, method
            )
        self._ensure_connected()
        duration = _check_positive(duration, "duration")
        self._validate_channel(ch_start)
        self._validate_channel(ch_stop)
        if ch_start == ch_stop:
            raise ValueError("coincidence channels must be different")
        if unit not in {"ns", "ps", "ms"}:
            raise ValueError("unit must be 'ps', 'ns', or 'ms'")
        if window_start is not None or window_stop is not None:
            if window_start is None or window_stop is None or float(window_stop) <= float(window_start):
                raise ValueError("window_start and window_stop must form a positive interval")
            width = float(window_stop) - float(window_start)
        else:
            width = 1000.0 if unit == "ns" else (1_000_000.0 if unit == "ps" else 0.001)
        width_ns = width * {"ps": 1e-3, "ns": 1.0, "ms": 1e6}[unit]
        self._sdk.check("DmtchInitialize", self._dev_id, self._board)
        self._sdk.check("DmtchModeSelection", self._dev_id, 0)
        self._sdk.check("SetFileMode", MODE_CO, 0, 0)
        channels = (ctypes.c_int * 2)(ch_start - 1, ch_stop - 1)
        self._sdk.check(
            "DmtchAddStrategy", 1, channels, 2, round(width_ns), float(duration), 0, 0.0, 0
        )
        self._sdk.check("SetStatisticsTime", MODE_CO, duration)
        self._sdk.check("StartTask", MODE_CO)
        self._active_mode = MODE_CO
        try:
            self._wait_task(timeout=self._task_timeout)
            count = int(self._sdk.invoke("DmtchGetStratgyCount", 1))
            start_count = self._sdk.signal_status(self._dev_id, self._board, ch_start - 1)[1]
            stop_count = self._sdk.signal_status(self._dev_id, self._board, ch_stop - 1)[1]
        finally:
            try:
                self._sdk.invoke("StopTask", MODE_CO)
            except Exception:
                logger.debug("Siminics coincidence task stop failed", exc_info=True)
            finally:
                self._active_mode = None
        return CoincidenceResult(
            count=count,
            channel1_rate=float(start_count) / duration,
            channel2_rate=float(stop_count) / duration,
            integration_time=duration,
            order=2,
            window_ps=round(width_ns * 1000.0),
            accidental_method=None,
            method="hardware",
        )

    @classmethod
    def discover_devices(cls) -> list[DeviceInfo]:
        if sys.platform != "win32":
            return []
        sdk = SiminicsSDK()
        found: list[DeviceInfo] = []
        try:
            sdk.init()
            for dev_id in range(8):
                try:
                    if not sdk.connected(dev_id):
                        continue
                    dev_type = sdk.device_type(dev_id)
                    serial = sdk.serial_number(dev_id)
                    name = MODEL_NAMES.get(dev_type, f"0x{dev_type:x}")
                    found.append(
                        DeviceInfo(
                            backend_name="siminics",
                            device_path=f"siminics://{dev_id}",
                            serial_number=serial,
                            description=f"Siminics {name}",
                            transport="usb",
                        )
                    )
                except Exception:
                    logger.debug("Failed to inspect Siminics device %d", dev_id, exc_info=True)
        except (SiminicsError, OSError):
            return []
        finally:
            try:
                sdk.uninit()
            except (SiminicsError, OSError):
                logger.debug("Siminics discovery cleanup failed", exc_info=True)
        return found

