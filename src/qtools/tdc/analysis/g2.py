"""Coincidence g2 correlation analysis.

Computes second-order correlation histograms (g²), 3-fold (triplet)
coincidence histograms, and N-fold gated coincidence measurements.

All computations work in **bin units**: timestamps (picoseconds from the
backend) are converted to bin indices by integer-dividing by *resolution_ps*.
Histogram bin edges and centres are therefore expressed in bins (not ns).
"""

from __future__ import annotations

import ctypes
import logging
from typing import List, Optional, Tuple

import numpy as np

from qtools.tdc.data import G2Result, TripletResult, GateResult
from qtools.tdc.backends.base import TDCBackend


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Native C library loading
# ---------------------------------------------------------------------------

_LIBCOINC = None
_S15LIB_DELTA_LOOP = None

try:
    from qtools.tdc._native import load_libcoincidences

    _LIBCOINC = load_libcoincidences()

    # --- g2 (bin-based, int64 timestamps) ---
    _LIBCOINC.tdc_compute_g2.argtypes = [
        ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t1, len1
        ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t2, len2
        ctypes.c_int,                                     # bins
        ctypes.POINTER(ctypes.c_uint64),                  # out histogram
    ]
    _LIBCOINC.tdc_compute_g2.restype = ctypes.c_int

    # --- triplet (3-fold) ---
    try:
        _LIBCOINC.tdc_compute_triplet.argtypes = [
            ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t1, len1
            ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t2, len2
            ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t3, len3
            ctypes.c_int,                                     # bins
            ctypes.c_int,                                     # deduplicate
            ctypes.POINTER(ctypes.c_uint64),                  # out hist_21
            ctypes.POINTER(ctypes.c_uint64),                  # out hist_31
            ctypes.POINTER(ctypes.c_uint64),                  # out hist_32
            ctypes.POINTER(ctypes.c_uint64),                  # out hist_23
            ctypes.POINTER(ctypes.c_int64),                   # out_events
            ctypes.POINTER(ctypes.c_int64),                   # out_ref_idx
            ctypes.c_int,                                     # max_events
            ctypes.POINTER(ctypes.c_int),                    # out_count
        ]
        _LIBCOINC.tdc_compute_triplet.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have triplet yet

    # --- gate (N-fold) ---
    try:
        _LIBCOINC.tdc_compute_gate.argtypes = [
            ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t_ref, len_ref
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int64)),  # signals array
            ctypes.POINTER(ctypes.c_int),                    # signal lengths
            ctypes.c_int,                                     # n_signals
            ctypes.c_int,                                     # bins
            ctypes.c_int,                                     # deduplicate
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint64)), # out hists
            ctypes.POINTER(ctypes.c_uint64),                 # out n_fold (uint64_t)
            ctypes.POINTER(ctypes.c_int64),                   # out_events
            ctypes.POINTER(ctypes.c_int64),                   # out_ref_idx
            ctypes.c_int,                                     # max_events
            ctypes.POINTER(ctypes.c_int),                    # out_count
        ]
        _LIBCOINC.tdc_compute_gate.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have gate yet

    # --- gate-photon correspondence ---
    try:
        _LIBCOINC.tdc_compute_gate_photons.argtypes = [
            ctypes.POINTER(ctypes.c_int64), ctypes.c_int,   # t_gate, n_gate
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int64)),  # photon_signals
            ctypes.POINTER(ctypes.c_int),                    # signal_lengths
            ctypes.c_int,                                     # n_signals
            ctypes.c_int,                                     # bins
            ctypes.POINTER(ctypes.c_int64),                   # out_photons
            ctypes.POINTER(ctypes.c_int32),                   # out_channels
            ctypes.POINTER(ctypes.c_int32),                   # out_offsets
            ctypes.c_int,                                     # max_hits
            ctypes.POINTER(ctypes.c_int),                    # out_count
        ]
        _LIBCOINC.tdc_compute_gate_photons.restype = ctypes.c_int
    except AttributeError:
        pass  # C lib doesn't have gate-photons yet

    logger.debug("Loaded native coincidences library")
except Exception as e:
    logger.debug("Could not load native coincidences library: %s", e)

# S15lib fallback (expects float arrays and bin_width_ns)
try:
    from S15lib.g2lib.g2lib import delta_loop
    _S15LIB_DELTA_LOOP = delta_loop
    logger.debug("Loaded S15lib delta_loop fallback")
except ImportError:
    logger.debug("S15lib delta_loop not available")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _infer_integration_time(timestamps_ps: np.ndarray) -> float:
    """Estimate integration time from the span of recorded timestamps."""
    if len(timestamps_ps) > 1:
        return float(timestamps_ps[-1] - timestamps_ps[0]) * 1e-12
    return 0.0


def _singles_rate(counts: int, integration_time: float) -> float:
    """Singles count rate in cps."""
    return counts / integration_time if integration_time > 0 else 0.0


# ---------------------------------------------------------------------------
# Pure-Python fallback implementations
# ---------------------------------------------------------------------------

def _compute_g2_python(t1_bins: np.ndarray, t2_adj_bins: np.ndarray, bins: int) -> np.ndarray:
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
    t1: np.ndarray, t2: np.ndarray, t3: np.ndarray, bins: int,
    deduplicate: bool = False,
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
                        hist_21[d21] += 1; mask21[d21] = True
                    if not mask31[d31]:
                        hist_31[d31] += 1; mask31[d31] = True
                else:
                    hist_21[d21] += 1
                    hist_31[d31] += 1

                d32 = t3[k] - t2[j]
                if 0 <= d32 < bins:
                    if deduplicate:
                        if not mask32[d32]:
                            hist_32[d32] += 1; mask32[d32] = True
                    else:
                        hist_32[d32] += 1

                d23 = t2[j] - t3[k]
                if 0 <= d23 < bins:
                    if deduplicate:
                        if not mask23[d23]:
                            hist_23[d23] += 1; mask23[d23] = True
                    else:
                        hist_23[d23] += 1

                events.append(((int(val1), int(t2[j]), int(t3[k])), i))

                k += 1
            j += 1

    return hist_21, hist_31, hist_32, hist_23, events


def _compute_gate_python(
    t_ref: np.ndarray, signals: List[np.ndarray], bins: int,
    deduplicate: bool = False,
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
            # Enumerate cartesian product of matched indices (odometer)
            cursors = [0] * n_signals
            while True:
                sig_vals = tuple(int(signals[k][per_ch_matches[k][cursors[k]]])
                                 for k in range(n_signals))
                events.append(((int(ref),) + sig_vals, i))
                # Advance odometer
                for k in range(n_signals - 1, -1, -1):
                    cursors[k] += 1
                    if cursors[k] >= len(per_ch_matches[k]):
                        cursors[k] = 0
                        if k == 0:
                            break  # wrapped — done
                    else:
                        break
                else:
                    break  # all wrapped

    return hists, n_fold, events


# ---------------------------------------------------------------------------
# Internal: dispatch to best available g2 engine
# ---------------------------------------------------------------------------

def _compute_g2_delta_loop(
    t1_bins: np.ndarray, t2_adj_bins: np.ndarray, bins: int,
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
            logger.warning("C-based tdc_compute_g2 returned error %d, falling back", err)
        else:
            return hist

    if _S15LIB_DELTA_LOOP is not None:
        # S15lib expects float64 arrays and a bin_width_ns parameter.
        # Since we are already in bin units, pass bin_width=1.
        return _S15LIB_DELTA_LOOP(
            t1_bins.astype(np.float64),
            t2_adj_bins.astype(np.float64),
            bins=bins,
            bin_width_ns=1,
        ).astype(np.uint64)

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
    integration_time: Optional[float] = None,
    delay: int = 0,
) -> G2Result:
    """Compute the second-order correlation histogram g²(τ).

    All window parameters (*bin_offset*, *delay*) are expressed in **bin units**
    (i.e. multiples of *resolution_ps*).

    Args:
        timestamps_ps: Absolute timestamp values in picoseconds (int64).
        channels:      Corresponding channel indices (uint8).
        ch_start:      Index of the start channel (1-indexed).
        ch_stop:       Index of the stop channel (1-indexed).
        bins:          Number of histogram bins (must be > 0).
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        integration_time: Total integration time in seconds (optional).
        delay:         Delay to apply to ch_stop in bins.

    Returns:
        A :class:`G2Result` containing the histogram and bin boundaries.

    Raises:
        ValueError: If *bins* ≤ 0.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    # Filter timestamps for start and stop channels
    t1_ps = timestamps_ps[channels == ch_start]
    t2_ps = timestamps_ps[channels == ch_stop]

    # Convert picoseconds to bin units (integer division)
    t1_bins = (t1_ps / resolution_ps).astype(np.int64)
    t2_bins = (t2_ps / resolution_ps).astype(np.int64)

    # Apply delay compensation to stop channel directly in bin units,
    # avoiding precision loss from the float ps → int ps round-trip.
    if delay != 0:
        t2_bins = t2_bins + delay

    # Calculate actual integration time if not supplied
    if integration_time is None:
        integration_time = _infer_integration_time(timestamps_ps)

    # Compute correlation histogram
    hist = np.zeros(bins, dtype=np.uint64)
    if len(t1_bins) > 0 and len(t2_bins) > 0:
        t2_adj_bins = t2_bins - bin_offset
        hist = _compute_g2_delta_loop(t1_bins, t2_adj_bins, bins)

    # Bin edges in bin units (integer array)
    bin_edges = np.arange(bin_offset, bin_offset + bins + 1)

    # Singles count rate (counts / integration_time)
    rate_start = _singles_rate(len(t1_ps), integration_time)
    rate_stop = _singles_rate(len(t2_ps), integration_time)

    return G2Result(
        histogram=hist,
        bin_edges=bin_edges.astype(np.float64),
        singles_start=rate_start,
        singles_stop=rate_stop,
        integration_time=integration_time,
        resolution_ps=resolution_ps,
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
    integration_time: Optional[float] = None,
    deduplicate: bool = False,
) -> TripletResult:
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
        integration_time: Total integration time in seconds.
        deduplicate:   If True, each unique delay per reference event is
            counted at most once per histogram bin.

    Returns:
        A :class:`TripletResult` with four delay histograms and event list.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    # Filter and convert to bin units with window alignment
    # (only signal channels are adjusted by bin_offset, matching g2 convention)
    t1_ps = timestamps_ps[channels == ch_ref]
    t2_ps = timestamps_ps[channels == ch_sig1]
    t3_ps = timestamps_ps[channels == ch_sig2]

    t1 = (t1_ps / resolution_ps).astype(np.int64)
    t2_adj = (t2_ps / resolution_ps).astype(np.int64) - bin_offset
    t3_adj = (t3_ps / resolution_ps).astype(np.int64) - bin_offset

    if integration_time is None:
        integration_time = _infer_integration_time(timestamps_ps)

    events: list = []

    # Try C library first, then fall back to Python
    use_c = (
        _LIBCOINC is not None
        and hasattr(_LIBCOINC, "tdc_compute_triplet")
    )
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
        max_ev = 100000
        while True:
            ev_buf = np.zeros(max_ev * 3, dtype=np.int64)
            ref_buf = np.zeros(max_ev, dtype=np.int64)
            out_count = ctypes.c_int(0)
            err = _LIBCOINC.tdc_compute_triplet(
                t1_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)), len(t1_arr),
                t2_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)), len(t2_arr),
                t3_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)), len(t3_arr),
                int(bins), int(deduplicate),
                hist_21.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_31.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_32.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                hist_23.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                ev_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                ref_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                max_ev, ctypes.byref(out_count),
            )
            if err == -2:
                max_ev *= 4  # buffer too small — grow and retry
                continue
            if err != 0:
                logger.warning("C-based tdc_compute_triplet returned error %d, falling back", err)
                break
            c_ok = True
            # Unpack events from flat buffer
            for e in range(out_count.value):
                events.append((
                    (int(ev_buf[e * 3]), int(ev_buf[e * 3 + 1]), int(ev_buf[e * 3 + 2])),
                    int(ref_buf[e]),
                ))
            break

    if not c_ok:
        hist_21, hist_31, hist_32, hist_23, events = _compute_triplet_python(
            t1, t2_adj, t3_adj, bins, deduplicate=deduplicate,
        )

    # Singles rates
    rates = tuple(
        _singles_rate(len(t), integration_time)
        for t in (t1_ps, t2_ps, t3_ps)
    )

    return TripletResult(
        hist_21=hist_21,
        hist_31=hist_31,
        hist_32=hist_32,
        hist_23=hist_23,
        bins=bins,
        singles=rates,
        integration_time=integration_time,
        events=events,
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
    integration_time: Optional[float] = None,
    deduplicate: bool = False,
) -> GateResult:
    """Compute N-fold gated coincidence measurement.

    For each reference event, checks for coincidences with all signal
    channels within the window ``[bin_offset, bin_offset + bins)``.

    Pairwise histograms record every (signal[k] - ref) hit within the window.
    ``n_fold_count`` is the number of reference events where ALL signal
    channels had at least one coincidence.

    N-fold event tuples (one per combination of matched signal hits per ref)
    are appended to the ``events`` list.

    Args:
        timestamps_ps: Absolute timestamps in picoseconds (int64).
        channels:      Channel indices (uint8).
        ch_ref:        Reference channel index (0-indexed).
        ch_signals:    List of signal channel indices (0-indexed).
        bins:          Number of histogram bins.
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        integration_time: Total integration time in seconds.
        deduplicate:   If True, each unique delay per ref per channel is
            counted at most once.

    Returns:
        A :class:`GateResult` with pairwise histograms, N-fold count, and events.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")
    if not ch_signals:
        raise ValueError("ch_signals must contain at least one signal channel")

    # Filter and convert to bin units.
    # Window alignment: only signal channels are offset by bin_offset, matching
    # the g2 convention (delay = signal - bin_offset - ref). The reference
    # channel is kept unshifted.
    t_ref_ps = timestamps_ps[channels == ch_ref]
    t_ref = (t_ref_ps / resolution_ps).astype(np.int64)

    sig_ps_list = [timestamps_ps[channels == ch] for ch in ch_signals]
    sig_list = [
        (s / resolution_ps).astype(np.int64) - bin_offset for s in sig_ps_list
    ]

    if integration_time is None:
        integration_time = _infer_integration_time(timestamps_ps)

    events: list = []

    # Try C library first, then fall back to Python
    use_c = (
        _LIBCOINC is not None
        and hasattr(_LIBCOINC, "tdc_compute_gate")
    )
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
        max_ev = 100000
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
                logger.warning("C-based tdc_compute_gate returned error %d, falling back", err)
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
            t_ref, sig_list, bins, deduplicate=deduplicate,
        )

    # Singles rates
    all_channels = [ch_ref] + list(ch_signals)
    all_ts = [t_ref_ps] + sig_ps_list
    singles = [
        _singles_rate(len(t), integration_time)
        for t in all_ts
    ]

    return GateResult(
        pairwise_hists=hists,
        n_fold_count=n_fold,
        bins=bins,
        channels=all_channels,
        singles=singles,
        integration_time=integration_time,
        events=events,
    )


def _compute_gate_photons_python(
    t_gate: np.ndarray, signals: List[np.ndarray], bins: int,
) -> Tuple[List[list], list]:
    """Pure-Python gate-photon mapping fallback.

    Args:
        t_gate: Gate trigger timestamps (sorted int64, bin units).
        signals: List of photon channel timestamp arrays.
        bins: Window size in bins.

    Returns:
        (per_gate_hits, events) where *per_gate_hits* is a list-of-lists:
        ``per_gate_hits[gate_idx][photon_idx] = (ts, channel)``, and
        *events* is a flat list of ``(gate_idx, ts, channel)`` triples
        suitable for the C-compatible flat-buffer format.
    """
    n_signals = len(signals)
    per_gate: List[list] = [[] for _ in range(len(t_gate))]
    events: list = []  # flat list for compatibility with C output format
    cached_starts = [0] * n_signals

    for i in range(len(t_gate)):
        gate = t_gate[i]
        for k in range(n_signals):
            sig = signals[k]
            j = cached_starts[k]
            while j < len(sig) and sig[j] < gate:
                cached_starts[k] = j + 1
                j += 1
            while j < len(sig):
                diff = sig[j] - gate
                if diff >= bins:
                    break
                per_gate[i].append((int(sig[j]), k))
                events.append((i, int(sig[j]), k))
                j += 1

    return per_gate, events


# ---------------------------------------------------------------------------
# Gate-Photon Public API
# ---------------------------------------------------------------------------


def compute_gate_photons(
    timestamps_ps: np.ndarray,
    channels: np.ndarray,
    ch_gate: int,
    ch_photons: List[int],
    bins: int = 500,
    resolution_ps: float = 1000.0,
    bin_offset: int = 0,
    integration_time: Optional[float] = None,
) -> "GatePhotonResult":
    """Map gate (trigger) events to photon detections within a coincidence window.

    For each gate trigger event, finds ALL photon hits from each photon
    channel within ``[bin_offset, bin_offset + bins)``. Unlike gate coincidence
    there is no "all channels must hit" requirement — every photon within
    the window is recorded.

    Args:
        timestamps_ps: Absolute timestamps in picoseconds (int64).
        channels:      Channel indices (uint8).
        ch_gate:       Gate trigger channel index (0-indexed).
        ch_photons:    List of photon detection channel indices (0-indexed).
        bins:          Number of histogram bins (window width).
        resolution_ps: Time resolution in picoseconds per bin.
        bin_offset:    Start of the correlation window in bins.
        integration_time: Total integration time in seconds.

    Returns:
        A :class:`GatePhotonResult` with per-gate photon lists and flat arrays.
    """
    from qtools.tdc.data import GatePhotonResult

    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")
    if not ch_photons:
        raise ValueError("ch_photons must contain at least one photon channel")

    # Filter and convert to bin units (only signal/photon channels offset)
    t_gate_ps = timestamps_ps[channels == ch_gate]
    t_gate = (t_gate_ps / resolution_ps).astype(np.int64)

    photon_ps_list = [timestamps_ps[channels == ch] for ch in ch_photons]
    photon_list = [
        (p / resolution_ps).astype(np.int64) - bin_offset for p in photon_ps_list
    ]

    if integration_time is None:
        integration_time = _infer_integration_time(timestamps_ps)

    per_gate: list = []
    flat_photons: Optional[np.ndarray] = None
    flat_channels: Optional[np.ndarray] = None
    flat_offsets: Optional[np.ndarray] = None

    # Try C library first, then fall back to Python
    use_c = (
        _LIBCOINC is not None
        and hasattr(_LIBCOINC, "tdc_compute_gate_photons")
    )
    c_ok = False

    if use_c:
        n_signals = len(photon_list)
        t_gate_arr = np.ascontiguousarray(t_gate, dtype=np.int64)

        SigPtrArray = ctypes.POINTER(ctypes.c_int64) * n_signals
        sig_ptrs = SigPtrArray()
        sig_lens = (ctypes.c_int * n_signals)()
        sig_arrs = []
        for k, sig in enumerate(photon_list):
            arr = np.ascontiguousarray(sig, dtype=np.int64)
            sig_arrs.append(arr)
            sig_ptrs[k] = arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64))
            sig_lens[k] = len(arr)

        max_hits = 100000
        while True:
            ph_buf = np.zeros(max_hits, dtype=np.int64)
            ch_buf = np.zeros(max_hits, dtype=np.int32)
            off_buf = np.zeros(len(t_gate) + 1, dtype=np.int32)
            out_count = ctypes.c_int(0)
            err = _LIBCOINC.tdc_compute_gate_photons(
                t_gate_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                len(t_gate_arr),
                ctypes.cast(sig_ptrs, ctypes.POINTER(ctypes.POINTER(ctypes.c_int64))),
                sig_lens,
                n_signals,
                int(bins),
                ph_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                ch_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                off_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                max_hits,
                ctypes.byref(out_count),
            )
            if err == -2:
                max_hits *= 4
                continue
            if err != 0:
                logger.warning("C-based tdc_compute_gate_photons returned error %d, falling back", err)
                break
            c_ok = True
            n = out_count.value
            flat_photons = ph_buf[:n].copy()
            flat_channels = ch_buf[:n].copy()
            flat_offsets = off_buf.copy()
            # Build per-gate lists from flat buffers
            for i in range(len(t_gate)):
                start = int(flat_offsets[i])
                end = int(flat_offsets[i + 1])
                per_gate.append([
                    (int(flat_photons[p]), int(flat_channels[p]))
                    for p in range(start, end)
                ])
            break

    if not c_ok:
        per_gate, _events = _compute_gate_photons_python(
            t_gate, photon_list, bins,
        )
        # Build flat arrays from per-gate lists
        offsets = [0]
        photons_flat: list = []
        channels_flat: list = []
        for hits in per_gate:
            for ts_val, ch_val in hits:
                photons_flat.append(ts_val)
                channels_flat.append(ch_val)
            offsets.append(len(photons_flat))
        flat_photons = np.array(photons_flat, dtype=np.int64)
        flat_channels = np.array(channels_flat, dtype=np.int32)
        flat_offsets = np.array(offsets, dtype=np.int32)

    all_channels = [ch_gate] + list(ch_photons)
    all_ts = [t_gate_ps] + photon_ps_list
    singles = [
        _singles_rate(len(t), integration_time)
        for t in all_ts
    ]

    return GatePhotonResult(
        per_gate=per_gate,
        flat_photons=flat_photons,
        flat_channels=flat_channels,
        flat_offsets=flat_offsets,
        n_gates=len(t_gate),
        bins=bins,
        channels=all_channels,
        singles=singles,
        integration_time=integration_time,
    )


# ---------------------------------------------------------------------------
def bin_offset_from_peak(peak: int, loffset: int) -> int:
    """Calculate bin_offset from peak position and left offset."""
    return peak - loffset


min_range_from_peak = bin_offset_from_peak


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
        ``(bin_centers, list_of_histograms)`` where *bin_centers* is in bin units.
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
            integration_time=ts_res.duration_s,
        )
        histograms.append(g2_res.histogram)
        if bin_centers is None:
            bin_centers = g2_res.bin_centers

    return bin_centers, histograms
