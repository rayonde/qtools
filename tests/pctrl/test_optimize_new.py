import pytest
import numpy as np
from pathlib import Path
from qtools.pctrl import PolarizationController
from qtools.pctrl.optimize import (
    OptimizeResult,
    _relative_noise_tolerance,
)


def test_optimize_result_subclassing_list(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    # 1. Test basic maximization (default metric)
    res = ctrl.optimize(target="alice", maxiter=10)

    # Assert OptimizeResult behaves like a list
    assert isinstance(res, list)
    assert len(res) == 1
    assert isinstance(res[0], float)

    # Assert new OptimizeResult properties are accessible
    assert isinstance(res, OptimizeResult)
    assert hasattr(res, "success")
    assert isinstance(res.success, bool)
    assert isinstance(res.optimal_value, float)
    assert isinstance(res.n_iterations, int)
    assert isinstance(res.n_evaluations, int)
    assert isinstance(res.message, str)
    assert isinstance(res.history, list)
    assert len(res.history) > 0

    ctrl.close()


def test_optimize_minimize_and_save(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    # Custom metric: quadratic bowl centered at 15.0 deg
    def quadratic_bowl(_meas_mgr):
        angles = ctrl.get_angles(target="alice1550_qwp_1")
        current_angle = angles.get("alice1550_qwp_1", 0.0) or 0.0
        return float((current_angle - 15.0) ** 2)

    # Minimize with save option
    res = ctrl.optimize(
        target="alice1550_qwp_1",
        metric_fn=quadratic_bowl,
        minimize=True,
        maxiter=30,
        save=True,
        step_size_deg=10.0,
    )

    assert res.success
    # The optimal value should be small after minimization
    assert res.optimal_value < 50.0
    assert abs(res.optimal_angles[0] - 15.0) < 20.0

    ctrl.close()

    # Reload config to verify it was saved
    from qtools.pctrl.config import ConfigManager
    cfg = ConfigManager(str(config_file))
    cfg.load()
    s = cfg.get_servo("alice1550_qwp_1")
    assert "optimal_phys_angle" in s


def test_optimize_simulation_warm_start(tmp_path):
    # Setup a channel config with fit/model parameters
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    basis: "h"
    input_alpha: 0.7854
    input_beta: 0.0
    gain: 1.0
    bg_offset: 0.0
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        cal_scale: 1.0
        cal_offset_deg: 10.0
        a_wobble: 0.0
        b_wobble: 0.0
"""
    config_file.write_text(config_content)

    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    # Run optimization with default mock metric
    res = ctrl.optimize(target="alice", maxiter=20)
    assert isinstance(res, OptimizeResult)
    ctrl.close()


def test_optimize_cli_maximize(tmp_path):
    from unittest.mock import patch
    from qtools.pctrl.cli import main

    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
      - name: "alice1550_hwp_2"
        group: "alice"
        servo_id: 2
        waveplate: "HWP"
        order: 2
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
      - name: "alice1550_qwp_3"
        group: "alice"
        servo_id: 3
        waveplate: "QWP"
        order: 3
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    with patch(
        "sys.argv",
        [
            "pctrl",
            "--mock",
            "-c",
            str(config_file),
            "optimize",
            "alice",
            "--maxiter",
            "5",
            "--maximize",
            "--measure",
            "singles",
            "--channel",
            "1",
            "--time",
            "2",
            "--samples",
            "1",
            "--tol",
            "1.0",
        ],
    ):
        main()


def test_optimize_cli_pairs_forwards_parameters():
    from unittest.mock import patch
    from qtools.pctrl.cli import main

    with patch("qtools.pctrl.PolarizationController") as mock_ctrl:
        mock_ctrl.return_value.optimize.return_value = []
        with patch(
            "sys.argv",
            [
                "pctrl",
                "optimize",
                "alice",
                "--measure",
                "pairs",
                "--ch_start",
                "1",
                "--ch_stop",
                "4",
                "--delay",
                "100",
                "--ws",
                "109",
                "--we",
                "110",
                "--threshvolt",
                "0.6",
                "--duration",
                "0.5",
                "--samples",
                "3",
            ],
        ):
            main()

    kwargs = mock_ctrl.return_value.optimize.call_args.kwargs
    assert kwargs["measure_type"] == "pairs"
    assert kwargs["ch_start"] == 1
    assert kwargs["ch_stop"] == 4
    assert kwargs["delay"] == 100
    assert kwargs["window_start"] == 109
    assert kwargs["window_stop"] == 110
    assert kwargs["threshvolt"] == 0.6
    assert kwargs["duration"] == 0.5
    assert kwargs["samples"] == 3


def test_optimize_direction_flags_are_mutually_exclusive():
    from qtools.pctrl.cli import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["optimize", "alice", "--minimize", "--maximize"]
        )


def test_relative_noise_tolerance_caps_large_fluctuation():
    tolerance = _relative_noise_tolerance(base_mean=10.0, noise_std=10.0)

    assert tolerance == pytest.approx(0.5)
    assert tolerance < 0.75 * 10.0


def test_optimize_maximize_uses_high_angle(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_file.write_text(
        """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    )
    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    def angle_metric(_meas_mgr):
        return float(ctrl.get_angles("alice1550_qwp_1")["alice1550_qwp_1"])

    res = ctrl.optimize(
        target="alice1550_qwp_1",
        metric_fn=angle_metric,
        minimize=False,
        maxiter=20,
        step_size_deg=10.0,
    )

    assert res.optimal_value > 50.0
    ctrl.close()


def test_save_process_file(tmp_path):
    import json
    import csv
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    json_process_path = tmp_path / "proc.json"
    res = ctrl.optimize(
        target="alice",
        maxiter=10,
        save_config=True,
        save_process=str(json_process_path),
    )
    assert json_process_path.exists()
    data = json.loads(json_process_path.read_text())
    assert len(data) > 0
    assert "angles" in data[0]
    assert "value" in data[0]
    assert "evaluation" in data[0]

    csv_process_path = tmp_path / "proc.csv"
    res_csv = ctrl.optimize(
        target="alice",
        maxiter=10,
        save_process=str(csv_process_path),
    )
    assert csv_process_path.exists()
    with open(csv_process_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) > 0
        assert "evaluation" in reader[0]
        assert "val" in reader[0]
        assert "loss" in reader[0]
        assert "angle_1" in reader[0]

    # Test default boolean save_process=True -> optimize_process_<timestamp>.csv
    import os
    import glob
    existing_files = glob.glob("optimize_process_*.csv")
    for f in existing_files:
        os.remove(f)

    res_default = ctrl.optimize(
        target="alice",
        maxiter=5,
        save_process=True,
    )
    created_files = glob.glob("optimize_process_*.csv")
    assert len(created_files) == 1
    for f in created_files:
        os.remove(f)

    ctrl.close()
