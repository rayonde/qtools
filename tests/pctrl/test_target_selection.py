from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from scipy.optimize import minimize

from qtools.pctrl import PolarizationController
from qtools.pctrl.config import ConfigManager
from qtools.pctrl.meas_manager import MockMeasManager


@pytest.fixture
def controller(tmp_path):
    config_path = tmp_path / "pctrl.yaml"
    cfg = ConfigManager(str(config_path))
    for path, first_id in (("alice", 1), ("bob", 4)):
        for order, waveplate in enumerate(("QWP", "HWP", "QWP"), 1):
            cfg.add_servo(path, 1550, waveplate, order, first_id + order - 1)
    cfg.save()
    with PolarizationController(str(config_path), mock=True) as ctrl:
        yield ctrl


@pytest.mark.parametrize(
    "target, expected_ids",
    [
        (["alice1550_qwp_1"], {1}),
        (["1", "alice1550_qwp_1", "bob1550_hwp_2"], {1, 5}),
        ("alice1550_qwp_1,bob1550_hwp_2", {1, 5}),
        (["alice1550_hwp_2", "alice", "bob1550_qwp_3"], {1, 2, 3, 6}),
        (["alice", "bob"], {1, 2, 3, 4, 5, 6}),
    ],
)
def test_optimize_moves_only_selected_servos(controller, target, expected_ids):
    backend = controller.servo_mgr.backend
    with patch.object(backend, "move", wraps=backend.move) as move:
        result = controller.optimize(target=target, maxiter=1, verbose=False)

    assert {call.args[0] for call in move.call_args_list} == expected_ids
    assert len(result) == len(expected_ids)
    assert len(controller.cfg.get_channel("alice", 1550)["servos"]) == 3


def test_optimize_accepts_falsey_measurement_adapter(controller):
    class FalseyAdapter(MockMeasManager):
        def __bool__(self):
            return False

    adapter = FalseyAdapter(value=42)
    controller.meas_mgr = None
    result = controller.optimize(
        "alice1550_qwp_1", measurement_adapter=adapter, maxiter=1, verbose=False
    )
    assert result.optimal_value == 42


def test_api_calibration_reuses_connected_manager(controller):
    with patch("qtools.pctrl.api.run_calibration") as run:
        controller.calibrate("alice")
    assert run.call_args.kwargs["servo_mgr"] is controller.servo_mgr


def test_optimizer_clips_current_angle_to_bounds(controller):
    controller.servo_mgr.get_angle = MagicMock(return_value=-120)
    with patch("qtools.pctrl.optimize.minimize", wraps=minimize) as run:
        controller.optimize("alice1550_qwp_1", maxiter=1, verbose=False)
    assert run.call_args.args[1] == pytest.approx([-90])


def test_multi_channel_optimization_requires_explicit_metric(controller):
    controller.meas_mgr.measure = MagicMock(return_value=[(1, 0), (2, 0)])
    with pytest.raises(ValueError, match="metric_fn"):
        controller.optimize("alice", channels=[1, 2], maxiter=1, verbose=False)


@pytest.mark.parametrize("data", [[], [[1]], [[np.nan, 0]], [[1, np.inf]]])
def test_optimizer_rejects_invalid_measurements(controller, data):
    controller.meas_mgr.measure = MagicMock(return_value=data)
    with pytest.raises(ValueError, match="Measurement"):
        controller.optimize("alice1550_qwp_1", maxiter=1, verbose=False)


def test_optimizer_rejects_nonfinite_custom_metric(controller):
    with pytest.raises(ValueError, match="metric_fn"):
        controller.optimize(
            "alice1550_qwp_1", metric_fn=lambda mgr: np.nan, maxiter=1, verbose=False
        )
