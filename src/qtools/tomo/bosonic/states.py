"""Bosonic quantum state generation helpers wrapping QuTiP primitives.

Provides clean constructors for Fock states, coherent states, cat states,
squeezed states, and thermal states in truncated Fock spaces.
"""

from __future__ import annotations

from typing import Sequence
import numpy as np
import qutip as qt


def fock_state(hilbert_size: int, n: int) -> qt.Qobj:
    """Return a Fock number state |n⟩ as a QuTiP ket.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space (cutoff N).
    n : int
        Photon number (0 <= n < hilbert_size).

    Returns
    -------
    qt.Qobj
        Normalized ket state |n⟩.
    """
    if n < 0 or n >= hilbert_size:
        raise ValueError(f"Photon number n={n} must satisfy 0 <= n < hilbert_size={hilbert_size}")
    return qt.fock(hilbert_size, n)


def fock_density_matrix(hilbert_size: int, n: int) -> qt.Qobj:
    """Return a Fock state density matrix |n⟩⟨n|.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    n : int
        Photon number (0 <= n < hilbert_size).

    Returns
    -------
    qt.Qobj
        Density matrix operator |n⟩⟨n|.
    """
    if n < 0 or n >= hilbert_size:
        raise ValueError(f"Photon number n={n} must satisfy 0 <= n < hilbert_size={hilbert_size}")
    return qt.fock_dm(hilbert_size, n)


def coherent_state(hilbert_size: int, alpha: complex | float) -> qt.Qobj:
    """Return a coherent state |alpha⟩ as a QuTiP ket.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    alpha : complex | float
        Coherent state amplitude in phase space.

    Returns
    -------
    qt.Qobj
        Normalized ket state |alpha⟩.
    """
    return qt.coherent(hilbert_size, alpha)


def coherent_density_matrix(hilbert_size: int, alpha: complex | float) -> qt.Qobj:
    """Return a coherent state density matrix |alpha⟩⟨alpha|.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    alpha : complex | float
        Coherent state amplitude.

    Returns
    -------
    qt.Qobj
        Density matrix operator |alpha⟩⟨alpha|.
    """
    return qt.coherent_dm(hilbert_size, alpha)


def cat_state(
    hilbert_size: int,
    alphas: complex | float | Sequence[complex | float],
    weights: Sequence[complex | float] | None = None,
    parity: str = "even",
) -> qt.Qobj:
    """Construct a Schrödinger cat state or multi-headed superposition of coherent states.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    alphas : complex | float | Sequence[complex | float]
        Either a single amplitude alpha for a standard 2-component cat,
        or a sequence of amplitudes [alpha_1, alpha_2, ...] for multi-headed cat states.
    weights : Sequence[complex | float] | None, optional
        Superposition weights for multi-headed cat state. If None, equal superposition is used.
    parity : str, optional
        For single alpha:
        - "even": (|alpha⟩ + |-alpha⟩) / N
        - "odd": (|alpha⟩ - |-alpha⟩) / N
        - "yurke-stoler": (|alpha⟩ + 1j * |-alpha⟩) / N
        Ignored if a sequence of alphas is supplied.

    Returns
    -------
    qt.Qobj
        Normalized ket state superposition.
    """
    # Multi-component cat state
    if isinstance(alphas, (list, tuple, np.ndarray)):
        alpha_list = list(alphas)
        if len(alpha_list) == 0:
            raise ValueError("alphas sequence cannot be empty")

        if weights is None:
            weight_list = [1.0] * len(alpha_list)
        else:
            weight_list = list(weights)
            if len(weight_list) != len(alpha_list):
                raise ValueError("Length of weights must match length of alphas")

        state = sum(w * qt.coherent(hilbert_size, a) for w, a in zip(weight_list, alpha_list))
        return state.unit()

    # Standard 2-component cat state
    alpha = complex(alphas)
    ket_plus = qt.coherent(hilbert_size, alpha)
    ket_minus = qt.coherent(hilbert_size, -alpha)

    p_norm = parity.lower()
    if p_norm in ("even", "+"):
        psi = ket_plus + ket_minus
    elif p_norm in ("odd", "-"):
        psi = ket_plus - ket_minus
    elif p_norm in ("yurke-stoler", "ys"):
        psi = ket_plus + 1j * ket_minus
    else:
        raise ValueError(f"Unknown cat parity '{parity}'. Supported: 'even', 'odd', 'yurke-stoler'.")

    return psi.unit()


def squeezed_vacuum_state(hilbert_size: int, r: float, theta: float = 0.0) -> qt.Qobj:
    """Return a squeezed vacuum state S(r e^{i theta}) |0⟩.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    r : float
        Squeezing parameter (r >= 0).
    theta : float, optional
        Squeezing angle (phase). Default is 0.0.

    Returns
    -------
    qt.Qobj
        Normalized squeezed vacuum ket.
    """
    z = r * np.exp(1j * theta)
    squeeze_op = qt.squeeze(hilbert_size, z)
    vac = qt.basis(hilbert_size, 0)
    return (squeeze_op * vac).unit()


def thermal_state(hilbert_size: int, n_th: float) -> qt.Qobj:
    """Return a thermal state density matrix with mean photon number n_th.

    Parameters
    ----------
    hilbert_size : int
        Dimension of the truncated Hilbert space.
    n_th : float
        Average thermal photon number (n_th >= 0).

    Returns
    -------
    qt.Qobj
        Normalized thermal density matrix operator.
    """
    if n_th < 0:
        raise ValueError("n_th must be non-negative")
    return qt.thermal_dm(hilbert_size, n_th)


def displaced_state(state: qt.Qobj, alpha: complex | float) -> qt.Qobj:
    """Apply displacement operator D(alpha) to a state.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    alpha : complex | float
        Displacement amplitude.

    Returns
    -------
    qt.Qobj
        Displaced quantum state.
    """
    hilbert_size = state.dims[0][0]
    D = qt.displace(hilbert_size, alpha)
    if state.isket:
        return (D * state).unit()
    elif state.isoper:
        return D * state * D.dag()
    else:
        raise ValueError("state must be a ket or density matrix operator")


def superposition_state(
    states: Sequence[qt.Qobj], weights: Sequence[complex | float] | None = None
) -> qt.Qobj:
    """Construct an arbitrary superposition of ket states.

    Parameters
    ----------
    states : Sequence[qt.Qobj]
        Sequence of ket states (must share the same Hilbert space dimension).
    weights : Sequence[complex | float] | None, optional
        Superposition coefficients. Default is equal weights.

    Returns
    -------
    qt.Qobj
        Normalized ket state.
    """
    if len(states) == 0:
        raise ValueError("states sequence cannot be empty")
    if weights is None:
        w_list = [1.0] * len(states)
    else:
        w_list = list(weights)
        if len(w_list) != len(states):
            raise ValueError("Length of weights must match length of states")

    psi = sum(w * s for w, s in zip(w_list, states))
    return psi.unit()
