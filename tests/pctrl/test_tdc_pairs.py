from unittest.mock import MagicMock

import pytest

from qtools.pctrl.meas_manager import MeasManager


class _FakeTDC:
    def __init__(self):
        self.set_threshold = MagicMock()
        self.measure_pairs_samples = MagicMock(
            return_value={
                "net_pair_rate": 12.5,
                "net_pair_rate_std": 0.7,
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _manager_with_tdc(tdc):
    manager = object.__new__(MeasManager)
    manager.tdc = tdc
    return manager


def test_tdc_pairs_uses_public_tdc_api():
    tdc = _FakeTDC()
    manager = _manager_with_tdc(tdc)

    result = manager.measure(
        duration=2.0,
        samples=3,
        measure_type="pairs",
        ch_start=1,
        ch_stop=4,
        delay=100,
        window_start=109,
        window_stop=110,
        threshvolt=0.6,
    )

    tdc.set_threshold.assert_called_once_with(0.6)
    tdc.measure_pairs_samples.assert_called_once_with(
        duration=2.0,
        ch_start=1,
        ch_stop=4,
        delay=100,
        window_start=109,
        window_stop=110,
        num=3,
    )
    assert result == [(12.5, 0.7)]


def test_tdc_pairs_requires_window():
    manager = _manager_with_tdc(_FakeTDC())

    with pytest.raises(ValueError, match="window_start and window_stop"):
        manager.measure(
            duration=1.0,
            measure_type="pairs",
            ch_start=1,
            ch_stop=4,
        )
