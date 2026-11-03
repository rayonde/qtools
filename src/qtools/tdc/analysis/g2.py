"""Coincidence g2 correlation analysis.

Computes second-order correlation histograms (g²), 3-fold (triplet)
coincidence histograms, and N-fold gated coincidence measurements.

Internal kernels use bin indices; public results store integer physical times in ps.
"""

from __future__ import annotations

import ctypes
import logging
from typing import List, Optional, Tuple

import numpy as np

from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.data import (
    CoincidenceResult,
    HeraldingGateResult,
    MultiCoincidenceResult,
    validate_bin_width,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Native C library loading
# ---------------------------------------------------------------------------

_LIBCOINC = None

try:
    from qtools.tdc._native import load_libcoincidences

    _LIBCOINC = load_libcoincidences()

    # --- g2 (bin-based, int64 timestamps) ---
    _LIBCOINC.tdc_compute_g2.argtypes = [
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_int,  # t1, len1
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_int,  # t2, len2
        ctypes.c_int,  # bins
        ctypes.POINTER(ctypes.c_uint64),  # out histogram
    ]
    _LIBCOINC.tdc_compute_g2.restype = ctypes.c_int

    # --- triplet (3-fold) ---
    try:
        _LIBCOINC.tdc_compute_triplet.argtypes = [
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_int,  # t1, len1
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_int,  # t2, len2
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_int,  # t3, len3
            ctypes.c_int,  # bins
            ctypes.c_int,  # deduplicate
            ctypes.POINTER(ctypes.c_uint64),  # out hist_21
            ctypes.POINTER(ctypes.c_uint64),  # out hist_31
            ctypes.POINTER(ctypes.c_uint64),  # out hist_32
            ctypes.POINTER(ctypes.c_uint64),  # out hist_23
            ctypes.POINTER(ctypes.c_int64),  # out_events
            ctypes.POINTER(ctypes.c_int64),  # out_ref_idx
            ctypes.c_int,  # max_events
            ctypes.POINTER(ctypes.c_int),  # out_count
        ]
        _LIBCOINC.tdc_compute_triplet.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have triplet yet

    # --- gate (N-fold) ---
    try:
        _LIBCOINC.tdc_compute_gate.argtypes = [
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_int,  # t_ref, len_ref
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int64)),  # signals array
            ctypes.POINTER(ctypes.c_int),  # signal lengths
            ctypes.c_int,  # n_signals
            ctypes.c_int,  # bins
            ctypes.c_int,  # deduplicate
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint64)),  # out hists
            ctypes.POINTER(ctypes.c_uint64),  # out n_fold (uint64_t)
            ctypes.POINTER(ctypes.c_int64),  # out_events
            ctypes.POINTER(ctypes.c_int64),  # out_ref_idx
            ctypes.c_int,  # max_events
            ctypes.POINTER(ctypes.c_int),  # out_count
        ]
        _LIBCOINC.tdc_compute_gate.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have gate yet

    # --- gate-photon correspondence ---
    try:
        _LIBCOINC.tdc_compute_gate_photons.argtypes = [
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_int,  # t_gate, n_gate
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int64)),  # photon_signals
            ctypes.POINTER(ctypes.c_int),  # signal_lengths
            ctypes.c_int,  # n_signals
            ctypes.c_int,  # bins
            ctypes.POINTER(ctypes.c_int64),  # out_photons
            ctypes.POINTER(ctypes.c_int32),  # out_channels
            ctypes.POINTER(ctypes.c_int32),  # out_offsets
            ctypes.c_int,  # max_hits
            ctypes.POINTER(ctypes.c_int),  # out_count
        ]
        _LIBCOINC.tdc_compute_gate_photons.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have gate-photons yet

    logger.debug("Loaded native coincidences library")
except Exception as e:
    logger.debug("Could not load native coincidences library: %s", e)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _infer_duration(timestamps_ps: np.ndarray) -> float:
    """Estimate integration time from the span of recorded timestamps."""
    if len(timestamps_ps) > 1:
        return float(timestamps_ps[-1] - timestamps_ps[0]) * 1e-12
    return 0.0


def _relative_events(events, offset, width):
    return [
        ((0,) + tuple((value - times[0] + offset) * width for value in times[1:]), ref)
        for times, ref in events
    ]


def _singles_rate(counts: int, duration: float) -> float:
    """Singles count rate in cps."""
    return counts / duration if duration > 0 else 0.0


# ---------------------------------------------------------------------------
# Pure-Python fallback implementations
# ---------------------------------------------------------------------------


def _compute_g2_python(
    t1_bins: np.ndarray, t2_adj_bins: np.ndarray, bins: int
) -> np.ndarray:
    """Pure-Python g2 delta-loop fallback.

    Both arrays must be sorted int64 in bin units.
    ``t2_adj_bins`` is already offset-adjusted (``t2_bins - bin_offset``).
    """
    hist = np.zeros(bins, dtype=np.uint64)
    idx2_start = 0
    n2 = len(t2_adj_bins)
    for i in range(len(t1_bins)):
        val1 = t1_bins[i]
        j = idx2_start
        while j < n2:
            diff = t2_adj_bins[j] - val1
            if diff < 0:
                idx2_start = j + 1
                j += 1
                continue
            if diff >= bins:
                break
            hist[diff] += 1
            j += 1
    return hist


def _compute_triplet_python(
    t1: np.ndarray,
    t2: np.ndarray,
    t3: np.ndarray,
    bins: int,
    deduplicate: bool = False,
    store_events: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list]:
    """Pure-Python 3-fold coincidence fallback.

    Computes four histograms: (t2-t1), (t3-t1), (t3-t2), (t2-t3).
    All arrays are sorted int64 in bin units.

    Histograms are built from triplet events: for each ref, every (t2, t3)
    pair within the window forms a triplet, and all four histograms count
    those triplets.

    Args:
        t1, t2, t3: Sorted int64 arrays in bin units.
        bins: Number of histogram bins.
        deduplicate: If True, each unique delay per ref is counted once.

    Returns:
        (hist_21, hist_31, hist_32, hist_23, events) where *events* is a list
        of ``((t1_val, t2_val, t3_val), ref_idx)`` tuples.
    """
    hist_21 = np.zeros(bins, dtype=np.uint64)
    hist_31 = np.zeros(bins, dtype=np.uint64)
    hist_32 = np.zeros(bins, dtype=np.uint64)
    hist_23 = np.zeros(bins, dtype=np.uint64)
    events: list = []

    n2, n3 = len(t2), len(t3)
    idx2_start = 0
    idx3_start = 0

    for i in range(len(t1)):
        val1 = t1[i]

        # Advance cached start indices past val1
        while idx2_start < n2 and t2[idx2_start] < val1:
            idx2_start += 1
        while idx3_start < n3 and t3[idx3_start] < val1:
            idx3_start += 1

        # Per-ref dedup masks (if needed)
        mask21 = np.zeros(bins, dtype=bool) if deduplicate else None
        mask31 = np.zeros(bins, dtype=bool) if deduplicate else None
        mask32 = np.zeros(bins, dtype=bool) if deduplicate else None
        mask23 = np.zeros(bins, dtype=bool) if deduplicate else None

        j = idx2_start
        while j < n2:
            d21 = t2[j] - val1
            if d21 >= bins:
                break

            k = idx3_start
            while k < n3:
                d31 = t3[k] - val1
                if d31 >= bins:
                    break

                # Triplet event (val1, t2[j], t3[k])
                if deduplicate:
                    if not mask21[d21]:
                        hist_21[d21] += 1
                        mask21[d21] = True
                    if not mask31[d31]:
                        hist_31[d31] += 1
                        mask31[d31] = True
                else:
                    hist_21[d21] += 1
                    hist_31[d31] += 1

                d32 = t3[k] - t2[j]
                if 0 <= d32 < bins:
                    if deduplicate:
                        if not mask32[d32]:
                            hist_32[d32] += 1
                            mask32[d32] = True
                    else:
                        hist_32[d32] += 1

                d23 = t2[j] - t3[k]
                if 0 <= d23 < bins:
                    if deduplicate:
                        if not mask23[d23]:
                            hist_23[d23] += 1
                            mask23[d23] = True
                    else:
                        hist_23[d23] += 1

                if store_events:
                    events.append(((int(val1), int(t2[j]), int(t3[k])), i))

                k += 1
            j += 1

    return hist_21, hist_31, hist_32, hist_23, events


def _compute_gate_python(
    t_ref: np.ndarray,
    signals: List[np.ndarray],
    bins: int,
    deduplicate: bool = False,
    store_events: bool = True,
) -> Tuple[List[np.ndarray], int, list]:
    """Pure-Python N-fold gated coincidence fallback.

    Args:
        t_ref: Reference channel timestamps (sorted int64, bin units).
        signals: List of signal channel timestamp arrays.
        bins: Number of histogram bins.
        deduplicate: If True, unique delays per ref per channel counted once.

    Returns:
        Tuple of (list_of_histograms, n_fold_count, events).
        *events* is a list of ``((t_ref, t_sig0, t_sig1, ...), ref_idx)``.
    """
    n_signals = len(signals)
    hists = [np.zeros(bins, dtype=np.uint64) for _ in range(n_signals)]
    n_fold = 0
    events: list = []
    cached_starts = [0] * n_signals

    for i in range(len(t_ref)):
        ref = t_ref[i]
        all_hit = True
        per_ch_matches: list = []  # list of lists of hit indices per channel

        for k in range(n_signals):
            found = False
            sig = signals[k]
            matches_k: list = []

            # Advance cached index past ref
            j = cached_starts[k]
            while j < len(sig) and sig[j] < ref:
                cached_starts[k] = j + 1
                j += 1

            if deduplicate:
                seen = np.zeros(bins, dtype=bool)

            while j < len(sig):
                diff = sig[j] - ref
                if diff >= bins:
                    break
                if deduplicate:
                    if not seen[diff]:
                        hists[k][diff] += 1
                        seen[diff] = True
                else:
                    hists[k][diff] += 1
                matches_k.append(j)
                found = True
                j += 1

            per_ch_matches.append(matches_k)
            if not found:
                all_hit = False

        if all_hit:
            n_fold += 1
            if not store_events:
                continue
            # Enumerate cartesian product of matched indices (odometer)
            cursors = [0] * n_signals
            while True:
                sig_vals = tuple(
                    int(signals[k][per_ch_matches[k][cursors[k]]])
                    for k in range(n_signals)
                )
                events.append(((int(ref),) + sig_vals, i))
                # Advance odometer and stop after the final Cartesian product.
                carry = True
                for k in range(n_signals - 1, -1, -1):
                    cursors[k] += 1
                    if cursors[k] >= len(per_ch_matches[k]):
                        cursors[k] = 0
                    else:
                        carry = False
                        break
                if carry:
                    break

    return hists, n_fold, events


# ---------------------------------------------------------------------------
# Internal: dispatch to best available g2 engine
# ---------------------------------------------------------------------------


def _compute_g2_delta_loop(
    t1_bins: np.ndarray,
    t2_adj_bins: np.ndarray,
    bins: int,
) -> np.ndarray:
    """Compute correlation histogram using the best available implementation.

    Args:
        t1_bins: Start-channel timestamps in bin units (int64, sorted).
        t2_adj_bins: Stop-channel timestamps in bin units, offset-adjusted (int64, sorted).
        bins: Number of histogram bins.

    Returns:
        Histogram array of shape ``(bins,)`` with dtype uint64.
    """
    if _LIBCOINC is not None:
        t1_arr = np.ascontiguousarray(t1_bins, dtype=np.int64)
        t2_arr = np.ascontiguousarray(t2_adj_bins, dtype=np.int64)
        hist = np.zeros(bins, dtype=np.uint64)
        err = _LIBCOINC.tdc_compute_g2(
            t1_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
            len(t1_arr),
            t2_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
            len(t2_arr),
            int(bins),
            hist.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
        )
        if err != 0:
            logger.warning(
                "C-based tdc_compute_g2 returned error %d, falling back", err
            )
        else:
            return hist

    # Pure-Python fallback
    return _compute_g2_python(t1_bins, t2_adj_bins, bins)


# ---------------------------------------------------------------------------
# Public API: g2
# ---------------------------------------------------------------------------


def compute_g2(
    timestamps_ps: np.ndarray,
    channels: np.ndarray,
    ch_start: int,
    ch_stop: int,
    bins: int = 500,
    resolution_ps: float = 1000.0,
    bin_offset: int = 0,
    duration: Optional[float] = None,
    stop_delay: int = 0,
) -> CoincidenceResult:
    """Compute the second-order correlation histogram g²(τ).

    The window offset is in bins; stop_delay and output times are in integer ps.
    Histogram bins use the requested resolution.

    Args:
        timestamps_ps: Absolute timestamp values in picoseconds (int64).
        channels:      Corresponding channel indices (uint8).
        ch_start:      Actual start channel ID.
        ch_stop:       Actual stop channel ID.
        bins:          Number of histogram bins (must be > 0).
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        duration: Total integration time in seconds (optional).
        stop_delay:    Delay added to ch_stop in integer ps.

    Returns:
        A :class:`CoincidenceResult` containing the histogram and bin boundaries.

    Raises:
        ValueError: If *bins* ≤ 0.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    resolution_ps = validate_bin_width(resolution_ps)
    if not isinstance(stop_delay, (int, np.integer)):
        raise ValueError("stop_delay must be integer ps")
    if ch_start == ch_stop:
        raise ValueError("start and stop channels must differ")
    # Filter timestamps for start and stop channels
    t1_ps = timestamps_ps[channels == ch_start]
    t2_ps = timestamps_ps[channels == ch_stop]

    # Convert picoseconds to bin units (integer division)
    t1_bins = np.floor_divide(t1_ps, resolution_ps)
    t2_bins = np.floor_divide(t2_ps + stop_delay, resolution_ps)

    # Calculate actual integration time if not supplied
    if duration is None:
        duration = _infer_duration(timestamps_ps)

    # Compute correlation histogram
    hist = np.zeros(bins, dtype=np.uint64)
    if len(t1_bins) > 0 and len(t2_bins) > 0:
        t2_adj_bins = t2_bins - bin_offset
        hist = _compute_g2_delta_loop(t1_bins, t2_adj_bins, bins)

    # Convert the internal bin axis to physical picoseconds below.
    bin_edges = np.arange(bin_offset, bin_offset + bins + 1)

    # Singles count rate (counts / duration)
    rate_start = _singles_rate(len(t1_ps), duration)
    rate_stop = _singles_rate(len(t2_ps), duration)

    return CoincidenceResult(
        mode="histogram",
        channel_start=ch_start,
        channel_stop=ch_stop,
        bin_width=resolution_ps,
        counts_start=[len(t1_ps)],
        counts_stop=[len(t2_ps)],
        singles_start=[rate_start],
        singles_stop=[rate_stop],
        duration=[duration],
        stop_delay=[int(stop_delay)],
        n_bins=[bins],
        stop_offset=[bin_offset * resolution_ps],
        histogram=[hist],
        bin_edges=[bin_edges.astype(np.int64) * resolution_ps],
    )


# ---------------------------------------------------------------------------
# Public API: triplet (3-fold coincidence)
# ---------------------------------------------------------------------------


def compute_triplet_g2(
    timestamps_ps: np.ndarray,
    channels: np.ndarray,
    ch_ref: int,
    ch_sig1: int,
    ch_sig2: int,
    bins: int = 500,
    resolution_ps: float = 1000.0,
    bin_offset: int = 0,
    duration: Optional[float] = None,
    deduplicate: bool = False,
    store_events: bool = False,
) -> MultiCoincidenceResult:
    """Compute 3-fold coincidence histograms.

    Measures delay histograms between three channels: reference, signal-1,
    and signal-2. Histograms are built from **triplet events**: for each
    reference event, every (sig1, sig2) pair within the window forms a
    triplet and contributes to all four histograms.

    Args:
        timestamps_ps: Absolute timestamps in picoseconds (int64).
        channels:      Channel indices (uint8).
        ch_ref:        Reference channel index (0-indexed).
        ch_sig1:       First signal channel index (0-indexed).
        ch_sig2:       Second signal channel index (0-indexed).
        bins:          Number of histogram bins.
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        duration: Total integration time in seconds.
        deduplicate:   If True, each unique delay per reference event is
            counted at most once per histogram bin.
        store_events:  Retain relative event details when True.

    Returns:
        A :class:`MultiCoincidenceResult` with four directed histograms.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    resolution_ps = validate_bin_width(resolution_ps)
    if len({ch_ref, ch_sig1, ch_sig2}) != 3:
        raise ValueError("triplet channels must be distinct")
    # Filter and convert to bin units with window alignment
    # (only signal channels are adjusted by bin_offset, matching g2 convention)
    t1_ps = timestamps_ps[channels == ch_ref]
    t2_ps = timestamps_ps[channels == ch_sig1]
    t3_ps = timestamps_ps[channels == ch_sig2]

    t1 = np.floor_divide(t1_ps, resolution_ps)
    t2_adj = np.floor_divide(t2_ps, resolution_ps) - bin_offset
    t3_adj = np.floor_divide(t3_ps, resolution_ps) - bin_offset

    if duration is None:
        duration = _infer_duration(timestamps_ps)

    events: list = []

    # Try C library first, then fall back to Python
    use_c = _LIBCOINC is not None and hasattr(_LIBCOINC, "tdc_compute_triplet")
    c_ok = False

    if use_c:
        t1_arr = np.ascontiguousarray(t1, dtype=np.int64)
        t2_arr = np.ascontiguousarray(t2_adj, dtype=np.int64)
        t3_arr = np.ascontiguousarray(t3_adj, dtype=np.int64)
        hist_21 = np.zeros(bins, dtype=np.uint64)
        hist_31 = np.zeros(bins, dtype=np.uint64)
        hist_32 = np.zeros(bins, dtype=np.uint64)
        hist_23 = np.zeros(bins, dtype=np.uint64)

        # Events buffer — use a reasonable initial size, grow on overflow
        max_ev = 100000 if store_events else 0
        while True:
            ev_buf = np.zeros(max_ev * 3, dtype=np.int64)
            ref_buf = np.zeros(max_ev, dtype=np.int64)
            out_count = ctypes.c_int(0)
            err = _LIBCOINC.tdc_compute_triplet(
                t1_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(t1_arr),
                t2_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(t2_arr),
                t3_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(t3_arr),
                int(bins),
                int(deduplicate),
                hist_21.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_31.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_32.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_23.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                ev_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                ref_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                max_ev,
                ctypes.byref(out_count),
            )
            if err == -2:
                max_ev *= 4  # buffer too small — grow and retry
                continue
            if err != 0:
                logger.warning(
                    "C-based tdc_compute_triplet returned error %d, falling back", err
                )
                break
            c_ok = True
            # Unpack events from flat buffer
            for e in range(out_count.value):
                events.append(
                    (
                        (
                            int(ev_buf[e * 3]),
                            int(ev_buf[e * 3 + 1]),
                            int(ev_buf[e * 3 + 2]),
                        ),
                        int(ref_buf[e]),
                    )
                )
            break

    if not c_ok:
        hist_21, hist_31, hist_32, hist_23, events = _compute_triplet_python(
            t1,
            t2_adj,
            t3_adj,
            bins,
            deduplicate=deduplicate,
            store_events=store_events,
        )

    # Singles rates
    rates = tuple(
        _singles_rate(len(t), duration) for t in (t1_ps, t2_ps, t3_ps)
    )

    channel_ids = (ch_ref, ch_sig1, ch_sig2)
    count = sum(
        int(np.searchsorted(t2_adj, ref + bins) - np.searchsorted(t2_adj, ref))
        * int(np.searchsorted(t3_adj, ref + bins) - np.searchsorted(t3_adj, ref))
        for ref in t1
    )
    pairs = (
        (ch_ref, ch_sig1),
        (ch_ref, ch_sig2),
        (ch_sig1, ch_sig2),
        (ch_sig2, ch_sig1),
    )
    offsets = (bin_offset, bin_offset, 0, 0)
    return MultiCoincidenceResult(
        channels=channel_ids,
        mode="histogram",
        bin_width=resolution_ps,
        count_mode="combinations",
        histogram_scope="coincident_events",
        deduplicate=deduplicate,
        counts={ch: [len(ts)] for ch, ts in zip(channel_ids, (t1_ps, t2_ps, t3_ps))},
        singles={ch: [rate] for ch, rate in zip(channel_ids, rates)},
        duration=[duration],
        channel_delays={ch: [0] for ch in channel_ids},
        window_start=[bin_offset * resolution_ps],
        window_stop=[(bin_offset + bins) * resolution_ps],
        raw_counts=[count],
        pairwise_hists={
            pair: [hist]
            for pair, hist in zip(pairs, (hist_21, hist_31, hist_32, hist_23))
        },
        bin_edges={
            pair: [np.arange(offset, offset + bins + 1, dtype=np.int64) * resolution_ps]
            for pair, offset in zip(pairs, offsets)
        },
        events=[_relative_events(events, bin_offset, resolution_ps)]
        if store_events
        else None,
    )


# ---------------------------------------------------------------------------
# Public API: gate (N-fold coincidence)
# ---------------------------------------------------------------------------


def compute_gate_coincidence(
    timestamps_ps: np.ndarray,
    channels: np.ndarray,
    ch_ref: int,
    ch_signals: List[int],
    bins: int = 500,
    resolution_ps: float = 1000.0,
    bin_offset: int = 0,
    duration: Optional[float] = None,
    deduplicate: bool = False,
    store_events: bool = False,
) -> MultiCoincidenceResult:
    """Compute N-fold gated coincidence measurement.

    For each reference event, checks for coincidences with all signal
    channels within the window ``[bin_offset, bin_offset + bins)``.

    Pairwise histograms record every (signal[k] - ref) hit within the window.
    ``raw_counts[0]`` is the number of reference events where ALL signal
    channels had at least one coincidence.

    N-fold event tuples (one per combination of matched signal hits per ref)
    are retained only when ``store_events=True``.

    Args:
        timestamps_ps: Absolute timestamps in picoseconds (int64).
        channels:      Channel indices (uint8).
        ch_ref:        Reference channel index (0-indexed).
        ch_signals:    List of signal channel indices (0-indexed).
        bins:          Number of histogram bins.
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        duration: Total integration time in seconds.
        deduplicate:   If True, each unique delay per ref per channel is
            counted at most once.
        store_events:  Retain relative event details when True.

    Returns:
        A :class:`MultiCoincidenceResult` with pairwise histograms, N-fold count, and events.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")
    resolution_ps = validate_bin_width(resolution_ps)
    if (
        len(ch_signals) < 2
        or len(set([ch_ref] + list(ch_signals))) != len(ch_signals) + 1
    ):
        raise ValueError("N-fold coincidence requires at least three distinct channels")

    # Filter and convert to bin units.
    # Window alignment: only signal channels are offset by bin_offset, matching
    # the g2 convention (delay = signal - bin_offset - ref). The reference
    # channel is kept unshifted.
    t_ref_ps = timestamps_ps[channels == ch_ref]
    t_ref = np.floor_divide(t_ref_ps, resolution_ps)

    sig_ps_list = [timestamps_ps[channels == ch] for ch in ch_signals]
    sig_list = [np.floor_divide(s, resolution_ps) - bin_offset for s in sig_ps_list]

    if duration is None:
        duration = _infer_duration(timestamps_ps)

    events: list = []

    # Try C library first, then fall back to Python
    use_c = _LIBCOINC is not None and hasattr(_LIBCOINC, "tdc_compute_gate")
    c_ok = False

    if use_c:
        n_signals = len(sig_list)
        t_ref_arr = np.ascontiguousarray(t_ref, dtype=np.int64)

        # Build arrays of pointers for signals
        SigPtrArray = ctypes.POINTER(ctypes.c_int64) * n_signals
        sig_ptrs = SigPtrArray()
        sig_lens = (ctypes.c_int * n_signals)()
        sig_arrs = []  # prevent garbage collection
        for k, sig in enumerate(sig_list):
            arr = np.ascontiguousarray(sig, dtype=np.int64)
            sig_arrs.append(arr)
            sig_ptrs[k] = arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64))
            sig_lens[k] = len(arr)

        # Build output histogram pointers
        HistPtrArray = ctypes.POINTER(ctypes.c_uint64) * n_signals
        hist_ptrs = HistPtrArray()
        hist_arrs = [np.zeros(bins, dtype=np.uint64) for _ in range(n_signals)]
        for k, h in enumerate(hist_arrs):
            hist_ptrs[k] = h.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64))

        n_fold_out = ctypes.c_uint64(0)

        # Events buffer — grow on overflow
        max_ev = 100000 if store_events else 0
        while True:
            stride = n_signals + 1
            ev_buf = np.zeros(max_ev * stride, dtype=np.int64)
            ref_buf = np.zeros(max_ev, dtype=np.int64)
            out_count = ctypes.c_int(0)
            err = _LIBCOINC.tdc_compute_gate(
                t_ref_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(t_ref_arr),
                ctypes.cast(sig_ptrs, ctypes.POINTER(ctypes.POINTER(ctypes.c_int64))),
                sig_lens,
                n_signals,
                int(bins),
                int(deduplicate),
                ctypes.cast(hist_ptrs, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint64))),
                ctypes.byref(n_fold_out),
                ev_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                ref_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                max_ev,
                ctypes.byref(out_count),
            )
            if err == -2:
                max_ev *= 4
                continue
            if err != 0:
                logger.warning(
                    "C-based tdc_compute_gate returned error %d, falling back", err
                )
                break
            c_ok = True
            hists = hist_arrs
            n_fold = int(n_fold_out.value)
            # Unpack events from flat buffer
            for e in range(out_count.value):
                vals = tuple(int(ev_buf[e * stride + d]) for d in range(stride))
                events.append((vals, int(ref_buf[e])))
            break

    if not c_ok:
        hists, n_fold, events = _compute_gate_python(
            t_ref,
            sig_list,
            bins,
            deduplicate=deduplicate,
            store_events=store_events,
        )

    # Singles rates
    all_channels = [ch_ref] + list(ch_signals)
    all_ts = [t_ref_ps] + sig_ps_list
    singles = [_singles_rate(len(t), duration) for t in all_ts]

    return MultiCoincidenceResult(
        channels=tuple(all_channels),
        mode="histogram",
        bin_width=resolution_ps,
        count_mode="reference_events",
        histogram_scope="all_pair_hits",
        deduplicate=deduplicate,
        counts={ch: [len(ts)] for ch, ts in zip(all_channels, all_ts)},
        singles={ch: [rate] for ch, rate in zip(all_channels, singles)},
        duration=[duration],
        channel_delays={ch: [0] for ch in all_channels},
        window_start=[bin_offset * resolution_ps],
        window_stop=[(bin_offset + bins) * resolution_ps],
        raw_counts=[n_fold],
        pairwise_hists={(ch_ref, ch): [hist] for ch, hist in zip(ch_signals, hists)},
        bin_edges={
            (ch_ref, ch): [
                np.arange(bin_offset, bin_offset + bins + 1, dtype=np.int64)
                * resolution_ps
            ]
            for ch in ch_signals
        },
        events=[_relative_events(events, bin_offset, resolution_ps)]
        if store_events
        else None,
    )


def compute_gate_photons(
    timestamps_ps: np.ndarray,
    channels: np.ndarray,
    ch_gate: int,
    ch_photons: List[int],
    bins: int = 500,
    resolution_ps: float = 1000.0,
    bin_offset: int = 0,
    duration: Optional[float] = None,
    *,
    stop_delay: dict[int, int] | None = None,
    store_events: bool = False,
    detail_format: str = "flat",
    store_histogram: bool = True,
) -> HeraldingGateResult:
    """Count all gate-hit associations, optionally retaining exactly one detail format.

    Delays are physical integer ps. Internal event quantization uses bin_width.
    Overlapping heralding gates may associate the same photon more than once.
    """
    width = validate_bin_width(resolution_ps)
    if (
        bins <= 0
        or not ch_photons
        or len(set([ch_gate] + list(ch_photons))) != len(ch_photons) + 1
    ):
        raise ValueError(
            "positive bins and distinct heralding/gated channels are required"
        )
    if detail_format not in {"flat", "per_gate"}:
        raise ValueError("detail_format must be 'flat' or 'per_gate'")
    delays = dict.fromkeys(ch_photons, 0) if stop_delay is None else stop_delay
    if set(delays) != set(ch_photons) or any(
        not isinstance(d, (int, np.integer)) for d in delays.values()
    ):
        raise ValueError("stop_delay must map every gated channel to integer ps")
    duration = (
        _infer_duration(timestamps_ps)
        if duration is None
        else duration
    )
    herald = np.floor_divide(timestamps_ps[channels == ch_gate], width)
    signals = {
        ch: np.floor_divide(timestamps_ps[channels == ch] + delays[ch], width)
        for ch in ch_photons
    }
    hists = (
        {ch: np.zeros(bins, dtype=np.uint64) for ch in ch_photons}
        if store_histogram
        else {}
    )
    counts = dict.fromkeys(ch_photons, 0)
    photons, hit_channels, offsets, gates = [], [], [0], []
    start, stop = bin_offset * width, (bin_offset + bins) * width

    # Use the native correspondence kernel when it is available.  The C
    # function returns absolute signal-bin values and channel positions within
    # ``ch_photons``; convert those values to the public relative-ps format
    # before accumulating histograms and optional event details.
    native_hits = None
    if _LIBCOINC is not None and hasattr(_LIBCOINC, "tdc_compute_gate_photons"):
        signal_arrays = [np.ascontiguousarray(signals[ch], dtype=np.int64) for ch in ch_photons]
        n_signals = len(signal_arrays)
        SignalPtrArray = ctypes.POINTER(ctypes.c_int64) * n_signals
        signal_ptrs = SignalPtrArray()
        signal_lengths = (ctypes.c_int * n_signals)()
        for index, signal in enumerate(signal_arrays):
            signal_ptrs[index] = signal.ctypes.data_as(ctypes.POINTER(ctypes.c_int64))
            signal_lengths[index] = len(signal)
        # Shift the native gate start by bin_offset so the C window matches
        # [ref + bin_offset, ref + bin_offset + bins).
        gate_array = np.ascontiguousarray(herald + bin_offset, dtype=np.int64)
        max_hits = max(1, sum(len(signal) for signal in signal_arrays))
        while True:
            out_photons = np.empty(max_hits, dtype=np.int64)
            out_channels = np.empty(max_hits, dtype=np.int32)
            out_offsets = np.empty(len(gate_array) + 1, dtype=np.int32)
            out_count = ctypes.c_int(0)
            err = _LIBCOINC.tdc_compute_gate_photons(
                gate_array.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(gate_array),
                ctypes.cast(signal_ptrs, ctypes.POINTER(ctypes.POINTER(ctypes.c_int64))),
                signal_lengths,
                n_signals,
                int(bins),
                out_photons.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                out_channels.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                out_offsets.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                max_hits,
                ctypes.byref(out_count),
            )
            if err == -2:
                max_hits *= 2
                continue
            if err != 0:
                logger.warning(
                    "C-based tdc_compute_gate_photons returned error %d; using Python fallback",
                    err,
                )
            else:
                native_hits = (
                    out_photons[: out_count.value].copy(),
                    out_channels[: out_count.value].copy(),
                    out_offsets[: len(gate_array) + 1].copy(),
                )
            break

    if native_hits is not None:
        absolute_photons, channel_positions, native_offsets = native_hits
        for gate_index, ref in enumerate(herald):
            gate_hits = [] if store_events and detail_format == "per_gate" else None
            first = int(native_offsets[gate_index])
            last = int(native_offsets[gate_index + 1])
            for absolute, position in zip(
                absolute_photons[first:last], channel_positions[first:last], strict=True
            ):
                ch = ch_photons[int(position)]
                relative = (int(absolute) - int(ref)) * width
                counts[ch] += 1
                if store_histogram:
                    hist_bin = (relative - start) // width
                    if 0 <= hist_bin < bins:
                        hists[ch][hist_bin] += 1
                if gate_hits is not None:
                    gate_hits.append((relative, ch))
                elif store_events:
                    photons.append(relative)
                    hit_channels.append(ch)
            if gate_hits is not None:
                gates.append(gate_hits)
            elif store_events:
                offsets.append(len(photons))
    else:
        for ref in herald:
            gate_hits = [] if store_events and detail_format == "per_gate" else None
            for ch, signal in signals.items():
                low = np.searchsorted(signal, int(ref) + bin_offset)
                high = np.searchsorted(signal, int(ref) + bin_offset + bins)
                relative = (signal[low:high] - ref) * width
                counts[ch] += len(relative)
                if store_histogram:
                    hists[ch] += np.bincount(
                        (relative - start) // width, minlength=bins
                    ).astype(np.uint64)
                if gate_hits is not None:
                    gate_hits.extend((int(delay), ch) for delay in relative)
                elif store_events:
                    photons.extend(relative)
                    hit_channels.extend([ch] * len(relative))
            if gate_hits is not None:
                gates.append(gate_hits)
            elif store_events:
                offsets.append(len(photons))
    return HeraldingGateResult(
        heralding_channel=ch_gate,
        gated_channels=tuple(ch_photons),
        mode="histogram" if store_histogram else "window_count",
        bin_width=width,
        counts_heralding=[len(herald)],
        singles_heralding=[_singles_rate(len(herald), duration)],
        counts_gated={ch: [len(signal)] for ch, signal in signals.items()},
        singles_gated={
            ch: [_singles_rate(len(signal), duration)] for ch, signal in signals.items()
        },
        duration=[duration],
        stop_delay={ch: [delay] for ch, delay in delays.items()},
        window_start=[start],
        window_stop=[stop],
        raw_counts={ch: [count] for ch, count in counts.items()},
        histogram={ch: [hist] for ch, hist in hists.items()}
        if store_histogram
        else None,
        bin_edges=[np.arange(bin_offset, bin_offset + bins + 1, dtype=np.int64) * width]
        if store_histogram
        else None,
        n_bins=[bins] if store_histogram else None,
        stop_offset=[start] if store_histogram else None,
        flat_photons=[np.asarray(photons, dtype=np.int64)]
        if store_events and detail_format == "flat"
        else None,
        flat_channels=[np.asarray(hit_channels, dtype=np.int32)]
        if store_events and detail_format == "flat"
        else None,
        flat_offsets=[np.asarray(offsets, dtype=np.int64)]
        if store_events and detail_format == "flat"
        else None,
        per_gate=[gates] if store_events and detail_format == "per_gate" else None,
    )


# ---------------------------------------------------------------------------
def bin_offset_from_peak(peak: int, loffset: int) -> int:
    """Calculate bin_offset from peak position and left offset."""
    return peak - loffset


# ---------------------------------------------------------------------------
# Multi-pair convenience
# ---------------------------------------------------------------------------


def measure_multiple_g2(
    backend: TDCBackend,
    duration: float,
    pairs: List[Tuple[int, int]],
    bins: int = 500,
    resolution_ps: Optional[float] = None,
    peak: int = 0,
    loffset: int = 0,
) -> Tuple[np.ndarray, List[np.ndarray]]:
    """Measure multiple coincidence histograms from a single readout.

    Args:
        backend:       The connected TDC backend.
        duration:      Measurement duration in seconds.
        pairs:         List of ``(ch_start, ch_stop)`` channel index pairs.
        bins:          Number of bins.
        resolution_ps: Override resolution (uses backend default if ``None``).
        peak:          Peak position in bins.
        loffset:       Left offset of the coincidence window.

    Returns:
        ``(bin_centers, list_of_histograms)`` where *bin_centers* is in ps.
    """
    ts_res = backend.get_timestamps(duration)
    res_ps = resolution_ps if resolution_ps is not None else ts_res.resolution_ps

    histograms = []
    bin_centers = None

    for ch_start, ch_stop in pairs:
        g2_res = compute_g2(
            timestamps_ps=ts_res.timestamps,
            channels=ts_res.channels,
            ch_start=ch_start,
            ch_stop=ch_stop,
            bins=bins,
            resolution_ps=res_ps,
            bin_offset=bin_offset_from_peak(peak, loffset),
            duration=ts_res.duration_s,
        )
        histograms.append(g2_res.histogram[0])
        if bin_centers is None:
            bin_centers = g2_res.bin_edges[0][:-1] / 2.0 + g2_res.bin_edges[0][1:] / 2.0

    return bin_centers, histograms
