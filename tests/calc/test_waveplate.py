"""Regression tests for NumPy Jones waveplate calculus."""

import numpy as np
import pytest

from qtools.calc.waveplate import (
    apply,
    bloch,
    hwp,
    pbs,
    probability,
    qwp,
    retarder,
    solve_analyzer_angles,
    stokes,
)


def test_retarder_limits_match_named_plates():
    np.testing.assert_allclose(qwp(17), retarder(17, 90))
    np.testing.assert_allclose(hwp(17), retarder(17, 180))
    np.testing.assert_allclose(hwp(0), np.diag([1, -1]))
    np.testing.assert_allclose(hwp(22.5) @ np.array([1, 0]), [1, 1] / np.sqrt(2), atol=1e-12)
    np.testing.assert_allclose(hwp(45), np.array([[0, 1], [1, 0]]), atol=1e-12)
    np.testing.assert_allclose(qwp(0, 83), np.diag([1, np.exp(1j * np.deg2rad(83))]))
    np.testing.assert_allclose(hwp(0, 169), np.diag([1, np.exp(1j * np.deg2rad(169))]))


def test_apply_uses_optical_propagation_order():
    state = np.array([1, 0], dtype=complex)
    expected = hwp(22.5) @ qwp(10) @ state
    np.testing.assert_allclose(apply(state, [qwp(10), hwp(22.5)]), expected)


def test_apply_and_retarder_broadcast_batches():
    angles = np.array([0.0, 15.0, 30.0, 45.0])
    states = apply(np.array([1, 0], dtype=complex), [hwp(angles)])
    assert states.shape == (4, 2)
    np.testing.assert_allclose(np.linalg.norm(states, axis=-1), 1.0)

    input_batch = np.broadcast_to([1, 0], (4, 2)).astype(complex)
    outputs = apply(input_batch, [qwp(angles)])
    np.testing.assert_allclose(outputs, apply(np.array([1, 0]), [qwp(angles)]))


def test_history_contains_input_and_each_stage():
    history = apply(
        np.array([1, 0], dtype=complex), [qwp(10), hwp(22.5)], return_history=True
    )
    assert history.shape == (3, 2)
    np.testing.assert_allclose(history[0], [1, 0])
    np.testing.assert_allclose(history[-1], apply([1, 0], [qwp(10), hwp(22.5)]))
    np.testing.assert_allclose(
        apply([1, 0], [], return_history=True), np.array([[1, 0]], dtype=complex)
    )


def test_pbs_probability_for_basis_states():
    assert probability(np.array([1, 0]), pbs("H")) == pytest.approx(1.0)
    assert probability(np.array([0, 1]), pbs("H")) == pytest.approx(0.0)
    assert probability(np.array([1, 1]), pbs("D")) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="axis must"):
        pbs("R")


def test_stokes_and_bloch_coordinates():
    np.testing.assert_allclose(stokes([1, 0]), [1, 1, 0, 0])
    np.testing.assert_allclose(bloch([1, 1]), [0, 1, 0])
    np.testing.assert_allclose(bloch([1, 1j]), [0, 0, -1])
    np.testing.assert_allclose(stokes([2, 0], normalize=False), [4, 4, 0, 0])


def test_analyzer_angle_helpers():
    result = solve_analyzer_angles([1, 1], ("hwp",))
    assert result["angles_deg"][0] == pytest.approx(22.5)
    assert result["fidelity"] == pytest.approx(1.0)
    result = solve_analyzer_angles([0, 1j], ("hwp",))
    assert result["angles_deg"][0] == pytest.approx(45.0)
    assert result["fidelity"] == pytest.approx(1.0)

    with pytest.raises(ValueError, match="linear polarization"):
        solve_analyzer_angles([1, 1j], ("hwp",))

    result = solve_analyzer_angles([1, 1j], ("qwp", "hwp"))
    assert result["fidelity"] == pytest.approx(1.0, abs=1e-7)


def test_analyzer_solver_accepts_measured_retardances():
    angles = (21.0, 67.0)
    retardances = (83.0, 169.0)
    # Input state selected by QWP -> HWP -> PBS-H for the known plate angles.
    target = qwp(angles[0], retardances[0]).conj().T @ hwp(
        angles[1], retardances[1]
    ).conj().T @ np.array([1, 0], dtype=complex)
    result = solve_analyzer_angles(
        target,
        ("qwp", "hwp"),
        retardances_deg=retardances,
    )
    assert result["fidelity"] == pytest.approx(1.0, abs=1e-7)
    assert result["retardances_deg"] == retardances
