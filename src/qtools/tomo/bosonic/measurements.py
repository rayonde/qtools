"""Displaced photon counting measurements and phase-space distribution wrappers.

Implements the "displace-and-measure" operator construction and measurement
statistics generation for bosonic/cavity state tomography.
"""

from __future__ import annotations

from typing import Sequence
import numpy as np
import qutip as qt


def construct_displaced_fock_operators(
    hilbert_size: int,
    betas: Sequence[complex | float],
    max_photons: int | None = None,
) -> list[list[qt.Qobj]]:
    """Construct displaced Fock projectors M_{beta, n} for tomography.

    In a displace-and-measure experiment, the state is displaced by beta
    and then photon-number occupancy |n⟩⟨n| is measured:
        P(n | beta) = Tr[ |n⟩⟨n| D(beta) rho D^dagger(beta) ]
                    = Tr[ D^dagger(beta) |n⟩⟨n| D(beta) rho ]
                    = Tr[ M_{beta, n} rho ]

    Matching the QuTiP formulation:
        D = displace(hilbert_size, -beta)
        M_{beta, n} = D.dag() * fock_dm(hilbert_size, n) * D

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    betas : Sequence[complex | float]
        List of phase space displacement values applied before photon counting.
    max_photons : int | None, optional
        Maximum photon number measured (0 <= n < max_photons).
        If None, defaults to hilbert_size.

    Returns
    -------
    list[list[qt.Qobj]]
        Nested list where R_ops[i][n] is the operator for displacement betas[i]
        and photon number n.
    """
    if max_photons is None:
        max_photons = hilbert_size
    elif max_photons <= 0 or max_photons > hilbert_size:
        raise ValueError(f"max_photons must satisfy 1 <= max_photons <= hilbert_size={hilbert_size}")

    fock_dms = [qt.fock_dm(hilbert_size, n) for n in range(max_photons)]
    r_ops: list[list[qt.Qobj]] = []

    for beta in betas:
        # D(-beta)^dag = D(beta)
        d_minus = qt.displace(hilbert_size, -complex(beta))
        d_minus_dag = d_minus.dag()
        displaced_ops = [d_minus_dag * fock_op * d_minus for fock_op in fock_dms]
        r_ops.append(displaced_ops)

    return r_ops


def displaced_photon_probabilities(
    state: qt.Qobj,
    betas: Sequence[complex | float],
    max_photons: int | None = None,
    r_ops: list[list[qt.Qobj]] | None = None,
) -> np.ndarray:
    """Compute the theoretical probabilities P(n | beta) for a given state.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    betas : Sequence[complex | float]
        Displacement settings.
    max_photons : int | None, optional
        Number of photon levels to evaluate. Defaults to state's Hilbert space dimension.
    r_ops : list[list[qt.Qobj]] | None, optional
        Precomputed operators from construct_displaced_fock_operators.

    Returns
    -------
    np.ndarray
        2D array of shape (len(betas), max_photons) with non-negative probabilities.
    """
    hilbert_size = state.dims[0][0]
    if r_ops is None:
        r_ops = construct_displaced_fock_operators(hilbert_size, betas, max_photons=max_photons)

    n_betas = len(betas)
    n_photons = len(r_ops[0])
    probs = np.zeros((n_betas, n_photons), dtype=float)

    for i in range(n_betas):
        for n in range(n_photons):
            val = qt.expect(r_ops[i][n], state)
            probs[i, n] = max(float(np.real(val)), 0.0)

    return probs


def simulate_photon_counts(
    state: qt.Qobj,
    betas: Sequence[complex | float],
    shots_per_setting: int = 10000,
    max_photons: int | None = None,
    noise_std: float | None = None,
    seed: int | None = None,
    r_ops: list[list[qt.Qobj]] | None = None,
) -> np.ndarray:
    """Simulate experimental photon count data with statistical fluctuations.

    Parameters
    ----------
    state : qt.Qobj
        True quantum state.
    betas : Sequence[complex | float]
        Displacement settings.
    shots_per_setting : int, optional
        Total measurement repetitions (shots) per displacement setting. Default: 10000.
    max_photons : int | None, optional
        Cutoff photon number. Defaults to Hilbert space dimension.
    noise_std : float | None, optional
        Optional additive Gaussian noise standard deviation on probabilities.
    seed : int | None, optional
        Random seed for reproducibility.
    r_ops : list[list[qt.Qobj]] | None, optional
        Precomputed measurement operators.

    Returns
    -------
    np.ndarray
        2D array of shape (len(betas), max_photons) containing simulated counts.
    """
    rng = np.random.default_rng(seed)
    probs = displaced_photon_probabilities(state, betas, max_photons=max_photons, r_ops=r_ops)

    if noise_std is not None and noise_std > 0:
        probs += rng.normal(0.0, noise_std, size=probs.shape)
        probs = np.maximum(probs, 0.0)

    # Multinomial sampling for each beta setting
    n_betas, n_photons = probs.shape
    counts = np.zeros((n_betas, n_photons), dtype=float)

    for i in range(n_betas):
        p_row = probs[i].copy()
        p_sum = np.sum(p_row)
        if p_sum > 0:
            p_row /= p_sum
            # If probabilities sum to < 1 due to truncated photons, append remainder
            if p_sum < 1.0 - 1e-6:
                p_extended = np.append(p_row, 1.0 - p_sum)
                sample = rng.multinomial(shots_per_setting, p_extended)
                counts[i] = sample[:n_photons]
            else:
                counts[i] = rng.multinomial(shots_per_setting, p_row)
        else:
            counts[i] = shots_per_setting / n_photons

    return counts


def q_function(state: qt.Qobj, xvec: np.ndarray, yvec: np.ndarray) -> np.ndarray:
    """Evaluate the Husimi Q-function on a phase space grid using QuTiP.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    xvec : np.ndarray
        Real quadrature values (Re(beta)).
    yvec : np.ndarray
        Imaginary quadrature values (Im(beta)).

    Returns
    -------
    np.ndarray
        2D array of shape (len(yvec), len(xvec)) containing Q(x, y).
    """
    return qt.qfunc(state, xvec, yvec)


def wigner_function(state: qt.Qobj, xvec: np.ndarray, yvec: np.ndarray) -> np.ndarray:
    """Evaluate the Wigner quasiprobability distribution using QuTiP.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    xvec : np.ndarray
        Position / Real quadrature values.
    yvec : np.ndarray
        Momentum / Imaginary quadrature values.

    Returns
    -------
    np.ndarray
        2D array of shape (len(yvec), len(xvec)) containing W(x, y).
    """
    return qt.wigner(state, xvec, yvec)
