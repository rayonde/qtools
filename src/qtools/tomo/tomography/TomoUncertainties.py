"""Monte Carlo uncertainty estimates for reconstructed quantum states.

The implementation resamples the measured coincidence counts, propagates the
perturbation through the same linear measurement model used by tomography, and
projects each sample back onto the physical density-matrix set.  It reports a
sample standard deviation together with a bounded, asymmetric 68.27% interval.
"""

from __future__ import annotations

from math import comb
from typing import Any

import numpy as np

import qtools.tomo.tomography.TomoFunctions as tf


SINGLE_STATES: dict[str, np.ndarray] = {
    "H": np.array([1.0, 0.0], dtype=complex),
    "V": np.array([0.0, 1.0], dtype=complex),
    "D": np.array([1.0, 1.0], dtype=complex) / np.sqrt(2.0),
    "A": np.array([1.0, -1.0], dtype=complex) / np.sqrt(2.0),
    "R": np.array([1.0, 1.0j], dtype=complex) / np.sqrt(2.0),
    "L": np.array([1.0, -1.0j], dtype=complex) / np.sqrt(2.0),
}


def _get_projector(basis: list[str]) -> np.ndarray:
    """Return the product projector for canonical basis labels."""
    if not basis:
        return np.eye(2, dtype=complex)
    unknown = next((name for name in basis if name not in SINGLE_STATES), None)
    if unknown is not None:
        raise ValueError(f"Unknown measurement basis '{unknown}'")
    state = SINGLE_STATES[basis[0]]
    for name in basis[1:]:
        state = np.kron(state, SINGLE_STATES[name])
    return np.outer(state, state.conj())


def _normalise_state_vector(state: Any) -> np.ndarray:
    """Return a normalized two-component measurement ket."""
    vector = np.asarray(state, dtype=complex).reshape(-1)
    if vector.size != 2:
        raise ValueError("Each measurement state must be a two-component vector")
    norm = np.linalg.norm(vector)
    if norm <= 0:
        raise ValueError("Measurement state vector cannot be zero")
    return vector / norm


def _get_projector_from_states(
    basis: list[str], measurement_states: dict[str, Any] | None, n_qubits: int
) -> np.ndarray:
    """Build the product projector used by the input measurement model."""
    if len(basis) != n_qubits:
        raise ValueError("Measurement basis length does not match n_qubits")
    if measurement_states is None:
        return _get_projector(basis)

    vectors = []
    for name in basis:
        if name not in measurement_states:
            raise ValueError(f"Unknown measurement basis '{name}'")
        vectors.append(_normalise_state_vector(measurement_states[name]))
    state = vectors[0]
    for vector in vectors[1:]:
        state = np.kron(state, vector)
    return np.outer(state, state.conj())


def _project_to_psd(rho_mat: np.ndarray) -> np.ndarray:
    """Project a Hermitian matrix onto valid density matrices."""
    rho_herm = (rho_mat + rho_mat.conj().T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(rho_herm)
    eigvals = np.maximum(0.0, eigvals)
    total = float(np.sum(eigvals))
    if total > 1e-12:
        eigvals /= total
    else:
        eigvals = np.ones_like(eigvals) / len(eigvals)
    return eigvecs @ np.diag(eigvals) @ eigvecs.conj().T


def _calc_asymmetric_stats(
    arr: list[float],
    v0: float | None = None,
    min_bound: float = 0.0,
    max_bound: float = 1.0,
) -> dict[str, Any]:
    """Compute bounded standard deviation and asymmetric interval."""
    empty = {"std": None, "ci": None, "err_minus": None, "err_plus": None, "q16": None, "q84": None}
    if len(arr) < 2:
        return empty

    values = np.asarray(arr, dtype=float)
    values = np.clip(values, min_bound, max_bound)
    std_val = float(np.std(values, ddof=1))
    q16 = float(np.percentile(values, 15.865))
    q84 = float(np.percentile(values, 84.135))
    if v0 is not None and not np.isnan(v0):
        center = float(np.clip(v0, min_bound, max_bound))
    else:
        center = float(np.median(values))

    # At a physical boundary the empirical quantile can be on only one side
    # of the point estimate.  Include the point estimate in the displayed CI.
    ci_low = min(center, q16)
    ci_high = max(center, q84)
    return {
        "std": round(std_val, 4),
        "ci": [round(ci_low, 4), round(ci_high, 4)],
        "err_minus": round(max(0.0, center - ci_low), 4),
        "err_plus": round(max(0.0, ci_high - center), 4),
        "q16": round(q16, 4),
        "q84": round(q84, 4),
    }


def _empty_result() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("fidelity", "purity", "concurrence", "entropy"):
        result[f"{name}_std"] = None
        result[f"{name}_ci"] = None
        result[f"{name}_err_minus"] = None
        result[f"{name}_err_plus"] = None
    return result


def compute_state_uncertainties(
    data_rows: list[dict[str, Any]],
    rho: np.ndarray,
    target_state: Any = None,
    point_estimates: dict[str, float | None] | None = None,
    n_samples: int = 80,
    intensity: float | None = None,
    n_qubits: int = 2,
    measurement_states: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute uncertainty estimates for tomography state properties."""
    dim = 2**n_qubits
    empty_res = _empty_result()
    rho = np.asarray(rho, dtype=complex)
    if rho.shape != (dim, dim) or not data_rows or n_samples < 2:
        return empty_res

    target_rho: np.ndarray | None = None
    if target_state is not None:
        try:
            target_mat = target_state.full() if hasattr(target_state, "full") else np.asarray(target_state, dtype=complex)
            if target_mat.ndim == 1 or (target_mat.ndim == 2 and 1 in target_mat.shape):
                vector = target_mat.reshape(-1)
                norm = np.linalg.norm(vector)
                if norm > 0:
                    target_rho = np.outer(vector / norm, (vector / norm).conj())
            elif target_mat.shape == (dim, dim):
                target_rho = target_mat
        except Exception:
            target_rho = None

    meas_ops: list[np.ndarray] = []
    counts_list: list[float] = []
    user_stds_list: list[float] = []
    coincidence_idx = max(0, sum(comb(n_qubits, i) for i in range(n_qubits)) - 1)

    for row in data_rows:
        basis = row.get("basis", ["H"] * n_qubits)
        try:
            meas_ops.append(_get_projector_from_states(basis, measurement_states, n_qubits))
        except (TypeError, ValueError):
            return empty_res

        counts = row.get("counts", [])
        if counts and len(counts) > coincidence_idx:
            count = counts[coincidence_idx]
        elif counts:
            count = counts[-1]
        else:
            count = 0.0
        try:
            counts_list.append(max(0.0, float(count)))
        except (TypeError, ValueError):
            return empty_res

        stds = row.get("stds", [])
        try:
            std = float(stds[0]) if stds and stds[0] is not None else 0.0
        except (TypeError, ValueError):
            std = 0.0
        user_stds_list.append(max(0.0, std))

    # Singles-only/empty data do not provide the coincidence distribution this
    # model resamples; do not manufacture a non-zero uncertainty interval.
    if not meas_ops or sum(counts_list) <= 0.0:
        return empty_res

    A = np.asarray([operator.T.flatten() for operator in meas_ops])
    try:
        A_pinv = np.linalg.pinv(A)
    except Exception:
        return empty_res

    if intensity is not None and intensity > 0:
        scale = float(intensity)
    else:
        total_counts = sum(counts_list)
        n_bases = max(1.0, len(data_rows) / float(dim))
        scale = max(1.0, total_counts / n_bases)

    rng = np.random.default_rng()
    deltas = np.zeros((n_samples, len(data_rows)), dtype=float)
    for i, (count, std) in enumerate(zip(counts_list, user_stds_list)):
        if std > 0:
            deltas[:, i] = rng.normal(0.0, std, size=n_samples)
        else:
            deltas[:, i] = rng.poisson(count, size=n_samples) - count

    fidelities: list[float] = []
    purities: list[float] = []
    concurrences: list[float] = []
    entropies: list[float] = []
    for delta in deltas:
        delta_rho = (A_pinv @ (delta / scale)).reshape((dim, dim))
        rho_k = _project_to_psd(rho + delta_rho)
        if target_rho is not None:
            try:
                fidelities.append(float(np.clip(np.real(tf.fidelity(rho_k, target_rho)), 0.0, 1.0)))
            except Exception:
                pass
        try:
            purities.append(float(np.clip(np.real(tf.purity(rho_k)), 1.0 / dim, 1.0)))
        except Exception:
            pass
        if n_qubits == 2:
            try:
                concurrences.append(float(np.clip(np.real(tf.concurrence(rho_k)), 0.0, 1.0)))
            except Exception:
                pass
        try:
            entropies.append(float(np.clip(np.real(tf.entropy(rho_k)), 0.0, np.log2(dim))))
        except Exception:
            pass

    points = point_estimates or {}
    f_stats = _calc_asymmetric_stats(fidelities, points.get("fidelity"), 0.0, 1.0)
    p_stats = _calc_asymmetric_stats(purities, points.get("purity"), 1.0 / dim, 1.0)
    c_stats = _calc_asymmetric_stats(concurrences, points.get("concurrence"), 0.0, 1.0) if n_qubits == 2 else _empty_result()
    e_stats = _calc_asymmetric_stats(entropies, points.get("entropy"), 0.0, float(np.log2(dim)))

    result = _empty_result()
    for name, stats in (("fidelity", f_stats), ("purity", p_stats), ("concurrence", c_stats), ("entropy", e_stats)):
        result[f"{name}_std"] = stats.get("std")
        result[f"{name}_ci"] = stats.get("ci")
        result[f"{name}_err_minus"] = stats.get("err_minus")
        result[f"{name}_err_plus"] = stats.get("err_plus")
    return result
