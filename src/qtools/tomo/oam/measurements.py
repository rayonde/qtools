"""Projector and synthetic-count helpers for finite-dimensional OAM tomography."""

from __future__ import annotations

from itertools import product

import numpy as np

from .states import validate_l_values


def projector(state):
    """Return the rank-one projector for a ket."""
    ket = np.asarray(state, dtype=complex).reshape(-1)
    norm = np.linalg.norm(ket)
    if norm <= 1e-14:
        raise ValueError("projector state must have non-zero norm")
    ket = ket / norm
    return np.outer(ket, ket.conj())


def polarization_projectors():
    """Return canonical H/V, D/A and R/L projectors grouped as bases."""
    root2 = np.sqrt(2.0)
    vectors = {
        "H": np.array([1.0, 0.0], dtype=complex), "V": np.array([0.0, 1.0], dtype=complex),
        "D": np.array([1.0, 1.0], dtype=complex) / root2, "A": np.array([1.0, -1.0], dtype=complex) / root2,
        "R": np.array([1.0, 1.0j], dtype=complex) / root2, "L": np.array([1.0, -1.0j], dtype=complex) / root2,
    }
    return {"HV": np.array([projector(vectors["H"]), projector(vectors["V"])]),
            "DA": np.array([projector(vectors["D"]), projector(vectors["A"])]),
            "RL": np.array([projector(vectors["R"]), projector(vectors["L"])] )}


def oam_projectors(l_values=(-2, -1, 0, 1, 2)):
    """Return computational-basis OAM projectors in supplied label order."""
    labels = validate_l_values(l_values)
    return np.array([projector(np.eye(len(labels), dtype=complex)[:, i]) for i in range(len(labels))])


def oam_fourier_projectors(l_values=(-2, -1, 0, 1, 2)):
    """Return a mutually unbiased Fourier basis of OAM projectors."""
    labels = validate_l_values(l_values)
    d = len(labels)
    vectors = np.exp(2j * np.pi * np.outer(np.arange(d), np.arange(d)) / d) / np.sqrt(d)
    return np.array([projector(vectors[k]) for k in range(d)])


def oam_mub_projectors(l_values=(-2, -1, 0, 1, 2), basis_index=0):
    """Return a quadratic-phase Fourier basis for prime-dimensional OAM spaces.

    For the default five-mode truncation, ``basis_index=0..4`` gives the five
    non-computational members of the standard mutually unbiased basis family.
    The formula also provides useful phase-shifted Fourier bases for other
    finite dimensions, although mutual unbiasedness is guaranteed only when
    the dimension is an odd prime.
    """
    labels = validate_l_values(l_values)
    d = len(labels)
    basis_index = int(basis_index) % d
    k = np.arange(d)
    vectors = np.exp(2j * np.pi * (basis_index * k[:, None] ** 2 + k[:, None] * np.arange(d)[None, :]) / d) / np.sqrt(d)
    return np.array([projector(vectors[:, outcome]) for outcome in range(d)])


def tensor_product_projectors(*local_projectors):
    """Combine local projector arrays into all product POVM outcomes."""
    if not local_projectors:
        raise ValueError("at least one local projector set is required")
    arrays = [np.asarray(item, dtype=complex) for item in local_projectors]
    for array in arrays:
        if array.ndim != 3 or array.shape[1] != array.shape[2]:
            raise ValueError("each local projector set must have shape (n_outcomes,d,d)")
    effects = []
    for indices in product(*[range(array.shape[0]) for array in arrays]):
        effect = arrays[0][indices[0]]
        for array, index in zip(arrays[1:], indices[1:]):
            effect = np.kron(effect, array[index])
        effects.append(effect)
    return np.array(effects)


def product_povm(settings):
    """Build (n_settings,n_outcomes,D,D) from local basis settings."""
    effects = [tensor_product_projectors(*setting) for setting in settings]
    if not effects:
        raise ValueError("settings must contain at least one measurement setting")
    if any(item.shape[0] != effects[0].shape[0] for item in effects):
        raise ValueError("all settings must have the same number of outcomes")
    return np.array(effects)


def povm_probabilities(rho, measurements):
    """Evaluate probabilities/effect expectations for a POVM array."""
    effects = np.asarray(measurements, dtype=complex)
    if effects.ndim == 3:
        effects = effects[:, np.newaxis]
    return np.real(np.einsum("skij,ji->sk", effects, np.asarray(rho, dtype=complex)))


def simulate_counts(rho, measurements, shots=1000, rng=None):
    """Generate independent Poisson counts for a POVM measurement array."""
    probabilities = np.maximum(povm_probabilities(rho, measurements), 0.0)
    return np.random.default_rng(rng).poisson(float(shots) * probabilities).astype(int)
