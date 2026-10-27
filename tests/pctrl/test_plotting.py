"""Tests for --plot figure generation in calibration and optimization."""

import sys
from pathlib import Path


# Force a headless backend so plt.show() never blocks during tests.
import matplotlib
matplotlib.use("Agg", force=True)

import pytest
import numpy as np


SINGLE_SERVO_CONFIG = """
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
        retardance: 0.25
"""


def _write_config(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_file.write_text(SINGLE_SERVO_CONFIG)
    return config_file


def test_calibration_plot_generates_figures(tmp_path, monkeypatch):
    """run_calibration(plot=True) saves fit, verification, and Poincare figures."""
    config_file = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    from qtools.pctrl.calibration import run_calibration

    run_calibration(
        config=str(config_file),
        target="alice1550_qwp_1",
        basis="h",
        fast=True,
        mock=True,
        plot=True,
    )

    data_dir = tmp_path / "pctrl_calibration_data"
    pngs = sorted(data_dir.glob("*.png"))
    assert len(pngs) == 3
    names = [p.name for p in pngs]
    assert any("_fit.png" in n for n in names)
    assert any("_verification.png" in n for n in names)
    assert any("_poincare.png" in n for n in names)
    for p in pngs:
        assert p.stat().st_size > 0


def test_optimize_plot_generates_figure(tmp_path, monkeypatch):
    """PolarizationController.optimize(plot=True) saves a convergence figure."""
    config_file = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    from qtools.pctrl import PolarizationController

    ctrl = PolarizationController(config_path=str(config_file), mock=True)
    try:
        res = ctrl.optimize(target="alice", maxiter=10, plot=True)
        assert len(res.history) > 0
    finally:
        ctrl.close()

    data_dir = tmp_path / "pctrl_optimize_data"
    pngs = sorted(data_dir.glob("*.png"))
    assert len(pngs) == 1
    assert "_history.png" in pngs[0].name
    assert pngs[0].stat().st_size > 0


def test_plot_optimization_history_synthetic(tmp_path):
    """plot_optimization_history renders a synthetic history without hardware."""
    from qtools.pctrl.analysis.plotting import plot_optimization_history

    history = [
        {"evaluation": i + 1, "angles": [float(i) * 0.5, 10.0 + i],
         "value": 100.0 - i, "std": 1.5}
        for i in range(8)
    ]
    path = plot_optimization_history(
        title="alice:1550",
        servo_names=["qwp_1", "hwp_2"],
        history=history,
        success=True,
        optimal_value=92.0,
        out_dir=str(tmp_path),
    )
    assert path.exists()
    assert path.stat().st_size > 0
    # ':' in the title must not survive into the filename on Windows.
    assert ":" not in path.name
