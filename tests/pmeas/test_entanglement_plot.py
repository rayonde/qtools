import csv
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from qtools.pmeas.analysis.fit import _segment_indices_by_valleys, fit_calibration_curve
from qtools.pmeas.entanglement import (
    _state_phase_rad,
    run_coincidence_scan,
)


def _hwp_transmission(theta_0_true: float) -> np.ndarray:
    angles = np.arange(0, 180, 5)
    return 1000.0 * (
        0.5
        + 0.45 * np.cos(4.0 * np.radians(angles - theta_0_true))
    )


def test_amplitude_init_accepts_per_segment_values() -> None:
    angles = np.arange(0, 180, 5)
    rates = _hwp_transmission(10.0)
    segments = _segment_indices_by_valleys(angles, rates, None)
    initial_amplitudes = [
        max(1.0, float(np.ptp(rates[indices]))) for indices in segments
    ]

    result = fit_calibration_curve(
        angles,
        rates,
        amplitude_init=initial_amplitudes,
    )

    assert np.isclose(result["theta_0"], 10.0, atol=0.3)
    assert result["r_squared"] > 0.999


def test_amplitude_init_rejects_wrong_segment_count() -> None:
    angles = np.arange(0, 180, 5)
    rates = _hwp_transmission(10.0)
    segments = _segment_indices_by_valleys(angles, rates, None)

    try:
        fit_calibration_curve(angles, rates, amplitude_init=[900.0] * (len(segments) + 1))
    except ValueError as exc:
        assert "one value per segment" in str(exc)
    else:
        raise AssertionError("amplitude_init length mismatch should raise")


def test_state_phase_estimate_uses_da_fringe_phase() -> None:
    """A D/A fringe whose signed contrast is cos(phi) recovers phi."""
    phi_expected = 0.8
    contrast = float(np.cos(phi_expected))
    scan_results = {
        "H": {
            "visibility": 1.0,
            "fit": {"coefficients": {"Bc": 1.0, "Bs": 0.0}},
        },
        "D": {
            "visibility": contrast,
            "fit": {"coefficients": {"Bc": 0.0, "Bs": contrast}},
        },
        "A": {
            "visibility": contrast,
            "fit": {"coefficients": {"Bc": 0.0, "Bs": -contrast}},
        },
    }

    assert np.isclose(_state_phase_rad(scan_results), phi_expected, atol=1e-9)


def test_scan_pairs_uses_trace_amplitude_init_and_plot_labels(tmp_path) -> None:
    class FakeStage:
        name = "bob_1560_basis_hwp"
        serial = "S"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def home(self):
            pass

        def move_to(self, angle):
            self.angle = angle

        def wait_move(self):
            pass

    stage = FakeStage()
    motor_mgr = MagicMock()
    motor_mgr.get_motor.return_value = stage
    cfg = SimpleNamespace(
        get_device=lambda target: {
            "name": "bob_1560_basis_hwp",
            "bases": {"H": 0.0, "V": 45.0, "D": 22.5, "A": 67.5},
        }
    )
    meas_mgr = MagicMock()
    meas_mgr.measure.return_value = SimpleNamespace(
        value=500.0,
        error=10.0,
        metrics={
            "raw_pair_rate": 500.0,
            "raw_pair_rate_std": 12.0,
            "acc_pair_rate": 0.0,
            "acc_pair_rate_std": 3.0,
        },
    )

    fit_calls: list[dict] = []

    def fake_fit(angles, rates, input_pol=None, basis=None, amplitude_init=None):
        fit_calls.append(
            {
                "input_pol": input_pol,
                "basis": basis,
                "amplitude_init": amplitude_init,
            }
        )
        return {
            "visibility": 0.8,
            "model_func": lambda x: np.full(np.asarray(x, dtype=float).shape, 500.0),
        }

    fig, ax = MagicMock(), MagicMock()
    path_calls: list[tuple[str, str]] = []

    def fake_get_subdir_path(subdir: str, filename: str) -> str:
        path_calls.append((subdir, filename))
        target = tmp_path / subdir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        return str(target)

    with patch("qtools.pmeas.entanglement.fit_calibration_curve", fake_fit):
        with patch("matplotlib.pyplot.subplots", return_value=(fig, ax)):
            with patch(
                "qtools.pmeas.entanglement.get_subdir_path",
                side_effect=fake_get_subdir_path,
            ):
                run_coincidence_scan(
                    motor_mgr=motor_mgr,
                    meas_mgr=meas_mgr,
                    cfg=cfg,
                    start_angle=0.0,
                    end_angle=45.0,
                    step_angle=45.0,
                    subtract_accidentals=False,
                    export=True,
                    save_plot=True,
                )

    assert len(fit_calls) == 4
    assert all(call["amplitude_init"] == 1.0 for call in fit_calls)
    ax.set_xlabel.assert_called_once_with("Bob HWP angle (°)")
    title_lines = ax.set_title.call_args.args[0].splitlines()
    assert title_lines[0] == "Polarization Coincidence scan"
    assert title_lines[1] == "H: 80.0%  V: 80.0%  D: 80.0%  A: 80.0%"
    assert (
        title_lines[2]
        == r"$|VV\rangle + \exp(i\phi)|HH\rangle$, "
        r"$\phi = 0.644$ rad ($36.9^\circ$)"
    )
    assert [subdir for subdir, _ in path_calls] == ["output", "output"]
    plot_path = tmp_path / path_calls[0][0] / path_calls[0][1]
    csv_path = tmp_path / path_calls[1][0] / path_calls[1][1]
    assert csv_path.parent == plot_path.parent
    rows = None
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header_index = next(
        i for i, row in enumerate(rows) if row and row[0] == "sweep_angle_deg"
    )
    headers = rows[header_index]
    assert "error_H (cps)" in headers
    assert "raw_error_H (cps)" in headers
    assert "acc_error_H (cps)" in headers
    data_row = rows[header_index + 1]
    assert data_row[headers.index("error_H (cps)")] == "12.0000"
    assert data_row[headers.index("raw_error_H (cps)")] == "12.0000"
    assert data_row[headers.index("acc_error_H (cps)")] == "3.0000"
