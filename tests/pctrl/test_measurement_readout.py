from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from qtools.pctrl.meas_manager import MeasManager
from qtools.powermeter import get_device


def manager(*, tdc=None, pm=None):
    mgr = object.__new__(MeasManager)
    mgr.cfg = None
    mgr.cal_cfg = SimpleNamespace(meas_params={}, pm_config={})
    mgr.tdc = tdc
    mgr.pm = pm
    return mgr


def test_powermeter_uses_public_sampling_api(monkeypatch):
    from qtools.powermeter import measurement

    monkeypatch.setattr(measurement.time, "sleep", lambda _: None)
    pm = get_device("mock", "MOCK", base_power=0.002, noise_level=0, drift_rate=0)
    pm.get_power = MagicMock(return_value=0.002)
    result = manager(pm=pm).measure(duration=0.25, samples=3)

    assert np.asarray(result) == pytest.approx(np.array([[0.002, 0]]))
    assert pm.get_power.call_count == 3
    assert not pm.connected


def test_invalid_tdc_channel_does_not_fall_back_to_powermeter():
    tdc = MagicMock()
    tdc.measure_singles.return_value = [(1, np.array([5, 10]))]
    pm = MagicMock()
    with pytest.raises(ValueError, match="out of range"):
        manager(tdc=tdc, pm=pm).measure(channels=[3])
    pm.__enter__.assert_not_called()


def test_tdc_connection_failure_can_fall_back_to_powermeter():
    tdc = MagicMock()
    tdc.__enter__.side_effect = ConnectionError("offline")
    mgr = manager(tdc=tdc, pm=MagicMock())
    mgr._measure_pm = MagicMock(return_value=(3, 0))
    assert mgr.measure() == [(3, 0)]


def test_empty_tdc_singles_gives_useful_error():
    tdc = MagicMock()
    tdc.measure_singles.return_value = []
    with pytest.raises(RuntimeError, match="no singles"):
        manager(tdc=tdc)._measure_tdc()


@pytest.mark.parametrize(
    "records,expected",
    [
        ([(1, 100, np.array([4000, 1000])), (2, 100, np.array([2000]))], [1e-9, 2e-9, 4e-9]),
        ([], []),
        ([(1, 100, np.array([]))], []),
    ],
)
def test_raw_timestamps_are_sorted_seconds(records, expected):
    tdc = MagicMock()
    tdc.measure_timestamps.return_value = records
    result = manager(tdc=tdc).read_raw(duration=0.5, channels=[1, 2])

    assert isinstance(result, np.ndarray)
    assert result.shape == (len(expected),)
    assert np.allclose(result, expected, rtol=1e-12, atol=0)
    tdc.measure_timestamps.assert_called_once_with(duration=0.5, channels=[1, 2], unit="ps")

def test_tdc_rescan_uses_public_list_tdc(monkeypatch):
    import qtools.pctrl.meas_manager as meas_manager

    cfg = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    cal = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    opt = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    mgr = object.__new__(MeasManager)
    mgr.cfg = cfg
    mgr.cal_cfg = cal
    mgr.opt_cfg = opt

    device = SimpleNamespace(
        backend_name="exp_s15_tdc1",
        device_path="COM17",
    )
    list_tdc = MagicMock(return_value=[device])
    monkeypatch.setattr(meas_manager.tdc, "list_tdc", list_tdc)

    assert mgr._rescan_tdc() == {
        "backend": "exp_s15_tdc1",
        "port": "COM17",
    }
    list_tdc.assert_called_once_with(method="all", timeout=1.0)
    assert cfg._cfg["detectors"]["tdc"]["backend"] == "exp_s15_tdc1"
    cfg.set_device_port.assert_called_once_with("tdc", "COM17")
    assert cal._cfg["devices"]["tdc"]["backend"] == "exp_s15_tdc1"
    assert opt._cfg["devices"]["tdc"]["backend"] == "exp_s15_tdc1"


def test_discovery_saves_via_public_powermeter_api(monkeypatch):
    import qtools.pctrl.meas_manager as meas_manager

    cfg = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    cal = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    opt = SimpleNamespace(_cfg={}, set_device_port=MagicMock(), save=MagicMock())
    mgr = object.__new__(MeasManager)
    mgr.cfg = cfg
    mgr.cal_cfg = cal
    mgr.opt_cfg = opt

    monkeypatch.setattr(meas_manager.tdc, "list_tdc", lambda **_kwargs: [])
    detect = MagicMock(return_value=("GPIB0::1::INSTR", "thorlabs"))
    monkeypatch.setattr(
        meas_manager.powermeter,
        "auto_detect_connected_device",
        detect,
    )

    mgr.discover_and_save()

    detect.assert_called_once_with()
    assert cfg._cfg["devices"]["powermeter"] == {
        "backend": "thorlabs",
        "port": "GPIB0::1::INSTR",
    }
    cfg.set_device_port.assert_called_once_with(
        "powermeter", "GPIB0::1::INSTR"
    )
