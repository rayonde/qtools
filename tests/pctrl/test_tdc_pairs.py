from unittest.mock import MagicMock

import pytest

from qtools.pctrl.meas_manager import MeasManager
from qtools.tdc.data import CoincidenceResult


class _FakeTDC:
    def __init__(self):
        self.set_threshold = MagicMock()
        self.bin_width = 2_000
        self.backend = type("Backend", (), {"resolution_ps": 2_000})()
        self.measure_coincidence = MagicMock(
            return_value=CoincidenceResult(
                mode="window_count", bin_width=2_000, samples=2,
                channel_start=1, channel_stop=4,
                counts_start=[100, 100], counts_stop=[100, 100],
                singles_start=[100.0, 100.0], singles_stop=[100.0, 100.0],
                integration_time=[1.0, 1.0], stop_delay=[0, 0],
                window_start=[218_000, 218_000], window_stop=[220_000, 220_000],
                raw_counts=[14, 15], accidental_counts=[1, 1],
                accidental_method=["sideband", "sideband"],
            )
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
    tdc.measure_coincidence.assert_called_once_with(
        duration=2.0,
        ch_start=1,
        ch_stop=4,
        ch_stop_delay=200.0,
        unit="ns",
        window_start=218.0,
        window_stop=220.0,
        samples=3,
    )
    assert result[0][0] == 13.5


def test_tdc_pairs_requires_window():
    manager = _manager_with_tdc(_FakeTDC())

    with pytest.raises(ValueError, match="window_start and window_stop"):
        manager.measure(
            duration=1.0,
            measure_type="pairs",
            ch_start=1,
            ch_stop=4,
        )
