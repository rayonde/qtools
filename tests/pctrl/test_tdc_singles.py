import numpy as np
import pytest

from qtools.pctrl.meas_manager import MeasManager


class _FakeTDC:
    def __init__(self, counts):
        self.counts = counts
        self.singles_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def measure_singles(self, duration, num=1):
        self.singles_calls.append((duration, num))
        return [
            (duration, np.asarray(self.counts, dtype=float))
            for _ in range(num)
        ]


def _manager_with_tdc(tdc):
    mgr = object.__new__(MeasManager)
    mgr.tdc = tdc
    return mgr


def test_tdc_singles_selects_requested_channel():
    tdc = _FakeTDC([10, 22, 30, 40])
    mgr = _manager_with_tdc(tdc)

    result = mgr._measure_tdc(duration=2.0, samples=2, channels=[2])

    assert tdc.singles_calls == [(2.0, 2)]
    assert len(result) == 1
    mean, std = result[0]
    assert mean == pytest.approx(11.0)  # 22/2 and 22/2
    assert std == pytest.approx(0.0)


def test_tdc_singles_raises_for_out_of_range_channel():
    tdc = _FakeTDC([10, 20, 30, 40])
    mgr = _manager_with_tdc(tdc)

    with pytest.raises(ValueError, match="out of range"):
        mgr._measure_tdc(duration=1.0, channels=[5])
