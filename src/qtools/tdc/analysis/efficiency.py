"""Efficiency and accidentals calculation for photon source optimization.

Ported from inst_efficiency.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def compute_coincidence(
    histogram: np.ndarray,
    bin_edges: np.ndarray,
    window_start: float,
    window_stop: float,
) -> Tuple[int, float, float]:
    """Count signal-window pairs and estimate accidentals from side bins.

    ``window_start`` and ``window_stop`` use the same bin coordinate system as
    ``bin_edges``. The signal window is half-open: ``[start, stop)``. The
    Returns ``(count, acc_count_perbin, accidental_count)`` where
    ``acc_count_perbin`` is the mean sideband count per bin and
    ``accidental_count`` is that value scaled to the selected window size.
    """
    histogram = np.asarray(histogram)
    bin_edges = np.asarray(bin_edges)
    if histogram.ndim != 1 or bin_edges.ndim != 1:
        raise ValueError("histogram and bin_edges must be one-dimensional")
    if len(histogram) != len(bin_edges) - 1:
        raise ValueError("Histogram and bin_edges do not match")
    if not np.isfinite(window_start) or not np.isfinite(window_stop):
        raise ValueError("coincidence window must be finite")
    if window_stop <= window_start:
        raise ValueError("window_stop must be greater than window_start")

    bin_left = bin_edges[:-1]
    signal_mask = (bin_left >= window_start) & (bin_left < window_stop)
    signal_bins = int(np.count_nonzero(signal_mask))
    if signal_bins == 0:
        raise ValueError("coincidence window does not overlap the g2 histogram")

    raw_count = int(np.sum(histogram[signal_mask], dtype=np.uint64))
    background_bins = histogram[~signal_mask]
    if len(background_bins) == 0:
        acc_count_perbin = 0.0
    else:
        acc_count_perbin = float(np.mean(background_bins))
    accidental_count = float(signal_bins * acc_count_perbin)
    return raw_count, acc_count_perbin, accidental_count


def compute_accidentals(
    histogram: np.ndarray,
    window_size: int,
    acc_start: int,
    acc_size: Optional[int] = None,
) -> Tuple[float, float]:
    """Calculate the expected accidental coincidences within the time window.

    Args:
        histogram: The raw g2 correlation histogram.
        window_size: The width of the coincidence window in bins.
        acc_start: The starting index in the histogram to compute the background average.

    Returns:
        The computed accidental counts (0.0 if no background region available).
    """
    if window_size <= 0:
        return 0.0
    if acc_size is None:
        bg_region = histogram[acc_start:]
    else:
        bg_region = histogram[acc_start:acc_start + acc_size]

    if len(bg_region) == 0:
        return 0.0
    return float(window_size * np.mean(bg_region)), np.mean(bg_region)


def compute_pairs(
    histogram: np.ndarray,
    bin_edges: np.ndarray,
    singles_start: float,
    singles_stop: float,
    integration_time: float,
    coinc_start: int,
    coinc_stop: int,
    acc_start: Optional[int] = None,
) -> Dict[str, Any]:
    
    if len(histogram) != len(bin_edges) - 1:
        raise ValueError("Histogram and bin_edges do not match")
    
    if coinc_start > coinc_stop:
        raise ValueError("coinc_start must not be greater than coinc_stop")

    if integration_time == 0:
        raise ValueError("Integration time is zero")

    if np.sum(histogram) == 0:
        return {
            "pair_counts": 0,
            "acc_pair_counts": 0,
            "raw_pair_rate": 0.0,
            "net_pair_rate": 0.0,
            "acc_pair_rate": 0.0,
            "integration_time": integration_time,
            "start_rate": singles_start,
            "stop_rate": singles_stop,
            "eff_start": 0.0,
            "eff_stop": 0.0,
            "eff_avg": 0.0,
            "coinc_start": coinc_start,
            "coinc_stop": coinc_stop,
            "bin_edges": bin_edges,
            "histogram": histogram,
        }

    bin_left = bin_edges[:-1] 
    coinc_window = coinc_stop - coinc_start + 1 
    
    # accidentals 
    if acc_start is None:
        acc_start = coinc_stop + 100 
    
       
    acc_in_coinc, acc_per_bin = compute_accidentals(histogram, coinc_window, acc_start)
    acc_in_coinc_rate = acc_in_coinc / integration_time

    # pairs in the coincidence window 
    coinc_mask = (bin_left >= coinc_start) & (bin_left <= coinc_stop)
    raw_coinc_counts = np.sum(histogram[coinc_mask])
    corr_coinc_counts = raw_coinc_counts - acc_in_coinc
    
    # net coincidence rate
    net_pairs_rate = corr_coinc_counts / integration_time
    raw_pairs_rate = raw_coinc_counts / integration_time

    # heralding efficiency for start channel
    # singles_start and singles_stop are already rates (counts/s);
    # convert to total counts by multiplying by integration_time.
    total_singles_start = singles_start * integration_time
    total_singles_stop = singles_stop * integration_time
    eff_start = corr_coinc_counts / total_singles_start if total_singles_start > 0 else 0.0
    eff_stop = corr_coinc_counts / total_singles_stop if total_singles_stop > 0 else 0.0

    # singles_start and singles_stop are already rates
    start_rate = singles_start
    stop_rate = singles_stop
    
    geometric_mean_singles = np.sqrt(start_rate*stop_rate)
    eff_avg = net_pairs_rate / geometric_mean_singles

    return {
        "pair_counts": corr_coinc_counts,
        "acc_pair_counts": acc_in_coinc,
        "raw_pair_rate": raw_pairs_rate,
        "net_pair_rate": net_pairs_rate,
        "acc_pair_rate": acc_in_coinc_rate,
        "integration_time": integration_time,
        "start_rate": start_rate,
        "stop_rate": stop_rate,
        "eff_start": eff_start,
        "eff_stop": eff_stop,
        "eff_avg": eff_avg,
        "coinc_start": coinc_start,
        "coinc_stop": coinc_stop,
        "bin_edges": bin_edges,
        "histogram": histogram,
    }
        
