"""TDC threshold and coincidence configuration tests without hardware."""

from __future__ import annotations

from unittest.mock import MagicMock

from qtools.pmeas.meas_manager import MeasManager
from qtools.tdc.data import CoincidenceResult


class _FakeTDC:
    def __init__(self) -> None:
        self.backend = MagicMock(resolution_ps=2_000)
        self.bin_width = 2_000
        self.set_threshold = MagicMock()
        self.measure_coincidence = MagicMock(
            return_value=CoincidenceResult(
                mode="window_count",
                bin_width=2_000,
                samples=1,
                unit="ns",
                channel_start=1,
                channel_stop=2,
                counts_start=[100],
                counts_stop=[100],
                singles_start=[100.0],
                singles_stop=[100.0],
                integration_time=[1.0],
                stop_delay=[0],
                window_start=[10],
                window_stop=[20],
                raw_counts=[10],
                accidental_counts=[0.0],
                accidental_method=["sideband"],
            )
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _manager_with_tdc(tdc: _FakeTDC) -> MeasManager:
    manager = MeasManager.__new__(MeasManager)
    manager.cfg = {"scan": {"thresvolt": 0.05}}
    manager.detectors = {"tdc": tdc}
    return manager


def test_pairs_sets_global_threshold_before_acquisition():
    """The unified TDC API applies the single threshold to all channels."""
    tdc = _FakeTDC()
    manager = _manager_with_tdc(tdc)

    manager.measure(
        detector="tdc",
        meas_type="pairs",
        task="scan",
        channels=[1, 2],
        duration=1.0,
    )

    tdc.set_threshold.assert_called_once_with(0.05)
    tdc.measure_coincidence.assert_called_once()
    kwargs = tdc.measure_coincidence.call_args.kwargs
    assert kwargs["ch_stop_delay"] == 0.0
    assert kwargs["unit"] == "ns"
    assert "delay" not in kwargs


def test_pairs_forwards_delay_bin_as_physical_time():
    """A bins-based delay config maps to physical time at the TDC API boundary."""
    tdc = _FakeTDC()
    manager = _manager_with_tdc(tdc)
    manager.cfg["scan"]["delay_bin"] = 3

    manager.measure(
        detector="tdc",
        meas_type="pairs",
        task="scan",
        channels=[1, 2],
        duration=1.0,
    )

    kwargs = tdc.measure_coincidence.call_args.kwargs
    assert kwargs["ch_stop_delay"] == 6.0
    assert "delay" not in kwargs


def test_pairs_forwards_delay_and_window_overrides():
    """Explicit delay/window overrides take precedence over config defaults."""
    tdc = _FakeTDC()
    manager = _manager_with_tdc(tdc)
    manager.cfg["scan"]["delay_bin"] = 0

    manager.measure(
        detector="tdc",
        meas_type="pairs",
        task="scan",
        channels=[1, 2],
        duration=1.0,
        delay=5,
        window_start=10,
        window_stop=20,
    )

    kwargs = tdc.measure_coincidence.call_args.kwargs
    assert kwargs["ch_stop_delay"] == 10.0
    assert kwargs["window_start"] == 20.0
    assert kwargs["window_stop"] == 40.0
    assert "delay" not in kwargs
