"""TDC measurement orchestration.

Wraps a TDCBackend and provides high-level measurement routines:
singles, pairs (g²), triplets, and N-fold gate coincidences.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

import numpy as np

from qtools.tdc.analysis.efficiency import compute_pairs
from qtools.tdc.analysis.g2 import (
    compute_gate_coincidence,
    compute_gate_photons,
    compute_triplet_g2,
)
from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.data import (
    CoincidenceResult,
    DeviceInfo,
    HeraldingGateResult,
    MultiCoincidenceResult,
    SinglesResult,
    TimestampResult,
    combine_samples,
    time_to_ps,
    validate_bin_width,
)

logger = logging.getLogger(__name__)

_MAX_SINGLES_RETRIES = 20


class TDC:
    """High-level measurements with a shared analysis bin width in ps.

    An omitted per-measurement bin_width uses the constructor default, then
    the native timestamp resolution if no default was configured.
    """

    def __init__(
        self,
        backend: TDCBackend | str | DeviceInfo,
        port: str | None = None,
        *,
        bin_width: int | None = None,
        **kwargs,
    ) -> None:
        """Wrap a backend or create one by name, with a default bin width in ps.

        Enter the context to connect. Per-measurement bin_width overrides
        this default; None uses the native timestamp resolution.
        Additional keyword arguments configure a newly created backend.
        """
        self.bin_width = None if bin_width is None else validate_bin_width(bin_width)
        if isinstance(backend, DeviceInfo):
            if port is not None:
                raise TypeError("port must be omitted when backend is a DeviceInfo")
            port = backend.device_path
            backend = backend.backend_name
        if isinstance(backend, str):
            from qtools.tdc.connection import get_backend

            backend = get_backend(backend)(port, **kwargs)
        elif port is not None or kwargs:
            raise TypeError(
                "port and backend options require a backend name or DeviceInfo"
            )
        self.backend = backend

    def _bin_width(self, override: int | None) -> int | None:
        """Resolve an analysis override without changing the instance default."""
        width = self.bin_width if override is None else override
        return None if width is None else validate_bin_width(width)

    def __enter__(self) -> "TDC":
        self.backend.connect()

        return self

    def __exit__(self, *args: object) -> None:
        self.backend.disconnect()

    def set_threshold(
        self,
        threshold_or_channel: float | int | None = None,
        threshold: float | None = None,
        *,
        channel: int | None = None,
    ) -> None:
        """Set threshold voltage.

        Thresholds are expressed in volts (V) at this public API boundary.

        Supports flexible signatures for both global devices (e.g. S15 TDC1)
        and per-channel devices (e.g. IDQ):

          - ``tdc.set_threshold(0.6)``: Set global threshold value.
          - ``tdc.set_threshold(1, 0.6)``: Set threshold for channel 1.
          - ``tdc.set_threshold(channel=1, threshold=0.6)``: Set threshold for channel 1.

        Args:
            threshold_or_channel: Threshold value (if single arg) or channel index.
            threshold: Threshold value (if channel is passed first or as keyword).
            channel: Keyword argument for channel index (0-based).
        """
        if channel is not None:
            ch = channel
            if threshold is None:
                if threshold_or_channel is None:
                    raise TypeError("threshold is required when channel is specified")
                val = float(threshold_or_channel)
            else:
                val = float(threshold)
        elif threshold is None:
            if threshold_or_channel is None:
                raise TypeError("threshold is required")
            ch = None
            val = float(threshold_or_channel)
        else:
            if threshold_or_channel is None:
                raise TypeError("channel is required when threshold is positional")
            ch = int(threshold_or_channel)
            val = float(threshold)

        self.backend.set_threshold(val, channel=ch)

    @property
    def threshold(self) -> float:
        """Get the cached default/global threshold in volts."""
        return float(self.backend.get_threshold())

    @threshold.setter
    def threshold(self, val: float) -> None:
        """Set global threshold voltage."""
        self.set_threshold(val)

    # -- singles --------------------------------------------------------------

    def _acquire_singles(self, duration: float) -> SinglesResult:
        """Acquire singles data with robustness retries.

        Args:
            duration: Integration time in seconds.

        Returns:
            A ``SinglesResult`` with counts and count_rates.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        for attempt in range(_MAX_SINGLES_RETRIES):
            try:
                res = self.backend.get_singles(duration)
                inttime = res.duration

                # Integration time validation check (0.75 to 2.0)
                if not (0.75 < inttime / duration < 2.0):
                    logger.warning(
                        "Singles duration check failed: %f vs %f, retrying...",
                        inttime,
                        duration,
                    )
                    continue
                # Raw rates positive check
                if np.any(res.count_rates < 0):
                    logger.warning(
                        "Singles contain negative rates: %s, retrying...",
                        res.count_rates,
                    )
                    continue

                return res
            except Exception as e:
                logger.warning("Error getting singles, retrying: %s", e)
                time.sleep(0.1)

        raise RuntimeError(
            f"Singles acquisition failed after {_MAX_SINGLES_RETRIES} retries (duration={duration})"
        )

    def measure_singles(
        self,
        duration: float,
        samples: int = 1,
    ) -> List[Tuple[float, np.ndarray]]:
        """Perform singles raw-count measurement(s) with robustness retries.

        Args:
            duration: Integration time in seconds.
            samples: Number of measurements to take.

        Returns a list of ``(duration, counts)`` tuples for
        compatibility with the singles CLI.  The backend acquisition itself
        uses the unified :class:`SinglesResult` model.

        Raises:
            RuntimeError: If all retries are exhausted for a measurement.
        """
        results = []
        for _ in range(self._sample_count(samples)):
            res = self._acquire_singles(duration)
            results.append((res.duration, res.counts))

        return results

    def measure_rates(
        self,
        duration: float,
        samples: int = 1,
    ) -> List[Tuple[float, np.ndarray]]:
        """Perform singles count-rate measurement(s) with robustness retries.

        Args:
            duration: Integration time in seconds.
            samples: Number of measurements to take.

        Returns a list of ``(duration, count_rates)`` tuples for
        compatibility with the singles CLI.

        Raises:
            RuntimeError: If all retries are exhausted for a measurement.
        """
        results = []
        for _ in range(self._sample_count(samples)):
            res = self._acquire_singles(duration)
            results.append((res.duration, res.count_rates))

        return results

    def _acquire_timestamp(self, duration: float) -> TimestampResult:
        """Acquire raw timestamp result from backend.

        Args:
            duration: Acquisition duration in seconds.

        Returns:
            A ``TimestampResult`` object containing raw timestamps and channels.
        """
        return self.backend.get_timestamps(duration)

    def measure_timestamps(
        self,
        duration: float,
        unit: str = "ps",
        channels: list[int] | None = None,
    ) -> list[tuple[int, float, np.ndarray]]:
        """Acquire raw timestamp data for the specified duration.

        Args:
            duration: Acquisition duration in seconds.
            unit: Time unit for returned timestamps, either ``'ps'`` or ``'ns'``.
            channels: List of channel indices to filter. If None, auto-detects
                active channels present in the acquisition.

        Returns:
            list of ``(channel, total_time_ns, timestamps)`` 3-tuples, where
            ``timestamps`` is an array of per-channel timestamps in the specified ``unit``.
        """
        res = self._acquire_timestamp(duration)

        ts_ps = res.timestamps
        ch = res.channels
        res_ps = res.resolution_ps
        total_time_ns = res.total_time_ns

        if unit == "ps":
            ts = ts_ps
        elif unit == "ns":
            ts = ts_ps // 1000
            if res_ps < 1000:
                logger.warning(
                    "Converting timestamps from ps to ns loses sub-nanosecond precision"
                )
        else:
            raise ValueError(f"Unsupported unit: {unit}. Expected 'ps' or 'ns'.")

        # filter channels
        if channels is None:
            channels = [int(c) for c in np.sort(np.unique(ch))]

        result = []
        for channel in channels:
            mask = ch == channel
            result.append((channel, total_time_ns, ts[mask]))

        return result

    # -- pairs ----------------------------------------------------------------

    def measure_pairs(
        self,
        duration: float,
        ch_start: int,
        ch_stop: int,
        bins: int = 500,
        peak: int = 0,
        loffset: int = 0,
        roffset: int = 0,
        window_start: Optional[int] = None,
        window_stop: Optional[int] = None,
        delay: int = 0,
        bin_offset: int = 0,
        unit: str = "ns",
        bin_width: int | None = None,
    ) -> dict:
        """Perform a coincidence correlation measurement.

        Calculates coincidences, accidentals, and efficiencies. All window
        parameters are in **bin units**.

        Rates use the backend-reported live acquisition time as their
        denominator (see ``TDCBackend.get_g2``).

        Args:
            duration: Measurement time in seconds.
            ch_start: Start channel index.
            ch_stop: Stop channel index.
            bins: Number of correlation histogram bins.
            bin_width: Analysis bin width in ps, or None for the instance default.
            peak: Center of coincidence window in bins.
            loffset: Left offset of coincidence window in bins.
            roffset: Right offset of coincidence window in bins.
            window_start: Optional start of coincidence window in bins.
            window_stop: Optional stop of coincidence window in bins.
            delay: Time delay in bins to apply to ch_stop (default: 0).
            bin_offset: Start of correlation window in bins.
            unit: Time unit for ``bin_offset`` (used for the correlation
                window; ``delay`` is always expressed in bins).

        Returns:
            A dictionary with keys ``pair_counts``, ``acc_pair_counts``,
            ``raw_pair_rate``, ``net_pair_rate``, ``acc_pair_rate``,
            ``duration``, ``start_rate``, ``stop_rate``, ``eff_start``,
            ``eff_stop``, ``eff_avg``, ``coinc_start``, ``coinc_stop``,
            ``bin_edges``, and ``histogram``.
        """
        width = self._bin_width(bin_width)
        # delay is specified in bins; convert to the time unit expected by
        # backend.get_g2() (ch_stop_delay).
        ch_stop_delay = delay * (self.backend.resolution_ps if width is None else width)
        if unit == "ns":
            ch_stop_delay = ch_stop_delay / 1e3
        elif unit == "us":
            ch_stop_delay = ch_stop_delay / 1e6
        elif unit == "ps":
            pass
        elif unit == "ms":
            ch_stop_delay = ch_stop_delay / 1e9
        else:
            raise ValueError(
                f"Unsupported unit: {unit!r}. Expected 'ns', 'ps', or 'ms'."
            )

        use_start_stop = window_start is not None and window_stop is not None
        if use_start_stop:
            if window_start < bin_offset:
                raise ValueError("window_start cannot be less than bin_offset.")
            if window_stop < window_start:
                raise ValueError("window_stop cannot be less than window_start.")

        else:
            window_start = peak - loffset
            window_stop = peak + roffset

        # Validate bins
        if bins <= 0:
            raise ValueError(f"bins must be positive, got {bins}")

        g2res = self.backend.get_g2(
            duration=duration,
            bins=bins,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            bin_offset=bin_offset,
            unit=unit,
            bin_width=width,
        )

        hist = g2res.histogram[0]
        bin_edges = g2res.bin_edges[0] // g2res.bin_width
        reported_duration = g2res.duration[0]
        if (
            reported_duration is None
            or not np.isfinite(reported_duration)
            or reported_duration <= 0
        ):
            logger.warning(
                "TDC returned invalid duration %r; "
                "falling back to requested duration %.3f s",
                reported_duration,
                duration,
            )
            reported_duration = duration
        singles_start = g2res.singles_start[0]
        singles_stop = g2res.singles_stop[0]

        res_dict = compute_pairs(
            histogram=hist,
            bin_edges=bin_edges,
            singles_start=singles_start,
            singles_stop=singles_stop,
            duration=reported_duration,
            coinc_start=window_start,
            coinc_stop=window_stop,
        )

        return res_dict

    @staticmethod
    def _sample_count(samples: int) -> int:
        """Validate repetitions before acquiring any data."""
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise ValueError("samples must be a positive integer")
        return samples

    def measure_g2(
        self,
        duration: float,
        ch_start: int,
        ch_stop: int,
        ch_stop_delay: int | float = 0,
        bins: int = 500,
        bin_offset: int = 0,
        unit: str = "ns",
        method: str = "software",
        samples: int = 1,
        bin_width: int | None = None,
    ) -> CoincidenceResult:
        """Measure repeated histograms with fixed settings and integer ps axes."""
        width = self._bin_width(bin_width)
        return combine_samples(
            [
                self.backend.get_g2(
                    duration=duration,
                    bins=bins,
                    ch_start=ch_start,
                    ch_stop=ch_stop,
                    ch_stop_delay=ch_stop_delay,
                    bin_offset=bin_offset,
                    unit=unit,
                    bin_width=width,
                    method=method,
                )
                for _ in range(self._sample_count(samples))
            ]
        )

    def measure_coincidence(
        self,
        duration: float,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        unit: str = "ns",
        window_start: int | float | None = None,
        window_stop: int | float | None = None,
        method: str = "software",
        samples: int = 1,
        bin_width: int | None = None,
    ) -> CoincidenceResult:
        """Measure repeated window counts with window-local histograms.

        For software coincidence measurements, ``bin_offset`` and ``bins``
        are derived from the requested window. The first automatic sample
        searches a broad histogram for the peak, then subsequent samples reuse
        the selected window.
        """
        width = self._bin_width(bin_width)
        results = []
        automatic = window_start is None and method == "software"
        delay_ps = time_to_ps(ch_stop_delay, unit)
        for _ in range(self._sample_count(samples)):
            if automatic and results:
                first = results[0]
                result = self.backend.get_coincidence(
                    duration=duration,
                    ch_start=ch_start,
                    ch_stop=ch_stop,
                    ch_stop_delay=delay_ps,
                    unit="ps",
                    window_start=first.window_start[0],
                    window_stop=first.window_stop[0],
                    method=method,
                    bin_width=first.bin_width,
                )
            else:
                result = self.backend.get_coincidence(
                    duration=duration,
                    ch_start=ch_start,
                    ch_stop=ch_stop,
                    ch_stop_delay=ch_stop_delay,
                    unit=unit,
                    bin_width=width,
                    window_start=window_start,
                    window_stop=window_stop,
                    method=method,
                )
            results.append(result)
        return combine_samples(results)

    def measure_triplet(
        self,
        duration: float,
        ch_ref: int,
        ch_sig1: int,
        ch_sig2: int,
        bins: int = 500,
        bin_offset: int = 0,
        deduplicate: bool = False,
        samples: int = 1,
        store_events: bool = False,
        bin_width: int | None = None,
    ) -> MultiCoincidenceResult:
        """Measure repeated three-channel combinations with four directed histograms."""
        width = self._bin_width(bin_width)
        results = []
        for _ in range(self._sample_count(samples)):
            ts = self.backend.get_timestamps(duration)
            results.append(
                compute_triplet_g2(
                    timestamps_ps=ts.timestamps,
                    channels=ts.channels,
                    ch_ref=ch_ref,
                    ch_sig1=ch_sig1,
                    ch_sig2=ch_sig2,
                    bins=bins,
                    resolution_ps=ts.resolution_ps if width is None else width,
                    bin_offset=bin_offset,
                    duration=ts.duration_s,
                    deduplicate=deduplicate,
                    store_events=store_events,
                )
            )
        return combine_samples(results)

    def measure_gate(
        self,
        duration: float,
        ch_ref: int,
        ch_signals: List[int],
        bins: int = 500,
        bin_offset: int = 0,
        deduplicate: bool = False,
        samples: int = 1,
        store_events: bool = False,
        bin_width: int | None = None,
    ) -> MultiCoincidenceResult:
        """Count reference events with a hit on every configured signal channel."""
        width = self._bin_width(bin_width)
        results = []
        for _ in range(self._sample_count(samples)):
            ts = self.backend.get_timestamps(duration)
            results.append(
                compute_gate_coincidence(
                    timestamps_ps=ts.timestamps,
                    channels=ts.channels,
                    ch_ref=ch_ref,
                    ch_signals=ch_signals,
                    bins=bins,
                    resolution_ps=ts.resolution_ps if width is None else width,
                    bin_offset=bin_offset,
                    duration=ts.duration_s,
                    deduplicate=deduplicate,
                    store_events=store_events,
                )
            )
        return combine_samples(results)

    def measure_heralding_gate(
        self,
        duration: float,
        heralding_channel: int,
        gated_channels: List[int],
        bins: int = 500,
        bin_offset: int = 0,
        samples: int = 1,
        stop_delay: dict[int, int] | None = None,
        store_events: bool = False,
        detail_format: str = "flat",
        store_histogram: bool = True,
        bin_width: int | None = None,
    ) -> HeraldingGateResult:
        """Measure associations for every herald, optionally retaining gate details.

        stop_delay values and returned times are integer picoseconds.
        """
        width = self._bin_width(bin_width)
        results = []
        for _ in range(self._sample_count(samples)):
            ts = self.backend.get_timestamps(duration)
            results.append(
                compute_gate_photons(
                    timestamps_ps=ts.timestamps,
                    channels=ts.channels,
                    ch_gate=heralding_channel,
                    ch_photons=gated_channels,
                    bins=bins,
                    resolution_ps=ts.resolution_ps if width is None else width,
                    bin_offset=bin_offset,
                    duration=ts.duration_s,
                    stop_delay=stop_delay,
                    store_events=store_events,
                    detail_format=detail_format,
                    store_histogram=store_histogram,
                )
            )
        return combine_samples(results)
