"""CIQTEK TDC1610 Backend implementation.

Wraps the vendor ``Tdc1610`` SDK (kept unmodified under ``libs/``) to
integrate the CIQTEK (国仪量子) TDC1610 time-to-digital converter into the
``tdc`` framework.

Hardware / SDK notes
--------------------
* The TDC1610 is an Ethernet-connected instrument whose vendor DLL
  (``TDC1610DLL_x64.dll``) is a **Windows x64** shared library, so talking to
  real hardware is only possible on Windows.  On other platforms the backend
  imports fine but ``connect()`` raises ``ImportError``.
* The instrument exposes 1 start input and 16 stop inputs.  This backend uses
  the unified 1-based channel mapping::

      physical channel 1  -> SDK start  channel 0
      physical channel 2  -> SDK stop   channel 1
      ...
      physical channel 17 -> SDK stop   channel 16

* Thresholds are expressed in **millivolts** (mV, range ``-5000..5000``) and
  delays in **picoseconds** (ps, range ``-200000..200000``), i.e. the native
  units of the vendor SDK.
* ``GetCollectDataByUserEx`` only returns per-channel **histogram** data
  (non-zero bins); the SDK has no raw per-event timestamp stream.  The
  histogram of every stop channel is measured **relative to the start
  (trigger) event** (in internal-trigger mode, relative to the internal
  clock trigger).  ``get_timestamps()`` / ``compute_g2()`` are therefore
  intentionally unsupported and raise ``NotImplementedError``.
"""

from __future__ import annotations

import logging
import time
from ctypes import c_ulonglong
from typing import List, Optional

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import CoincidenceResult, DeviceInfo, G2Result, SinglesResult, TimestampResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TDC1610 hardware constants
# ---------------------------------------------------------------------------

CHANNEL_COUNT = 17  # 1 start + 16 stop inputs
DEFAULT_RESOLUTION_PS = 8  # allowed: 8, 16, 32, 64, 128, 256, 1024 ps
DEFAULT_DYNAMIC_RANGE_PS = 100_000  # collection window (vendor example uses 100 ns)
DEFAULT_DRAW_WINDOW_PS = 4_000_000  # draw window (must be <= dynamic range)
DEFAULT_CLOCK_PERIOD_NS = 100_000_000  # internal trigger period (ns), multiple of 4
DEFAULT_THRESHOLD_MV = 500.0

# Vendor SDK files are kept unmodified under libs/.  Importing the
# module is safe on every platform; the DLL is only loaded when a ``Tdc1610``
# instance is created.
try:
    from qtools.tdc.backends.ciqtek.libs.tdc1610SDK import TDC_CALLBACK, Tdc1610

    TDC1610_SDK_AVAILABLE = True
except Exception:  # pragma: no cover - defensive import guard
    TDC_CALLBACK = None
    Tdc1610 = None
    TDC1610_SDK_AVAILABLE = False


def _error_message(code: int) -> str:
    """Best-effort translation of a TDC1610 error code to a readable message."""
    try:
        from qtools.tdc.backends.ciqtek.libs.errorCode import ErrorCode
    except Exception:
        return "unknown error"
    if code in ErrorCode:
        return ErrorCode[code]
    # Codes > 65535 encode the offending channel in the high 16 bits.
    if code > 0xFFFF:
        channel = code >> 16
        inner = ErrorCode.get(code & 0xFFFF, "unknown error")
        return f"channel {channel}: {inner}"
    return "unknown error"


@register_backend("tdc1610")
class TDC1610Backend(TDCBackend):
    """Backend for the CIQTEK TDC1610 time-to-digital converter.

    See the module docstring for the channel mapping, units, and platform
    requirements.
    """

    def __init__(self, device_path: Optional[str] = None) -> None:
        self._device_path = device_path
        self._dev = None  # vendor Tdc1610 SDK instance
        self._connected = False
        self._collecting = False
        self._error_callback = None

        # Configuration state (mirrors the vendor example's global arrays).
        self._trigger_mode = 0  # 0 = external trigger, 1 = internal
        self._clock_period_ns = DEFAULT_CLOCK_PERIOD_NS
        self._resolution_ps = float(DEFAULT_RESOLUTION_PS)
        self._dynamic_range_ps = DEFAULT_DYNAMIC_RANGE_PS
        self._draw_window_ps = DEFAULT_DRAW_WINDOW_PS

        # Per-channel config, SDK channel order: index 0 = start, 1..16 = stop1..16.
        self._channel_enable = [1] * CHANNEL_COUNT
        self._channel_mode = [0] * CHANNEL_COUNT  # 0 = rising edge, 1 = falling
        self._channel_range = [DEFAULT_THRESHOLD_MV] * CHANNEL_COUNT
        self._channel_delay = [0] * CHANNEL_COUNT

    # -- identity properties ------------------------------------------------

    @property
    def name(self) -> str:
        return "tdc1610"

    @property
    def vendor(self) -> str:
        return "CIQTEK (国仪量子)"

    @property
    def channel_count(self) -> int:
        # 1 start input + 16 stop inputs.
        return CHANNEL_COUNT

    @property
    def capabilities(self) -> BackendCapability:
        # TIMESTAMPS / G2 are intentionally NOT advertised: the vendor SDK
        # only returns per-channel histograms, never raw timestamp streams.
        return (
            BackendCapability.SINGLES
            | BackendCapability.COINCIDENCE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return self._resolution_ps

    # -- helpers -------------------------------------------------------------

    def _ensure_sdk(self):
        """Return the vendor SDK instance, loading it on first use."""
        if self._dev is not None:
            return self._dev
        if not TDC1610_SDK_AVAILABLE or Tdc1610 is None:
            raise ImportError(
                "The TDC1610 vendor SDK (tdc.backends.ciqtek.libs.tdc1610SDK) "
                "could not be imported."
            )
        try:
            sdk = Tdc1610()
        except Exception as e:
            # The vendor SDK caches its singleton even when __init__ fails;
            # clear it so a later attempt can retry.
            try:
                if getattr(Tdc1610, "_instance", None) is not None:
                    Tdc1610._instance = None
            except Exception:
                pass
            raise ImportError(
                "Unable to load the TDC1610 SDK (TDC1610DLL_x64.dll). "
                "The TDC1610 backend requires Windows with the vendor DLL: "
                f"{e}"
            ) from e
        self._dev = sdk
        return sdk

    def _ensure_connected(self) -> None:
        if not self._connected or self._dev is None:
            raise RuntimeError("Device not connected")

    def _check(self, ret: int, operation: str) -> None:
        """Raise a RuntimeError when a vendor SDK call returns a non-zero code."""
        if ret == 0:
            return
        raise RuntimeError(
            f"TDC1610 {operation} failed with error code {ret}: {_error_message(ret)}"
        )

    @staticmethod
    def _to_sdk_channel(channel: int) -> int:
        """Convert a 1-based physical channel to the vendor SDK channel index."""
        if not (1 <= channel <= CHANNEL_COUNT):
            raise ValueError(f"Invalid channel index: {channel}")
        return channel - 1

    def _resolve_device(self, device_path, kwargs):
        """Resolve a vendor ``FindDevice`` entry from the user-supplied path.

        Accepts, in order of precedence:
          * ``kwargs["dev_info"]`` — a full vendor device entry
            ``[index, local_ip, des_ip, dst_mac, dst_name]``;
          * ``device_path`` as a list/tuple with the same shape;
          * ``device_path`` as ``"eth://<ip>"`` or a bare IP string, matched
            against the discovered device list;
          * ``None`` — the first discovered device.
        """
        dev_info = kwargs.get("dev_info")
        if dev_info is not None:
            if not (isinstance(dev_info, (list, tuple)) and len(dev_info) >= 4):
                raise ValueError("dev_info must be a vendor device entry of length >= 4")
            return list(dev_info)

        if isinstance(device_path, (list, tuple)):
            if len(device_path) < 4:
                raise ValueError("device_path must be a vendor device entry of length >= 4")
            return list(device_path)

        ret, devlist = self._dev.FindDevice()
        if ret != 0:
            raise ConnectionError(f"TDC1610 device search failed with error code {ret}")
        if not devlist:
            raise ConnectionError(
                "No TDC1610 devices found on the network. "
                "Power on the device and check the Ethernet connection."
            )

        target = device_path or self._device_path
        if target is None:
            return list(devlist[0])

        ip = str(target)
        if ip.startswith("eth://"):
            ip = ip[len("eth://"):]
        for dev in devlist:
            if dev[2] == ip:
                return list(dev)
        raise ConnectionError(
            f"No TDC1610 device found with address {target!r}. "
            f"Discovered: {[d[2] for d in devlist]}"
        )

    def _ensure_calibrated(self) -> None:
        """Run code-density calibration when the device reports it is required."""
        result = self._dev.TdcGetCalibrationResult()
        if result == 0:
            return
        logger.info("TDC1610 calibration required, running code-density calibration...")
        self._check(self._dev.TdcSetCalibration(), "TdcSetCalibration")
        for _ in range(30):
            time.sleep(1)
            if self._dev.TdcGetCalibrationResult() == 0:
                return
        raise RuntimeError("TDC1610 calibration did not complete in time")

    def _apply_channel_config(self) -> None:
        """Push the stored per-channel enable/mode/threshold/delay to the device."""
        self._ensure_connected()
        was_collecting = self._collecting
        if was_collecting:
            self.stop_collect()
        try:
            sdk = self._dev
            self._check(
                sdk.ConfigStartSwitch(int(self._channel_enable[0]), int(self._channel_mode[0])),
                "ConfigStartSwitch",
            )
            self._check(
                sdk.ConfigStartChannel(int(self._channel_range[0]), int(self._channel_delay[0])),
                "ConfigStartChannel",
            )
            self._check(
                sdk.ConfigStopSwitchSZ(list(self._channel_enable[1:]), list(self._channel_mode[1:])),
                "ConfigStopSwitchSZ",
            )
            for i in range(1, CHANNEL_COUNT):
                self._check(
                    sdk.ConfigStopChannel(i, int(self._channel_range[i]), int(self._channel_delay[i])),
                    f"ConfigStopChannel({i})",
                )
        finally:
            if was_collecting:
                self.start_collect()

    def _apply_configuration(self, **kwargs) -> None:
        """Apply trigger / clock / channel / window configuration to the device."""
        self._ensure_connected()
        was_collecting = self._collecting
        if was_collecting:
            self.stop_collect()
        try:
            self.set_trigger_mode(kwargs.get("trigger_mode", self._trigger_mode))
            self.set_clock_period(kwargs.get("clock_period_ns", self._clock_period_ns))
            self._apply_channel_config()
            self.set_time_resolution(kwargs.get("resolution_ps", self._resolution_ps))
            self.set_dynamic_range(kwargs.get("dynamic_range_ps", self._dynamic_range_ps))
            self.set_draw_window(kwargs.get("draw_window_ps", self._draw_window_ps))
            self.set_clock(
                kwargs.get("clock_input_type", 0),
                kwargs.get("clock_input_value", 1),
                kwargs.get("clock_output", 0),
            )
            self.set_collect_time(kwargs.get("collect_time_ms", 0))
            self.set_fresh_time(kwargs.get("fresh_time_s", 0))
        finally:
            if was_collecting:
                self.start_collect()

    # -- connection management ----------------------------------------------

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        sdk = self._ensure_sdk()
        try:
            dev = self._resolve_device(device_path, kwargs)

            if kwargs.get("error_callback") is not None:
                self.set_error_callback(kwargs["error_callback"])

            ret = sdk.ConnectDevice(dev)
            self._check(ret, "ConnectDevice")
            self._connected = True

            if isinstance(device_path, str):
                self._device_path = device_path
            elif self._device_path is None and len(dev) > 2:
                self._device_path = f"eth://{dev[2]}"

            if kwargs.get("calibrate", True):
                self._ensure_calibrated()
            self._apply_configuration(**kwargs)
        except Exception:
            self._connected = False
            raise

    def disconnect(self) -> None:
        if not self._connected or self._dev is None:
            return
        logger.info("Disconnecting TDC1610")
        try:
            if self._collecting:
                self.stop_collect()
            ret = self._dev.DisConnectDevice()
            if ret != 0:
                logger.warning("TDC1610 DisConnectDevice returned error code %d", ret)
        except Exception as e:
            logger.warning("Error while disconnecting TDC1610: %s", e)
        self._dev = None
        self._connected = False
        self._collecting = False

    def is_connected(self) -> bool:
        return self._connected

    # -- data acquisition ---------------------------------------------------

    def get_singles(self, integration_time: float) -> SinglesResult:
        """Acquire singles count rates.

        The TDC1610 reports count rates directly (``GetCpsByUser``), so the
        returned counts are reconstructed as ``rate * integration_time``.
        """
        self._ensure_connected()
        if integration_time <= 0:
            raise ValueError(f"integration_time must be positive, got {integration_time}")

        if not self._collecting:
            self.start_collect()
        try:
            t0 = time.perf_counter()
            time.sleep(integration_time)
            ret, is_new, cps_list = self._dev.GetCpsByUser()
            self._check(ret, "GetCpsByUser")
            actual_duration = time.perf_counter() - t0
        finally:
            self.stop_collect()

        # SDK returns 17 rates: [start, stop1 .. stop16] (physical channels 1..17).
        rates = np.asarray(cps_list, dtype=np.float64)
        if rates.size < CHANNEL_COUNT:
            padded = np.zeros(CHANNEL_COUNT, dtype=np.float64)
            padded[: rates.size] = rates
            rates = padded

        counts = (rates * actual_duration).astype(np.uint64)
        return SinglesResult(
            integration_time=actual_duration,
            counts=counts,
            count_rates=rates,
        )

    def get_timestamps(
        self,
        duration: float,
        *,
        channels: Optional[List[int]] = None,
    ) -> TimestampResult:
        """Raw per-event timestamps are not supported by the TDC1610 SDK.

        The vendor SDK only exposes per-channel **histograms** (time spectra)
        via ``GetCollectDataByUserEx`` — there is no raw timestamp stream API,
        so this method always raises.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "The TDC1610 backend cannot provide raw per-event timestamps: "
            "the vendor SDK only returns per-channel histograms (time "
            "spectra). Use get_singles() for count rates or "
            "get_accord_counts() for hardware coincidence counts."
        )

    def get_g2(
        self,
        duration: float,
        bins: int = 500,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        bin_offset: int = 0,
        unit: str = "ns",
        method: str = "software",
    ) -> G2Result:
        """Software g² correlation is not supported by the TDC1610 backend.

        Software correlation requires raw per-event timestamps, which the
        vendor SDK does not provide (only per-channel histograms), so this
        method always raises.

        Raises:
            NotImplementedError: Always.
        """
        if method not in ("software", "hardware"):
            raise ValueError(
                f"Unsupported g2 method: {method!r}. "
                "Expected 'software' or 'hardware'."
            )
        raise NotImplementedError(
            "The TDC1610 backend cannot compute g2: software correlation "
            "requires raw per-event timestamps, which the vendor SDK does "
            "not provide (only per-channel histograms). Use "
            "get_accord_counts() for hardware coincidence counts instead."
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
        """Acquire CIQTEK's hardware accord counter.

        TDC1610 has a fixed start trigger (physical channel 1). The accord
        gate has a configurable width anchored at the start channel. The
        stop-channel delay positions the stop signal, and ``window_stop`` is
        the gate width. ``window_start`` is accepted only as an explicit zero.
        """
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
        if ch_start != 1:
            raise ValueError("TDC1610 hardware coincidence uses fixed trigger channel 1")
        if not (2 <= ch_stop <= CHANNEL_COUNT):
            raise ValueError("TDC1610 hardware coincidence stop channels must be 2..17")
        if window_stop is None:
            raise ValueError("TDC1610 hardware coincidence requires window_stop")
        if window_start is not None and float(window_start) != 0:
            raise ValueError("TDC1610 hardware coincidence window_start is fixed at 0")

        unit_to_ps = {"ps": 1.0, "ns": 1e3, "ms": 1e6}
        if unit not in unit_to_ps:
            raise ValueError(f"Unsupported unit: {unit!r}. Expected 'ps', 'ns', or 'ms'.")
        factor = unit_to_ps[unit]
        start_ps = 0.0
        stop_ps = float(window_stop) * factor
        width_ps = int(round(stop_ps))
        if width_ps <= 0:
            raise ValueError("window_stop must be positive")
        if width_ps % int(self.resolution_ps) != 0:
            raise ValueError(
                f"hardware window width must be a multiple of {self.resolution_ps:g} ps"
            )

        stop_channels = [ch_stop]
        delay_ps = int(round(float(ch_stop_delay) * factor))
        if not -200_000 <= delay_ps <= 200_000:
            raise ValueError("TDC1610 channel delay must be within [-200000, 200000] ps")
        self._ensure_connected()
        self.set_channel_config(channels=stop_channels, delay=delay_ps)
        self.configure_accord(width_ps, ch_start, ch_stop)
        self.set_algorithm(0x02)

        started_here = not self._collecting
        started = time.perf_counter()
        try:
            if started_here:
                self.start_collect()
            time.sleep(duration)
        finally:
            if started_here:
                self.stop_collect()
        actual_duration = time.perf_counter() - started
        values = self.get_accord_counts()
        if len(values) < 4:
            raise RuntimeError(f"TDC1610 accord response has {len(values)} fields; expected 4")
        accidental_count = (
            float(values[1])
            * float(values[2])
            * (width_ps * 1e-12)
            * actual_duration
        )
        return CoincidenceResult(
            count=int(values[0]),
            acc_count_perbin=None,
            accidental_count=accidental_count,
            accidental_method="rate_product",
            channel1_rate=float(values[1]),
            channel2_rate=float(values[2]),
            channel3_rate=None,
            integration_time=actual_duration,
            order=2,
            window_ps=width_ps,
            window_start_ps=start_ps,
            window_stop_ps=stop_ps,
            method="hardware",
        )

    # -- threshold control --------------------------------------------------

    def set_threshold(
        self,
        threshold: float,
        channel: int | None = None,
    ) -> None:
        """Set the channel threshold voltage.

        Note: TDC1610 thresholds are in **millivolts** (range ``-5000..5000``).
        ``channel=None`` applies the value to every channel.
        """
        self._ensure_connected()
        channels = range(1, self.channel_count + 1) if channel is None else [channel]
        for ch in channels:
            if not (1 <= ch <= self.channel_count):
                raise ValueError(f"Invalid channel index: {ch}")
            self._channel_range[ch - 1] = float(threshold)
        self._apply_channel_config()

    # -- device discovery ---------------------------------------------------

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        """Discover TDC1610 devices via the vendor ``FindDevice`` network search."""
        devices: List[DeviceInfo] = []
        if not TDC1610_SDK_AVAILABLE or Tdc1610 is None:
            return devices
        try:
            sdk = Tdc1610()
        except Exception as e:
            logger.debug("TDC1610 SDK unavailable during discovery: %s", e)
            return devices
        try:
            ret, devlist = sdk.FindDevice()
            if ret != 0:
                logger.warning("TDC1610 discovery failed with error code %d", ret)
                return devices
            for dev in devlist:
                if len(dev) < 3:
                    continue
                devices.append(
                    DeviceInfo(
                        backend_name="tdc1610",
                        device_path=f"eth://{dev[2]}",
                        serial_number=str(dev[4]) if len(dev) > 4 else None,
                        description=str(dev[3]) if len(dev) > 3 else "CIQTEK TDC1610 TDC",
                    )
                )
        except Exception as e:
            logger.warning("TDC1610 discovery failed: %s", e)
        return devices

    # -----------------------------------------------------------------------
    # TDC1610 SDK extensions (NOT part of the TDCBackend interface)
    #
    # These thin wrappers expose vendor-specific capabilities that the common
    # TDCBackend interface does not reserve: low-level collection control,
    # trigger/clock/window configuration, code-density calibration, hardware
    # coincidence counting, QRNG, and the mark trigger.
    # -----------------------------------------------------------------------

    def set_error_callback(self, callback) -> None:
        """Register a low-level SDK error callback (``CFUNCTYPE(None, c_int, c_int, c_void_p)``)."""
        self._ensure_connected()
        if TDC_CALLBACK is None:
            raise RuntimeError("TDC1610 SDK callback type unavailable")
        cb = callback if isinstance(callback, TDC_CALLBACK) else TDC_CALLBACK(callback)
        self._error_callback = cb  # keep a reference so the callback is not GC'd
        ret = self._dev.SetErrorCallback(cb)
        self._check(ret, "SetErrorCallback")

    def start_collect(self) -> None:
        """Start data collection (TDC1610 extension)."""
        self._ensure_connected()
        if self._collecting:
            return
        ret = self._dev.StartCollect()
        self._check(ret, "StartCollect")
        self._collecting = True

    def stop_collect(self) -> None:
        """Stop data collection (TDC1610 extension)."""
        if not self._connected or self._dev is None or not self._collecting:
            return
        try:
            ret = self._dev.StopCollect()
            if ret != 0:
                logger.warning("TDC1610 StopCollect returned error code %d", ret)
        finally:
            self._collecting = False

    def set_trigger_mode(self, mode: int) -> None:
        """Set trigger mode: 0 = external, 1 = internal (TDC1610 extension)."""
        self._ensure_connected()
        self._trigger_mode = int(mode)
        self._check(self._dev.ConfigTdcTriggerMode(self._trigger_mode), "ConfigTdcTriggerMode")

    def set_clock_period(self, period_ns: int) -> None:
        """Set internal clock trigger period in ns ``[100, 1e9]``, multiple of 4."""
        self._ensure_connected()
        self._clock_period_ns = int(period_ns)
        self._check(self._dev.ConfigClockPeriod(self._clock_period_ns), "ConfigClockPeriod")

    def set_time_resolution(self, resolution_ps: int) -> None:
        """Set time resolution: 8, 16, 32, 64, 128, 256, or 1024 ps."""
        self._ensure_connected()
        allowed = (8, 16, 32, 64, 128, 256, 1024)
        value = int(resolution_ps)
        if value not in allowed:
            raise ValueError(f"Invalid TDC1610 resolution: {value} ps (allowed: {allowed})")
        self._resolution_ps = float(value)
        self._check(self._dev.ConfigTimeResolution(value), "ConfigTimeResolution")

    def set_dynamic_range(self, dynamic_range_ps: int) -> None:
        """Set collection window in ps (max ``resolution x (2^32 - 1) - 4000`` ps)."""
        self._ensure_connected()
        self._dynamic_range_ps = int(dynamic_range_ps)
        self._check(self._dev.ConfigDynamicRange(self._dynamic_range_ps), "ConfigDynamicRange")

    def set_draw_window(self, draw_window_ps: int) -> None:
        """Set draw window in ps (<= dynamic range; max 12,500,000 points x resolution)."""
        self._ensure_connected()
        self._draw_window_ps = int(draw_window_ps)
        self._check(self._dev.ConfigDrawWindowRange(self._draw_window_ps), "ConfigDrawWindowRange")

    def set_clock(self, input_type: int = 0, input_value: int = 1, output: int = 0) -> None:
        """Set clock config: ``input_type`` 0=internal/1=external; freq 0=10M/1=100M."""
        self._ensure_connected()
        self._check(
            self._dev.ConfigClock(int(input_type), int(input_value), int(output)),
            "ConfigClock",
        )

    def set_collect_time(self, collect_time_ms: int) -> None:
        """Auto-stop collection after ``ms`` (``[0, 360000000]``, 0 disables)."""
        self._ensure_connected()
        self._check(self._dev.TdcSetCollectTime(int(collect_time_ms)), "TdcSetCollectTime")

    def set_fresh_time(self, fresh_time_s: int) -> None:
        """Set refresh-mode clear time in s (``[0, 86400]``, 0 disables)."""
        self._ensure_connected()
        self._check(self._dev.TdcSetFreshTime(int(fresh_time_s)), "TdcSetFreshTime")

    def set_channel_config(
        self,
        channels: Optional[List[int]] = None,
        enable: Optional[int] = None,
        mode: Optional[int] = None,
        threshold: Optional[float] = None,
        delay: Optional[int] = None,
    ) -> None:
        """Batch-configure channels: enable (0/1), edge mode (0 rising/1 falling),
        threshold (mV), delay (ps).  ``channels=None`` applies to all 17."""
        self._ensure_connected()
        chs = range(1, CHANNEL_COUNT + 1) if channels is None else list(channels)
        for ch in chs:
            if not (1 <= ch <= CHANNEL_COUNT):
                raise ValueError(f"Invalid channel index: {ch}")
            i = ch - 1
            if enable is not None:
                self._channel_enable[i] = int(enable)
            if mode is not None:
                self._channel_mode[i] = int(mode)
            if threshold is not None:
                self._channel_range[i] = float(threshold)
            if delay is not None:
                self._channel_delay[i] = int(delay)
        self._apply_channel_config()

    def calibrate(self, timeout: float = 30.0) -> int:
        """Run code-density calibration and wait (up to ``timeout`` s) for completion."""
        self._ensure_connected()
        self._check(self._dev.TdcSetCalibration(), "TdcSetCalibration")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._dev.TdcGetCalibrationResult()
            if result == 0:
                return 0
            time.sleep(1)
        raise RuntimeError("TDC1610 calibration did not complete in time")

    def get_calibration_result(self) -> int:
        """Read the code-density calibration result (0 = calibrated)."""
        self._ensure_connected()
        return self._dev.TdcGetCalibrationResult()

    def get_cps(self) -> List[float]:
        """Read current count rates in counts/s: ``[0]`` = start, ``[1..16]`` = stops."""
        self._ensure_connected()
        ret, is_new, cps_list = self._dev.GetCpsByUser()
        self._check(ret, "GetCpsByUser")
        return [float(x) for x in cps_list]

    def set_algorithm(self, algorithm_bits: int) -> None:
        """Enable algorithms by bitmask: 0x01 random, 0x02 2-fold accord, 0x04 3-fold accord, 0x08 mark."""
        self._ensure_connected()
        self._check(self._dev.TdcSetAlgorithmType(int(algorithm_bits)), "TdcSetAlgorithmType")

    def reset_algorithm(self, algorithm_bits: int) -> None:
        """Disable algorithm bits (same bitmask as :meth:`set_algorithm`)."""
        self._ensure_connected()
        self._check(self._dev.TdcResetAlgorithmType(int(algorithm_bits)), "TdcResetAlgorithmType")

    def configure_accord(
        self,
        code_width_ps: int,
        channel1: int,
        channel2: int,
        channel3: Optional[int] = None,
    ) -> None:
        """Configure 2-fold/3-fold hardware coincidence counting.

        ``channel1/2/3`` are **1-based physical channels** (1 = start, 2..17 =
        stop1..16).  ``code_width_ps`` is the coincidence gate width and must
        be an integer multiple of the configured resolution.  Remember to
        enable the accord algorithm bit (0x02 for 2-fold, 0x04 for 3-fold)
        with :meth:`set_algorithm` before ``start_collect()``, then read the
        result with :meth:`get_accord_counts`.
        """
        self._ensure_connected()
        ch1 = self._to_sdk_channel(channel1)
        ch2 = self._to_sdk_channel(channel2)
        if channel3 is None:
            ret = self._dev.TdcConfigAlgorithmAccord(
                c_ulonglong(int(code_width_ps)), ch1, ch2
            )
        else:
            ret = self._dev.TdcConfigAlgorithmAccord(
                c_ulonglong(int(code_width_ps)), ch1, ch2, self._to_sdk_channel(channel3)
            )
        self._check(ret, "TdcConfigAlgorithmAccord")

    def get_accord_counts(self) -> List[int]:
        """Read coincidence counts: ``[accord_count, ch1_cps, ch2_cps, ch3_cps]``."""
        self._ensure_connected()
        ret, data = self._dev.GetAccordByUser()
        self._check(ret, "GetAccordByUser")
        return [int(x) for x in data]

    def configure_random(
        self,
        channel1: int,
        channel2: int,
        save_count: int,
        code_width: int = 100,
    ) -> None:
        """Configure QRNG (random-number) acquisition.

        ``channel1/2`` are **1-based physical channels** (1 = start, 2..17 =
        stop1..16).  Enable the random algorithm bit (0x01) with
        :meth:`set_algorithm` before ``start_collect()``.
        """
        self._ensure_connected()
        ret = self._dev.TdcConfigAlgorithmRandom(
            self._to_sdk_channel(channel1),
            self._to_sdk_channel(channel2),
            int(save_count),
            int(code_width),
        )
        self._check(ret, "TdcConfigAlgorithmRandom")

    def get_random_bits(self, bits: int = 40) -> bytes:
        """Read the last ``bits`` random bits from the QRNG (raw ``bytes``)."""
        self._ensure_connected()
        ret, data = self._dev.TdcGetRandomLastBits(int(bits))
        self._check(ret, "TdcGetRandomLastBits")
        return data

    def save_random(self, path: str = "") -> None:
        """Save generated random numbers to a file (directory or ``.txt`` path)."""
        self._ensure_connected()
        ret = self._dev.TdcSaveRandom(path)
        self._check(ret, "TdcSaveRandom")

    def configure_mark(self, enable: int, mode: int = 0, threshold: int = 500) -> None:
        """Configure the mark trigger: enable (0/1), mode (0 external/1 internal),
        threshold (mV).  Enable the mark algorithm bit (0x08) via
        :meth:`set_algorithm` before ``start_collect()``."""
        self._ensure_connected()
        ret = self._dev.ConfigMark(int(enable), int(mode), int(threshold))
        self._check(ret, "ConfigMark")

    def set_mark_max_delay(self, max_delay_ps: int) -> None:
        """Set the mark max signal period; mark auto-disables when no signal arrives."""
        self._ensure_connected()
        self._check(self._dev.TdcSetMarkMaxDelay(int(max_delay_ps)), "TdcSetMarkMaxDelay")

    def set_mark_save_path(self, path: str = "") -> None:
        """Set the folder where mark files are saved (``Markfile`` subfolder)."""
        self._ensure_connected()
        ret = self._dev.ConfigMarkSavePath(path)
        self._check(ret, "ConfigMarkSavePath")

    def get_mark_status(self) -> int:
        """Mark status: 0 = off, 1 = enabled without signal, 2 = enabled with signal."""
        self._ensure_connected()
        ret, status = self._dev.TdcGetMarkDelayStatus()
        self._check(ret, "TdcGetMarkDelayStatus")
        return int(status)
