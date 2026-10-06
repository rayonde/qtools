"""Verify correctness of the native C-based g2 coincidence histogram algorithm."""

from __future__ import annotations

import numpy as np

from qtools.tdc.analysis.g2 import compute_g2, _compute_g2_python


def test_g2_c_int_based_computation():
    """Verify that the g2 computation is correct for int-based (bin units) timestamps."""
    np.random.seed(42)

    # Generate integer timestamps in bin units directly
    max_bin = 1000000
    n1 = 5000
    n2 = 5000

    t1_bins = np.sort(np.random.randint(0, max_bin, size=n1).astype(np.int64))
    t2_bins = np.sort(np.random.randint(0, max_bin, size=n2).astype(np.int64))

    # Add a correlation peak: t2 occurs 120-150 bins after t1
    coinc = np.random.randint(0, max_bin - 200, size=500)
    t1_bins = np.sort(np.concatenate([t1_bins, coinc]))
    t2_correlated = coinc + np.random.randint(120, 150, size=500)
    t2_bins = np.sort(np.concatenate([t2_bins, t2_correlated]))

    # Build unified format (timestamps = bins, resolution_ps = 1 so bins = ts)
    resolution_ps = 1.0
    timestamps = np.concatenate([t1_bins, t2_bins])
    channels = np.concatenate([
        np.zeros(len(t1_bins), dtype=np.uint8),
        np.ones(len(t2_bins), dtype=np.uint8),
    ])
    sort_idx = np.argsort(timestamps)
    timestamps = timestamps[sort_idx]
    channels = channels[sort_idx]

    bins = 100
    bin_offset = 0

    # Compute using the production path (C if available, else Python)
    res = compute_g2(
        timestamps_ps=timestamps,
        channels=channels,
        ch_start=0,
        ch_stop=1,
        bins=bins,
        resolution_ps=resolution_ps,
        bin_offset=bin_offset,
    )

    # Compute using pure Python reference
    # Extract and prepare arrays the same way compute_g2 does
    t1_ps = timestamps[channels == 0]
    t2_ps = timestamps[channels == 1]
    t1_ref = (t1_ps / resolution_ps).astype(np.int64)
    t2_ref = (t2_ps / resolution_ps).astype(np.int64) - bin_offset
    ref_hist = _compute_g2_python(t1_ref, t2_ref, bins)

    # Assert identical
    np.testing.assert_array_equal(res.histogram, ref_hist,
                                  err_msg="C/native g2 output must match Python reference")
    assert res.histogram.sum() > 0
    assert res.n_bins == bins


def test_g2_empty_input_returns_offset_histogram():
    """Empty acquisitions still return the requested window metadata."""
    res = compute_g2(
        timestamps_ps=np.array([], dtype=np.int64),
        channels=np.array([], dtype=np.uint8),
        ch_start=0,
        ch_stop=1,
        bins=4,
        resolution_ps=2.0,
        bin_offset=-3,
        integration_time=0.5,
    )

    np.testing.assert_array_equal(res.histogram, np.zeros(4, dtype=np.uint64))
    np.testing.assert_array_equal(res.bin_edges, np.arange(-3, 2, dtype=np.float64))
    assert res.singles_start == 0.0
    assert res.singles_stop == 0.0
    assert res.integration_time == 0.5
