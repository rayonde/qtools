"""Finite-dimensional OAM and polarization-OAM example states."""

from __future__ import annotations

import numpy as np


def validate_l_values(l_values=(-2, -1, 0, 1, 2)):
    """Return unique integer OAM labels in the basis order supplied by the caller."""
    try:
        values = tuple(int(value) for value in l_values)
    except (TypeError, ValueError):
        raise ValueError("l_values must be a sequence of integer OAM labels")
    if not values or len(set(values)) != len(values):
        raise ValueError("l_values must be non-empty and contain no duplicates")
    return values


def oam_labels(l_values=(-2, -1, 0, 1, 2)):
    """Return the stable OAM-label-to-basis-index mapping."""
    return {label: index for index, label in enumerate(validate_l_values(l_values))}


def oam_basis_vector(ell, l_values=(-2, -1, 0, 1, 2)):
    """Return the computational OAM ket associated with label ell."""
    labels = validate_l_values(l_values)
    if int(ell) not in labels:
        raise ValueError(f"OAM label {ell} is not present in l_values={labels}")
    vector = np.zeros(len(labels), dtype=complex)
    vector[oam_labels(labels)[int(ell)]] = 1.0
    return vector


def _as_density_matrix(state):
    state = np.asarray(state, dtype=complex)
    if state.ndim == 1:
        norm = np.linalg.norm(state)
        if norm <= 1e-14:
            raise ValueError("state vector must have non-zero norm")
        state = state / norm
        return np.outer(state, state.conj())
    if state.ndim == 2 and state.shape[0] == state.shape[1]:
        state = (state + state.conj().T) / 2.0
        trace = np.real(np.trace(state))
        if trace <= 1e-14:
            raise ValueError("density matrix must have positive trace")
        return state / trace
    raise ValueError("state must be a vector or square density matrix")


def two_oam_entangled_state(l_values=(-2, -1, 0, 1, 2), l_pair=1, phase=0.0, as_density_matrix=False):
    """Construct (|la,lb> + exp(i phase)|-la,-lb>)/sqrt(2)."""
    labels = validate_l_values(l_values)
    if isinstance(l_pair, (tuple, list, np.ndarray)):
        if len(l_pair) != 2:
            raise ValueError("l_pair must contain two OAM labels")
        la, lb = (int(l_pair[0]), int(l_pair[1]))
    else:
        la = lb = int(l_pair)
    if la == 0 or lb == 0:
        raise ValueError("l_pair must use non-zero OAM labels for a two-mode entangled state")
    for value in (la, lb, -la, -lb):
        if value not in labels:
            raise ValueError(f"OAM label {value} is not present in l_values={labels}")
    ket = (np.kron(oam_basis_vector(la, labels), oam_basis_vector(lb, labels)) +
           np.exp(1j * float(phase)) * np.kron(oam_basis_vector(-la, labels), oam_basis_vector(-lb, labels))) / np.sqrt(2.0)
    return _as_density_matrix(ket) if as_density_matrix else ket


def two_qubit_oam_entangled_state(*args, **kwargs):
    """Compatibility name for two_oam_entangled_state."""
    return two_oam_entangled_state(*args, **kwargs)


def polarization_oam_skyrmion(l_values=(-2, -1, 0, 1, 2), charge=1, mixing_angle=np.pi / 4, phase=0.0, as_density_matrix=False):
    """Construct a polarization-OAM vector-vortex (skyrmion) state."""
    labels = validate_l_values(l_values)
    charge = int(charge)
    if 0 not in labels or charge not in labels:
        raise ValueError("l_values must contain both 0 and the requested charge")
    h = np.array([1.0, 0.0], dtype=complex)
    v = np.array([0.0, 1.0], dtype=complex)
    ket = (np.cos(float(mixing_angle)) * np.kron(h, oam_basis_vector(0, labels)) +
           np.exp(1j * float(phase)) * np.sin(float(mixing_angle)) * np.kron(v, oam_basis_vector(charge, labels)))
    return _as_density_matrix(ket) if as_density_matrix else ket


def polarization_oam_skyrmion_density_matrix(*args, **kwargs):
    """Return polarization_oam_skyrmion directly as a density matrix."""
    kwargs["as_density_matrix"] = True
    return polarization_oam_skyrmion(*args, **kwargs)
