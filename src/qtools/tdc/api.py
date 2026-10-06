"""Convenience API for the TDC package.

Provides one-shot measurement functions that handle device discovery,
connection, and measurement in a single call — no need to manually
manage backend lifecycle.

Example::

    from qtools.tdc.api import count_rate, pairs, g2

    # Quick count rate measurement
    inttime, rates = count_rate(duration=1.0)

    # Count rate on specific channels, multiple samples
    results = count_rate(duration=1.0, channels=[1, 2], num=5)

    # g² correlation
    result = g2(duration=5.0, ch_start=0, ch_stop=1)

    # Coincidence pairs with efficiency
    hist, t, pairs_val, acc, s1, s2, e1, e2, eavg = pairs(
        duration=10.0, ch_start=0, ch_stop=1,
        peak=250, loffset=5, roffset=5,
    )
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from qtools.tdc.measurement import TDC  # noqa: F401 — re-export for backward compatibility
from qtools.tdc.connection import get_device
from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.data import G2Result, TripletResult, GateResult


def count_rate(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    channels: Optional[List[int]] = None,
    num: int = 1,
) -> List[Tuple[float, np.ndarray]]:
    """Measure per-channel count rates (counts/s).

    Auto-discovers and connects to the device, performs the measurement,
    and disconnects.

    Args:
        backend: Registered backend identifier (default: ``DEFAULT_TDC1_BACKEND``).
        port: Device path/address, or None to auto-discover.
        duration: Integration time in seconds.
        channels: List of channel numbers to return (1-based, default: all).
        num: Number of measurements to take. Always returns a list,
            even when ``num == 1``.

    Returns:
        A list of ``(integration_time, count_rates)`` tuples, one per sample.

    Example::

        # Single measurement, all channels
        [(inttime, rates)] = count_rate(duration=0.5)

        # Channels 1 and 2 only, 5 samples
        samples = count_rate(duration=1.0, channels=[1, 2], num=5)
        for t, rates in samples:
            print(f"{t:.2f}s: {rates}")
    """
    tdc = get_device(backend, port)
    with tdc:
        results = tdc.measure_rates(duration=duration, num=num)

    if channels is not None:
        indices = [ch - 1 for ch in channels]
        results = [(inttime, rates[indices]) for inttime, rates in results]

    return results


def singles(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    channels: Optional[List[int]] = None,
    num: int = 1,
) -> List[Tuple[float, np.ndarray]]:
    """Measure raw singles counts.

    Auto-discovers and connects to the device, performs the measurement,
    and disconnects.

    Args:
        backend: Registered backend identifier (default: ``DEFAULT_TDC1_BACKEND``).
        port: Device path/address, or None to auto-discover.
        duration: Integration time in seconds.
        channels: List of channel numbers to return (1-based, default: all).
        num: Number of measurements to take. Always returns a list,
            even when ``num == 1``.

    Returns:
        A list of ``(integration_time, counts)`` tuples, one per sample.

    Example::

        [(inttime, counts)] = singles(duration=1.0)
        print(f"Total counts: {counts.sum()}")
    """
    tdc = get_device(backend, port)
    with tdc:
        results = tdc.measure_singles(duration=duration, num=num)

    if channels is not None:
        indices = [ch - 1 for ch in channels]
        results = [(inttime, counts[indices]) for inttime, counts in results]

    return results


def g2(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    ch_start: int = 1,
    ch_stop: int = 2,
    ch_stop_delay: int | float = 0,
    bins: int = 500,
    bin_offset: int = 0,
    unit: str = "ns",
    method: str = "software",
) -> G2Result:
    """Measure g²(τ) correlation histogram.

    Auto-discovers and connects to the device, acquires timestamps,
    computes the g² correlation, and disconnects.

    Args:
        backend: Registered backend identifier.
        port: Device path/address, or None to auto-discover.
        duration: Integration time in seconds.
        ch_start: Start channel (1-indexed, default: 1).
        ch_stop: Stop channel (1-indexed, default: 2).
        ch_stop_delay: Time delay in specified unit added to ch_stop.
        bins: Number of histogram bins.
        bin_offset: Start of correlation window in bins.
        unit: Time unit for ch_stop_delay ('ns' or 'ps').
        method: G² implementation to use: ``"software"`` (default) or
            ``"hardware"``.

    Returns:
        A ``G2Result`` with histogram, bin edges, singles rates, and
        integration time.

    Example::

        result = g2(duration=5.0, ch_start=0, ch_stop=1, bins=500)
        print(f"Peak bin: {result.histogram.argmax()}")
        print(f"Normalized g²: {result.normalized}")
    """
    tdc = get_device(backend, port)
    with tdc:
        return tdc.measure_g2(
            duration=duration,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            bins=bins,
            bin_offset=bin_offset,
            unit=unit,
            method=method,
        )


def pairs(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    ch_start: int = 1,
    ch_stop: int = 2,
    bins: int = 500,
    peak: int = 250,
    loffset: int = 5,
    roffset: int = 5,
    window_start: Optional[int] = None,
    window_stop: Optional[int] = None,
) -> Tuple[np.ndarray, float, float, float, float, float, float, float, float]:
    """Measure coincidence pairs with efficiency analysis.

    Auto-discovers and connects to the device, acquires timestamps,
    computes g² with coincidence/accidental counts and detector
    efficiencies, and disconnects.

    Args:
        backend: Registered backend identifier.
        port: Device path/address, or None to auto-discover.
        duration: Measurement time in seconds.
        ch_start: Start channel (1-indexed, default: 1).
        ch_stop: Stop channel (1-indexed, default: 2).
        bins: Number of correlation histogram bins.
        peak: Center of coincidence window in bins.
        loffset: Left offset of the coincidence window in bins.
        roffset: Right offset of the coincidence window in bins.
        window_start: Explicit window start in bins (overrides peak+loffset).
        window_stop: Explicit window stop in bins (overrides peak+roffset).

    Returns:
        A 9-tuple: ``(histogram, integration_time, pairs, accidentals,
        singles_start, singles_stop, eff_start, eff_stop, eff_avg)``.

    Example::

        hist, t, p, acc, s1, s2, e1, e2, eavg = pairs(
            duration=10.0, ch_start=1, ch_stop=2,
            peak=250, loffset=5, roffset=5,
        )
        print(f"Pairs: {p:.1f}, Efficiency: {eavg:.4f}")
    """
    tdc = get_device(backend, port)
    with tdc:
        res = tdc.measure_pairs(
            duration=duration,
            ch_start=ch_start,
            ch_stop=ch_stop,
            bins=bins,
            peak=peak,
            loffset=loffset,
            roffset=roffset,
            window_start=window_start,
            window_stop=window_stop,
        )
        return (
            res["histogram"],
            res["integration_time"],
            res["pair_counts"],
            res["acc_pair_counts"],
            res["start_rate"],
            res["stop_rate"],
            res["eff_start"],
            res["eff_stop"],
            res["eff_avg"],
        )


def triplet(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    ch_ref: int = 1,
    ch_sig1: int = 2,
    ch_sig2: int = 3,
    bins: int = 500,
    bin_offset: int = 0,
    deduplicate: bool = False,
) -> TripletResult:
    """Measure 3-fold coincidence between three channels.

    Auto-discovers and connects to the device, acquires timestamps,
    computes triplet correlations, and disconnects.

    Args:
        backend: Registered backend identifier.
        port: Device path/address, or None to auto-discover.
        duration: Measurement time in seconds.
        ch_ref: Reference channel index (1-indexed, default: 1).
        ch_sig1: First signal channel index (1-indexed, default: 2).
        ch_sig2: Second signal channel index (1-indexed, default: 3).
        bins: Number of histogram bins.
        bin_offset: Start of correlation window in bins.
        deduplicate: If True, count unique delays per ref once.

    Returns:
        A ``TripletResult`` with four delay histograms and events.

    Example::

        result = triplet(duration=10.0)
        print(f"Triplet events: {len(result.events)}")
    """
    tdc = get_device(backend, port)
    with tdc:
        return tdc.measure_triplet(
            duration=duration,
            ch_ref=ch_ref,
            ch_sig1=ch_sig1,
            ch_sig2=ch_sig2,
            bins=bins,
            bin_offset=bin_offset,
            deduplicate=deduplicate,
        )


def gate(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    ch_ref: int = 0,
    ch_signals: Optional[List[int]] = None,
    bins: int = 500,
    bin_offset: int = 0,
    deduplicate: bool = False,
) -> GateResult:
    """Measure N-fold gated coincidence.

    For each reference event, checks for coincidences with all signal
    channels within the time window. Auto-discovers and connects to the
    device, acquires timestamps, computes the gate analysis, and disconnects.

    Args:
        backend: Registered backend identifier.
        port: Device path/address, or None to auto-discover.
        duration: Measurement time in seconds.
        ch_ref: Reference channel index (0-indexed).
        ch_signals: List of signal channel indices (default: ``[1, 2, 3]``).
        bins: Number of histogram bins.
        bin_offset: Start of correlation window in bins.
        deduplicate: If True, count unique delays per ref once.

    Returns:
        A ``GateResult`` with pairwise histograms, N-fold count, and events.

    Example::

        result = gate(duration=10.0, ch_ref=0, ch_signals=[1, 2, 3])
        print(f"N-fold coincidences: {result.n_fold_count}")
    """
    if ch_signals is None:
        ch_signals = [1, 2, 3]
    tdc = get_device(backend, port)
    with tdc:
        return tdc.measure_gate(
            duration=duration,
            ch_ref=ch_ref,
            ch_signals=ch_signals,
            bins=bins,
            bin_offset=bin_offset,
            deduplicate=deduplicate,
        )
