"""TDC threshold configuration tests without physical hardware."""

from __future__ import annotations

from unittest.mock import MagicMock

from qtools.pmeas.meas_manager import MeasManager


class _FakeTDC:
    def __init__(self) -> None:
        self.backend = MagicMock()
        self.set_threshold = MagicMock()
        self.measure_pairs_samples = MagicMock(
            return_value={
                "net_pair_rate": 10.0,
                "net_pair_rate_std": 1.0,
            }
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
    """The unified tdc API applies the single threshold to all channels."""
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
    tdc.measure_pairs_samples.assert_called_once()
    kwargs = tdc.measure_pairs_samples.call_args.kwargs
    assert kwargs.get("delay") == 0
    assert "ch_stop_delay" not in kwargs


def test_pairs_forwards_delay_bin_as_delay():
    """The bins-based delay_bin config maps to measure_pairs_samples(delay=...)."""
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

    kwargs = tdc.measure_pairs_samples.call_args.kwargs
    assert kwargs.get("delay") == 3
    assert "ch_stop_delay" not in kwargs


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

    kwargs = tdc.measure_pairs_samples.call_args.kwargs
    assert kwargs.get("delay") == 5
    assert kwargs.get("window_start") == 10
    assert kwargs.get("window_stop") == 20
    assert "ch_stop_delay" not in kwargs
