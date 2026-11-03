from unittest.mock import MagicMock

import numpy as np

from qtools.pmeas.meas_manager import MeasManager, _calc_stats


def test_calc_stats():
    m, s = _calc_stats([10.0, 12.0, 14.0])
    assert m == 12.0
    assert s > 0.0


class _FakeTDC:
    def __init__(self, singles: list[float], rates: list[float] | None = None) -> None:
        self.backend = MagicMock()
        self.set_threshold = MagicMock()
        self.measure_singles = MagicMock(return_value=singles)
        self.measure_rates = MagicMock(return_value=rates or [])
        self.disconnect = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _manager_with_tdc(tdc: _FakeTDC) -> MeasManager:
    manager = MeasManager.__new__(MeasManager)
    manager.cfg = {"calibration": {"thresvolt": 0.1}}
    manager.detectors = {"tdc": tdc, "powermeter": None}
    return manager


def test_singles_measurement_uses_current_meas_manager_api():
    tdc = _FakeTDC(
        [
            (0.05, np.array([10, 100, 1000, 10000], dtype=np.uint64)),
            (0.05, np.array([20, 200, 2000, 20000], dtype=np.uint64)),
        ]
    )
    manager = _manager_with_tdc(tdc)

    res = manager.measure(
        detector="tdc",
        meas_type="singles",
        channels=1,
        task="calibration",
        duration=0.05,
        samples=2,
    )

    assert res.value == 15.0
    assert res.error > 0.0
    assert res.unit == "counts"
    assert res.metrics["counts"] == [10.0, 20.0]
    assert res.metrics["channels"] == [1]
    tdc.set_threshold.assert_called_once_with(0.1)
    tdc.measure_singles.assert_called_once_with(duration=0.05, samples=2)

    manager.disconnect_all()
    tdc.disconnect.assert_called_once()


def test_singles_without_channel_selection_sums_all_channels():
    tdc = _FakeTDC([(0.05, np.array([10, 20, 30, 40], dtype=np.uint64))])
    manager = _manager_with_tdc(tdc)

    res = manager.measure(
        detector="tdc",
        meas_type="singles",
        task="calibration",
        duration=0.05,
        samples=1,
    )

    assert res.value == 100.0
    assert res.metrics["channels"] is None


def test_rates_with_channel_selection_uses_only_requested_channel():
    tdc = _FakeTDC(
        singles=[],
        rates=[
            (0.05, np.array([20_000.0, 180_000.0, 0.0, 300_000.0])),
            (0.05, np.array([22_000.0, 182_000.0, 0.0, 302_000.0])),
        ],
    )
    manager = _manager_with_tdc(tdc)

    res = manager.measure(
        detector="tdc",
        meas_type="rates",
        channels=1,
        task="calibration",
        duration=0.05,
        samples=2,
    )

    assert res.value == 21_000.0
    assert res.unit == "cps"
    assert res.metrics["rates"] == [20_000.0, 22_000.0]
    assert res.metrics["channels"] == [1]
    tdc.measure_rates.assert_called_once_with(duration=0.05, samples=2)
