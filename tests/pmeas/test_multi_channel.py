import numpy as np
import pytest
from qtools.pmeas.commands.calibrate import _resolve_basis
from qtools.pmeas.analysis.fit import _segment_indices_by_valleys, fit_calibration_curve
from qtools.pmeas.analysis.jones import transmission_retarder_pbs


def _hwp_transmission(theta_0_true: float, basis: str | float) -> np.ndarray:
    """Synthesize transmission through HWP plus a linear analyzer."""
    angles = np.arange(0, 180, 5)
    if isinstance(basis, str):
        analyzer_deg = {"H": 0.0, "D": 45.0, "V": 90.0, "A": -45.0}[basis]
    else:
        analyzer_deg = float(basis)
    return 1000.0 * (
        0.5
        + 0.45 * np.cos(4.0 * np.radians(angles - theta_0_true)
                        - 2.0 * np.radians(analyzer_deg))
    )


def test_hwp_basis_fit():
    """Fit converts theta_min back to the fast-axis offset for each analyzer."""
    theta_0_true = -10.0
    angles = np.arange(0, 180, 5)

    for basis in ("H", "V", "D", "A"):
        rates = _hwp_transmission(theta_0_true, basis)
        res = fit_calibration_curve(angles, rates, input_pol="H", basis=basis)
        # HWP fast axis has 90° periodicity; the fit returns the equivalent
        # angle nearest estimated_theta_0=0, so negative offsets are kept.
        assert np.isclose(
            (res["theta_0"] - theta_0_true) % 90.0,
            0.0,
            atol=0.3,
        ) or np.isclose(
            (res["theta_0"] - theta_0_true) % 90.0,
            90.0,
            atol=0.3,
        )

    res_hh = fit_calibration_curve(
        angles, _hwp_transmission(theta_0_true, "H"),
        input_pol="H", basis="H",
    )
    assert np.isclose(res_hh["theta_0"], theta_0_true, atol=0.3)

    res_hv = fit_calibration_curve(
        angles, _hwp_transmission(theta_0_true, "V"),
        input_pol="H", basis="V",
    )
    assert np.isclose(res_hv["theta_0"], theta_0_true, atol=0.3)

    res_num = fit_calibration_curve(
        angles, _hwp_transmission(theta_0_true, 22.5),
        input_pol="H", basis=22.5,
    )
    assert np.isclose(
        (res_num["theta_0"] - theta_0_true) % 90.0,
        0.0,
        atol=0.3,
    ) or np.isclose(
        (res_num["theta_0"] - theta_0_true) % 90.0,
        90.0,
        atol=0.3,
    )


def test_resolve_basis_returns_analyzer_angle():
    assert _resolve_basis(None) == 0.0
    assert _resolve_basis("H") == 0.0
    assert _resolve_basis("D") == 45.0
    assert _resolve_basis("V") == 90.0
    assert _resolve_basis("A") == -45.0
    assert _resolve_basis("22.5") == 22.5

    with pytest.raises(ValueError):
        _resolve_basis("not-an-angle")


def test_equal_input_and_basis_starting_at_valley_fits():
    """V-V scans begin at a valley and must not collapse to a constant."""
    theta_0_true = 0.0
    angles = np.arange(0, 180, 5)
    rates = 1000.0 * (0.5 - 0.45 * np.cos(4.0 * np.radians(angles - theta_0_true)))

    result = fit_calibration_curve(angles, rates, input_pol="V", basis="V")

    assert result["r_squared"] > 0.999
    assert result["amplitude"] > 500.0
    assert result["visibility"] > 0.9
    assert np.isclose(result["theta_0"] % 90.0, 45.0, atol=1e-6)


def test_jones_fit_handles_background_and_amplitude_drift():
    """Fit a non-ideal retarder while allowing slow multiplicative drift."""
    rng = np.random.default_rng(7)
    angles = np.arange(0.0, 360.1, 2.0)
    theta_0_true = -12.3
    retardance_true = 157.0
    amplitudes = 1000.0 * (1.0 + 0.18 * angles / angles.max())
    rates = (
        20.0
        + amplitudes * transmission_retarder_pbs(
            angles - theta_0_true, retardance_true
        )
        + rng.normal(0.0, 1.0, size=angles.size)
    )

    result = fit_calibration_curve(angles, rates, retardance_deg=retardance_true)

    assert np.isclose(result["theta_0"], theta_0_true, atol=0.3)
    assert np.isclose(result["retardance_deg"], retardance_true, atol=2.0)
    assert np.isclose(result["phi"], np.radians(retardance_true), atol=0.05)
    assert result["background"] == 20.0
    assert result["n_segments"] >= 4
    assert result["r_squared"] > 0.999


def test_segments_align_to_intensity_valleys():
    angles = np.arange(0, 180, 5)
    rates = _hwp_transmission(10.0, "H")

    segments = _segment_indices_by_valleys(angles, rates, None)

    assert len(segments) >= 2
    boundary_angles = [angles[segment[0]] for segment in segments[1:]]
    assert any(np.isclose(boundary, 55.0, atol=5.0) for boundary in boundary_angles)
    assert any(np.isclose(boundary, 145.0, atol=5.0) for boundary in boundary_angles)


def test_global_fit_uses_single_segment():
    theta_0_true = 2.345
    angles = np.arange(0, 180, 5)
    rates = _hwp_transmission(theta_0_true, "H")

    result = fit_calibration_curve(angles, rates, segment=False)

    assert result["n_segments"] == 1
    assert result["fit_method"] == "global"
    assert np.isclose(result["theta_0"], theta_0_true, atol=1e-6)
