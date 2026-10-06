import numpy as np
import pytest

from qtools.tomo.tomography.TomoUncertainties import (
    _calc_asymmetric_stats,
    _get_projector,
    compute_state_uncertainties,
)
from qtools.tomo.tomography.interface import run_tomography


CANONICAL_STATES = {
    "H": [1, 0],
    "V": [0, 1],
    "D": [1, 1],
    "A": [1, -1],
    "R": [1, "1j"],
    "L": [1, "-1j"],
}


def _one_qubit_rows(count=50):
    return [{"basis": [name], "counts": [count]} for name in CANONICAL_STATES]


def test_complex_projector_vectorization_matches_trace_model():
    projector = _get_projector(["R"])
    rho = np.array([[0.7, 0.1 - 0.2j], [0.1 + 0.2j, 0.3]], dtype=complex)
    expected = np.trace(projector @ rho)
    vectorized = np.dot(projector.T.flatten(), rho.flatten())
    assert np.isclose(vectorized, expected)


def test_unknown_canonical_basis_is_rejected_instead_of_mapped_to_h():
    with pytest.raises(ValueError, match="Unknown measurement basis"):
        _get_projector(["not-a-state"])

    result = compute_state_uncertainties(
        [{"basis": ["not-a-state"], "counts": [20]}],
        np.eye(2, dtype=complex) / 2,
        n_qubits=1,
    )
    assert result["purity_ci"] is None


def test_custom_measurement_state_names_are_used():
    custom_states = {
        "zero": [1, 0],
        "one": [0, 1],
        "plus": [1, 1],
        "right": [1, "1j"],
    }
    rows = [{"basis": [name], "counts": [40]} for name in custom_states]
    result = compute_state_uncertainties(
        rows,
        np.eye(2, dtype=complex) / 2,
        n_qubits=1,
        measurement_states=custom_states,
        n_samples=12,
    )
    assert result["purity_ci"] is not None


def test_zero_coincidence_counts_do_not_create_uncertainty():
    rows = [
        {"basis": ["H", "H"], "counts": [100, 100, 0]},
        {"basis": ["V", "V"], "counts": [100, 100, 0]},
    ]
    result = compute_state_uncertainties(
        rows,
        np.eye(4, dtype=complex) / 4,
        n_qubits=2,
        measurement_states=CANONICAL_STATES,
    )
    assert all(value is None for value in result.values())


def test_fidelity_uncertainty_is_omitted_without_target_state():
    result = compute_state_uncertainties(
        _one_qubit_rows(),
        np.eye(2, dtype=complex) / 2,
        target_state=None,
        n_qubits=1,
        measurement_states=CANONICAL_STATES,
        n_samples=12,
    )
    assert result["fidelity_std"] is None
    assert result["fidelity_ci"] is None
    assert result["purity_ci"] is not None


def test_boundary_ci_is_anchored_to_point_estimate():
    stats = _calc_asymmetric_stats([0.8, 0.9, 0.95], v0=1.0)
    assert stats["ci"][1] == 1.0
    assert stats["err_plus"] == 0.0
    assert stats["ci"][0] == stats["err_minus"] * -1 + 1.0


def test_interface_ignores_singles_when_coincidences_are_empty():
    data = {
        "n_qubits": 2,
        "n_detectors_per_qubit": 1,
        "n_measurements_per_qubit": 1,
        "coincidence_window": [0],
        "measurement_states": CANONICAL_STATES,
        "data": [{"basis": ["H", "H"], "counts": [100, 100, 0]}],
    }
    result = run_tomography(data=data, target_state=None)
    assert result["intensity"] == 0.0
    assert result["purity_ci"] is None
