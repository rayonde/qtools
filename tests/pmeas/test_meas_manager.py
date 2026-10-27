from unittest.mock import MagicMock

from qtools.pmeas.meas_manager import MeasManager, _calc_stats


def test_calc_stats():
    m, s = _calc_stats([10.0, 12.0, 14.0])
    assert m == 12.0
    assert s > 0.0


class _FakeTDC:
    def __init__(self, singles: list[float]) -> None:
        self.backend = MagicMock()
        self.set_threshold = MagicMock()
        self.measure_singles = MagicMock(return_value=singles)
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
    tdc = _FakeTDC([10.0, 20.0])
    manager = _manager_with_tdc(tdc)

    res = manager.measure(
        detector="tdc",
        meas_type="singles",
        channels=[0],
        task="calibration",
        duration=0.05,
        samples=2,
    )

    assert res.value == 15.0
    assert res.error > 0.0
    assert res.unit == "counts"
    tdc.set_threshold.assert_called_once_with(0.1)
    tdc.measure_singles.assert_called_once_with(duration=0.05, num=2)

    manager.disconnect_all()
    tdc.disconnect.assert_called_once()
