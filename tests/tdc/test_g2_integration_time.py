"""Regression tests for the software g2 acquisition-time denominator."""

from __future__ import annotations

import numpy as np
import pytest

from qtools.tdc.backends.s15_tdc1.exp_backend import ExpS15TDC1Backend
from qtools.tdc.data import CoincidenceResult, TimestampResult


@pytest.mark.parametrize(
    "timestamps_ps",
    [
        # Sparse events cover only 10 ms even though acquisition ran for 1 s.
        np.array([0, 10_000_000_000], dtype=np.int64),
        # A corrupt/unwrapped timestamp must not inflate the live time.
        np.array([0, 669_670_000_000_000], dtype=np.int64),
    ],
)
def test_software_g2_uses_backend_live_time(monkeypatch, timestamps_ps):
    backend = ExpS15TDC1Backend()
    timestamps = TimestampResult(
        timestamps=timestamps_ps,
        channels=np.array([1, 2], dtype=np.uint8),
        resolution_ps=2000.0,
        total_time_ns=1_000_000_000.0,
    )
    monkeypatch.setattr(backend, "get_timestamps", lambda duration: timestamps)

    captured = {}

    def fake_compute_g2(**kwargs):
        captured.update(kwargs)
        return CoincidenceResult(mode="histogram", bin_width=int(kwargs["resolution_ps"]), channel_start=1, channel_stop=2,
            counts_start=[int(1.0 * kwargs["duration"])], counts_stop=[int(1.0 * kwargs["duration"])],
            singles_start=[1.0], singles_stop=[1.0], duration=[kwargs["duration"]], stop_delay=[0],
            n_bins=[(5 - 1)], stop_offset=[0], histogram=[np.zeros(4, dtype=np.uint64)],
            bin_edges=[np.arange((5 - 1) + 1, dtype=np.int64) * int(kwargs["resolution_ps"])],
            )

    monkeypatch.setattr("qtools.tdc.analysis.g2.compute_g2", fake_compute_g2)

    result = backend.get_g2(duration=1.0, bins=4)

    assert result.duration[0] == pytest.approx(1.0)
    assert captured["duration"] == pytest.approx(1.0)
