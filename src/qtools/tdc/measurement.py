"""TDC measurement orchestration.

Wraps a TDCBackend and provides high-level measurement routines:
singles, pairs (g²), triplets, and N-fold gate coincidences.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

import numpy as np
from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.data import (
    CoincidenceResult,
    G2Result,
    TripletResult,
    GateResult,
    SinglesResult,
    TimestampResult,
)
from qtools.tdc.analysis.g2 import (
    compute_g2,
    compute_triplet_g2,
    compute_gate_coincidence,
    bin_offset_from_peak,
    min_range_from_peak,
)
from qtools.tdc.analysis.efficiency import compute_pairs

logger = logging.getLogger(__name__)

_MAX_SINGLES_RETRIES = 20


class TDC:
    """High-level API class to perform singles, pairs, triplet, and gate measurements."""

    def __init__(self, backend: TDCBackend) -> None:
        self.backend = backend

    def __enter__(self) -> "TDC":
        self.backend.connect()
 
        return self

    def __exit__(self, *args: object) -> None:
        self.backend.disconnect()

    def set_threshold(
        self,
        threshold_or_channel: float | int,
        threshold: float | None = None,
        *,
        channel: int | None = None,
    ) -> None:
        """Set threshold voltage.

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
            val = threshold if threshold is not None else float(threshold_or_channel)
        elif threshold is None:
            ch = None
            val = float(threshold_or_channel)
        else:
            ch = int(threshold_or_channel)
            val = float(threshold)

        self.backend.set_threshold(val, channel=ch)

    @property
    def threshold(self) -> float:
        """Get default/global threshold."""
        if hasattr(self.backend, "get_threshold"):
            return self.backend.get_threshold(0)
        return 600.0

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
                inttime = res.integration_time

                # Integration time validation check (0.75 to 2.0)
                if not (0.75 < inttime / duration < 2.0):
                    logger.warning("Singles duration check failed: %f vs %f, retrying...", inttime, duration)
                    continue
                # Raw rates positive check
                if np.any(res.count_rates < 0):
                    logger.warning("Singles contain negative rates: %s, retrying...", res.count_rates)
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
        num: int = 1,
    ) -> List[Tuple[float, np.ndarray]]:
        """Perform singles raw-count measurement(s) with robustness retries.

        Args:
            duration: Integration time in seconds.
            num: Number of measurements to take.

        Returns:
            A list of ``(integration_time, counts)`` tuples,
            where *counts* is an array of raw per-channel counts.
            Always returns a list, even when ``num == 1``.

        Raises:
            RuntimeError: If all retries are exhausted for a measurement.
        """
        results = []
        for _ in range(num):
            res = self._acquire_singles(duration)
            results.append((res.integration_time, res.counts))

        return results
    
    def measure_rates(
        self,
        duration: float,
        num: int = 1,
    ) -> List[Tuple[float, np.ndarray]]:
        """Perform singles count-rate measurement(s) with robustness retries.

        Args:
            duration: Integration time in seconds.
            num: Number of measurements to take.

        Returns:
            A list of ``(integration_time, count_rates)`` tuples,
            where *count_rates* is an array of per-channel rates in counts/s.
            Always returns a list, even when ``num == 1``.

        Raises:
            RuntimeError: If all retries are exhausted for a measurement.
        """
        results = []
        for _ in range(num):
            res = self._acquire_singles(duration)
            results.append((res.integration_time, res.count_rates))

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
                logger.warning("Converting timestamps from ps to ns loses sub-nanosecond precision")
        else:
            raise ValueError(f"Unsupported unit: {unit}. Expected 'ps' or 'ns'.")

        # filter channels
        if channels is None:
            channels = [int(c) for c in np.sort(np.unique(ch))]

        result = []
        for channel in channels:
            mask = (ch == channel)
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
            ``integration_time``, ``start_rate``, ``stop_rate``, ``eff_start``,
            ``eff_stop``, ``eff_avg``, ``coinc_start``, ``coinc_stop``,
            ``bin_edges``, and ``histogram``.
        """
        # delay is specified in bins; convert to the time unit expected by
        # backend.get_g2() (ch_stop_delay).
        ch_stop_delay = delay * self.backend.resolution_ps
        if unit == "ns":
            ch_stop_delay = ch_stop_delay / 1e3
        elif unit == "ps":
            pass
        elif unit == "ms":
            ch_stop_delay = ch_stop_delay / 1e6
        else:
            raise ValueError(f"Unsupported unit: {unit!r}. Expected 'ns', 'ps', or 'ms'.")

        use_start_stop = (window_start is not None and window_stop is not None)
        if use_start_stop:
            if window_start < bin_offset:
                raise ValueError("window_start cannot be less than bin_offset.")
            if window_stop < window_start:
                raise ValueError("window_stop cannot be less than window_start.")

            # include the window_start bin and window_stop bin 
            window_bins = window_stop - window_start + 1 
        else:
            window_bins = peak + roffset - loffset + 1 
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
            unit=unit)

        hist = g2res.histogram
        bin_edges = g2res.bin_edges
        integration_time = g2res.integration_time
        if (
            integration_time is None
            or not np.isfinite(integration_time)
            or integration_time <= 0
        ):
            logger.warning(
                "TDC returned invalid integration_time %r; "
                "falling back to requested duration %.3f s",
                integration_time,
                duration,
            )
            integration_time = duration
        resolution_ps = g2res.resolution_ps
        singles_start = g2res.singles_start
        singles_stop = g2res.singles_stop


        res_dict = compute_pairs(
                    histogram=hist,
                    bin_edges=bin_edges,
                    singles_start=singles_start,
                    singles_stop=singles_stop,
                    integration_time=integration_time,
                    coinc_start=window_start,
                    coinc_stop=window_stop,
                )

        return res_dict

    def measure_pairs_samples(
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
        num: int = 1,
    ) -> dict:
        """Perform multiple coincidence correlation measurements and return aggregated statistics.

        Args:
            duration: Measurement time in seconds per sample.
            ch_start: Start channel index.
            ch_stop: Stop channel index.
            bins: Number of correlation histogram bins.
            peak: Center of coincidence window in bins.
            loffset: Left offset of coincidence window in bins.
            roffset: Right offset of coincidence window in bins.
            window_start: Optional start of coincidence window in bins.
            window_stop: Optional stop of coincidence window in bins.
            delay: Time delay in bins to apply to ch_stop (default: 0).
            bin_offset: Start of correlation window in bins.
            unit: Time unit for ``bin_offset`` (used for the correlation
                window; ``delay`` is always expressed in bins).
            num: Number of measurement samples to collect.

        Returns:
            A dictionary containing raw sample lists, means, standard deviations, and window metadata.
        """
        if num <= 0:
            raise ValueError("num must be a positive integer.")

        samples = []
        for idx in range(num):
            res =  self.measure_pairs(
                    duration=duration,
                    ch_start=ch_start,
                    ch_stop=ch_stop,
                    delay=delay,
                    bins=bins,
                    peak=peak,
                    loffset=loffset,
                    roffset=roffset,
                    window_start=window_start,
                    window_stop=window_stop,
                    bin_offset=bin_offset,
                    unit=unit,
                )
            samples.append(res)

        first_sample = samples[0]

        pair_counts = [s["pair_counts"] for s in samples]
        acc_pair_counts = [s["acc_pair_counts"] for s in samples]
        integration_time = [s["integration_time"] for s in samples]

        raw_pair_rates = [s["raw_pair_rate"] for s in samples]
        net_pair_rates = [s["net_pair_rate"] for s in samples]
        acc_pair_rates = [s["acc_pair_rate"] for s in samples]
        start_rates = [s["start_rate"] for s in samples]
        stop_rates = [s["stop_rate"] for s in samples]
        eff_starts = [s["eff_start"] for s in samples]
        eff_stops = [s["eff_stop"] for s in samples]
        eff_avgs = [s["eff_avg"] for s in samples]


        res = {
            "pair_counts": pair_counts,
            "acc_pair_counts": acc_pair_counts,
            "integration_time": integration_time,
            "raw_pair_rate": float(np.mean(raw_pair_rates)),
            "raw_pair_rate_std": float(np.std(raw_pair_rates)),
            "net_pair_rate": float(np.mean(net_pair_rates)),
            "net_pair_rate_std": float(np.std(net_pair_rates)),
            "acc_pair_rate": float(np.mean(acc_pair_rates)),
            "acc_pair_rate_std": float(np.std(acc_pair_rates)),
            "start_rate": float(np.mean(start_rates)),
            "stop_rate": float(np.mean(stop_rates)),
            "eff_start": float(np.mean(eff_starts)),
            "eff_stop": float(np.mean(eff_stops)),
            "eff_avg": float(np.mean(eff_avgs)),
            "coinc_start": first_sample["coinc_start"],
            "coinc_stop": first_sample["coinc_stop"],
            "bin_edges": first_sample["bin_edges"],
        }
        return res

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
    ) -> G2Result:
        """Measure only the g2 correlation histogram.

        Args:
            duration: Measurement time in seconds.
            ch_start: Start channel index.
            ch_stop: Stop channel index.
            ch_stop_delay: Time delay added to stop channel in specified unit (default: 0).
            bins: Number of histogram bins (default: 500).
            bin_offset: Start of correlation window in bins (default: 0).
            unit: Time unit for ch_stop_delay ('ns' or 'ps', default: 'ns').
            method: G² implementation to use: ``"software"`` (default) or
                ``"hardware"``.

        Returns:
            A G2Result object.
        """
        return self.backend.get_g2(
            duration=duration,
            bins=bins,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            bin_offset=bin_offset,
            unit=unit,
            method=method,
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
    ) -> CoincidenceResult:
        """Measure two-fold coincidence counts."""
        return self.backend.get_coincidence(
            duration=duration,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            unit=unit,
            window_start=window_start,
            window_stop=window_stop,
            method=method,
        )

    # -- triplet (3-fold coincidence) ----------------------------------------

    def measure_triplet(
        self,
        duration: float,
        ch_ref: int,
        ch_sig1: int,
        ch_sig2: int,
        bins: int = 500,
        bin_offset: int = 0,
        deduplicate: bool = False,
    ) -> TripletResult:
        """Measure 3-fold coincidence between three channels.

        Args:
            duration: Measurement time in seconds.
            ch_ref: Reference channel index (1-based, e.g. 1).
            ch_sig1: First signal channel index.
            ch_sig2: Second signal channel index.
            bins: Number of histogram bins.
            bin_offset: Start of correlation window in bins.
            deduplicate: If True, count unique delays per ref once.

        Returns:
            A TripletResult with four delay histograms and events.
        """
        ts_res = self.backend.get_timestamps(duration)
        resolution_ps = ts_res.resolution_ps

        return compute_triplet_g2(
            timestamps_ps=ts_res.timestamps,
            channels=ts_res.channels,
            ch_ref=ch_ref,
            ch_sig1=ch_sig1,
            ch_sig2=ch_sig2,
            bins=bins,
            resolution_ps=resolution_ps,
            bin_offset=bin_offset,
            integration_time=ts_res.duration_s,
            deduplicate=deduplicate,
        )

    # -- gate (N-fold coincidence) -------------------------------------------

    def measure_gate(
        self,
        duration: float,
        ch_ref: int,
        ch_signals: List[int],
        bins: int = 500,
        bin_offset: int = 0,
        deduplicate: bool = False,
    ) -> GateResult:
        """Measure N-fold gated coincidence.

        For each reference event, checks for coincidences with all signal
        channels within the time window.

        Args:
            duration: Measurement time in seconds.
            ch_ref: Reference channel index (1-based, e.g. 1).
            ch_signals: List of signal channel indices.
            bins: Number of histogram bins.
            bin_offset: Start of correlation window in bins.
            deduplicate: If True, count unique delays per ref once.

        Returns:
            A GateResult with pairwise histograms, N-fold count, and events.
        """
        ts_res = self.backend.get_timestamps(duration)
        resolution_ps = ts_res.resolution_ps

        return compute_gate_coincidence(
            timestamps_ps=ts_res.timestamps,
            channels=ts_res.channels,
            ch_ref=ch_ref,
            ch_signals=ch_signals,
            bins=bins,
            resolution_ps=resolution_ps,
            bin_offset=bin_offset,
            integration_time=ts_res.duration_s,
            deduplicate=deduplicate,
        )
