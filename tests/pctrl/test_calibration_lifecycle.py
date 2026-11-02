from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from qtools.pctrl.calibration import (
    evaluate_metric,
    generate_sweep,
    generate_sweep_angles,
    run_calibration,
    servo_sweep_bounds,
)
from qtools.pctrl.config import ConfigManager


@pytest.fixture
def config(tmp_path):
    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.add_servo("alice", 1550, "QWP", 1, 1)
    cfg.save()
    return cfg


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("borrowed", [False, True])
def test_calibration_closes_only_owned_connection(config, borrowed, fails):
    manager = MagicMock(cfg=config, mock_mode=True)
    with patch("qtools.pctrl.servo_manager.ServoManager", return_value=manager), patch(
        "qtools.pctrl.calibration.run_calibration_group"
    ) as run_group:
        if fails:
            run_group.side_effect = RuntimeError("measurement interrupted")
            with pytest.raises(RuntimeError, match="measurement interrupted"):
                run_calibration(
                    str(config.config_path), "alice", mock=True,
                    servo_mgr=manager if borrowed else None,
                )
        else:
            run_calibration(
                str(config.config_path), "alice", mock=True,
                servo_mgr=manager if borrowed else None,
            )

    assert manager.disconnect.call_count == (0 if borrowed else 1)
    if borrowed:
        assert run_group.call_args.kwargs["cfg"] is config


def test_calibration_closes_connection_on_sensor_exit(config):
    manager = MagicMock(cfg=config)
    with patch("qtools.pctrl.servo_manager.ServoManager", return_value=manager), patch(
        "qtools.pctrl.meas_manager.MeasManager"
    ) as measurement:
        measurement.return_value.measure.side_effect = ConnectionError("offline")
        with pytest.raises(SystemExit):
            run_calibration(str(config.config_path), "alice")
    manager.disconnect.assert_called_once()


@pytest.mark.parametrize("step", [0, -1, float("nan"), float("inf")])
def test_sweep_rejects_invalid_step(step):
    with pytest.raises(ValueError, match="step_deg"):
        generate_sweep_angles(step)


@pytest.mark.parametrize("left,right", [(10, 90), (-90, -10), (-90, np.inf)])
def test_sweep_requires_finite_bounds_containing_zero(left, right):
    with pytest.raises(ValueError, match="bounds"):
        generate_sweep_angles(5, left, right)


@pytest.mark.parametrize("dps", [0, -1, float("nan")])
def test_quantized_sweep_requires_positive_encoder_scale(dps):
    with pytest.raises(ValueError, match="deg_per_step"):
        generate_sweep(5, -90, 90, dps, 512)


def test_sweep_rejects_disjoint_limits():
    with pytest.raises(ValueError, match="limits"):
        servo_sweep_bounds({"min_angle": 200, "max_angle": 300})


def test_custom_metric_overrides_single_channel_readout():
    measurement = MagicMock()
    measurement.measure.return_value = [(2, 0)]
    assert evaluate_metric(measurement, metric_fn=lambda mgr: 7) == 7
