"""Native coincidence backend and Python fallback regression tests."""

from __future__ import annotations

import platform
from pathlib import Path

import numpy as np
import pytest

from qtools.tdc.analysis import g2


def test_native_coincidences_library_is_loaded_when_packaged() -> None:
    """The packaged platform library must actually be picked up by ctypes."""
    suffix = {"Windows": ".dll", "Linux": ".so", "Darwin": ".dylib"}[platform.system()]
    native_path = Path(g2.__file__).resolve().parents[1] / "_native" / f"libcoincidences{suffix}"
    if not native_path.exists():
        pytest.skip(f"native coincidences library not packaged for this platform: {native_path}")

    assert g2._LIBCOINC is not None
    for symbol in (
        "tdc_compute_g2",
        "tdc_compute_triplet",
        "tdc_compute_gate",
        "tdc_compute_gate_photons",
    ):
        assert hasattr(g2._LIBCOINC, symbol), symbol


def test_python_gate_fallback_terminates_after_cartesian_product(monkeypatch) -> None:
    """Regression test for the fallback odometer hanging after a wrapped carry."""
    monkeypatch.setattr(g2, "_LIBCOINC", None)

    timestamps = np.array([0, 10, 1, 11, 2, 12], dtype=np.int64)
    channels = np.array([0, 0, 1, 1, 2, 2], dtype=np.uint8)

    result = g2.compute_gate_coincidence(
        timestamps_ps=timestamps,
        channels=channels,
        ch_ref=0,
        ch_signals=[1, 2],
        bins=5,
        resolution_ps=1.0,
        integration_time=1.0,
        store_events=True,
    )

    assert result.raw_counts[0] == 2
    assert len(result.events[0]) == 2
    np.testing.assert_array_equal(result.pairwise_hists[(0, 1)][0], [0, 2, 0, 0, 0])
    np.testing.assert_array_equal(result.pairwise_hists[(0, 2)][0], [0, 0, 2, 0, 0])
