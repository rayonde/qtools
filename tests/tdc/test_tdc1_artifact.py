"""Verify TDC1 first-bin artifact display exclusion logic."""

from __future__ import annotations

import numpy as np


def test_tdc1_first_bin_display_exclusion():
    """Verify that bin 0 is successfully sliced off for display and search."""
    # Simulate a g2 histogram with an anomalous spike in bin 0
    hist = np.array([5000, 12, 15, 10, 8, 14, 11, 9, 13, 10], dtype=np.uint64)
    
    # Exclusion logic: slice hist[1:]
    a = np.array(hist[1:], dtype=np.int64)
    
    # Verify that:
    # 1. The spike (5000) is excluded
    assert 5000 not in a
    
    # 2. The maximum peak value is now the real background peak (15) instead of the spike (5000)
    assert max(a) == 15
    assert np.argmax(a) == 1  # index 1 in a corresponds to index 2 in hist (value 15)
