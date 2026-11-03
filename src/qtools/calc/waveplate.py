"""NumPy Jones calculus for polarization optics.

The public API deliberately stays close to the underlying mathematics:
polarization states are complex arrays with Jones basis ``(H, V)`` and optical
elements are ``2 x 2`` Jones matrices.  All matrix constructors accept scalar
or array-valued angles and broadcast over batch dimensions.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


_AXIS_VECTORS = {
    "H": np.array([1.0, 0.0], dtype=complex),
    "V": np.array([0.0, 1.0], dtype=complex),
    "D": np.array([1.0, 1.0], dtype=complex) / np.sqrt(2.0),
    "A": np.array([1.0, -1.0], dtype=complex) / np.sqrt(2.0),
}


def _matrix_batch(matrix: np.ndarray, name: str = "matrix") -> np.ndarray:
    matrix = np.asarray(matrix, dtype=complex)
    if matrix.ndim < 2 or matrix.shape[-2:] != (2, 2):
        raise ValueError(f"{name} must have shape (..., 2, 2)")
    return matrix


def _state_batch(state: np.ndarray, name: str = "state") -> np.ndarray:
    state = np.asarray(state, dtype=complex)
    if state.ndim == 0 or state.shape[-1:] != (2,):
        raise ValueError(f"{name} must have shape (..., 2)")
    return state


def _normalize(state: np.ndarray, *, name: str = "state") -> np.ndarray:
    state = _state_batch(state, name)
    norm = np.linalg.norm(state, axis=-1, keepdims=True)
    if np.any(norm == 0):
        raise ValueError(f"{name} cannot contain a zero Jones vector")
    return state / norm


def retarder(theta_deg: float | np.ndarray, retardance_deg: float | np.ndarray) -> np.ndarray:
    """Return a linear retarder Jones matrix.

    ``theta_deg`` is the fast-axis angle measured from H. ``retardance_deg``
    is the slow-axis phase relative to the fast axis.  Scalar inputs return a
    ``(2, 2)`` matrix; array inputs return ``(..., 2, 2)`` matrices.
    """
    theta, delta = np.broadcast_arrays(
        np.asarray(theta_deg, dtype=float), np.asarray(retardance_deg, dtype=float)
    )
    theta = np.deg2rad(theta)
    phase = np.exp(1j * np.deg2rad(delta))
    c, s = np.cos(theta), np.sin(theta)

    matrix = np.empty(theta.shape + (2, 2), dtype=complex)
    matrix[..., 0, 0] = c**2 + phase * s**2
    matrix[..., 0, 1] = (1.0 - phase) * s * c
    matrix[..., 1, 0] = matrix[..., 0, 1]
    matrix[..., 1, 1] = s**2 + phase * c**2
    return matrix


def qwp(
    theta_deg: float | np.ndarray,
    retardance_deg: float | np.ndarray = 90.0,
) -> np.ndarray:
    """Return a QWP Jones matrix, optionally with measured retardance."""
    return retarder(theta_deg, retardance_deg)


def hwp(
    theta_deg: float | np.ndarray,
    retardance_deg: float | np.ndarray = 180.0,
) -> np.ndarray:
    """Return an HWP Jones matrix, optionally with measured retardance."""
    return retarder(theta_deg, retardance_deg)


def pbs(axis: str = "H") -> np.ndarray:
    """Return an ideal rank-one PBS/polarizer projection matrix.

    Supported axes are ``H``, ``V``, ``D`` and ``A``.  The returned matrix is
    suitable for direct multiplication or for :func:`probability`.
    """
    try:
        vector = _AXIS_VECTORS[str(axis).upper()]
    except KeyError as exc:
        raise ValueError("axis must be one of H, V, D or A") from exc
    return np.outer(vector, vector.conj())


def project(state: np.ndarray, projector: np.ndarray) -> np.ndarray:
    """Apply a projector or Jones matrix to one state or a batch of states."""
    state = _state_batch(state)
    matrix = _matrix_batch(projector, "projector")
    batch_shape = np.broadcast_shapes(state.shape[:-1], matrix.shape[:-2])
    state = np.broadcast_to(state, batch_shape + (2,))
    matrix = np.broadcast_to(matrix, batch_shape + (2, 2))
    return np.matmul(matrix, state[..., None])[..., 0]


def apply(
    state: np.ndarray,
    elements: Iterable[np.ndarray],
    *,
    return_history: bool = False,
) -> np.ndarray:
    """Propagate Jones states through matrices in optical order.

    ``elements=[qwp(10), hwp(22.5)]`` computes
    ``hwp(22.5) @ qwp(10) @ state``.  States and matrix batches are broadcast
    together.  With ``return_history=True`` the result has the input state as
    its first entry, followed by the output after each element.
    """
    state = _state_batch(state)
    matrices = tuple(
        _matrix_batch(element, f"elements[{index}]")
        for index, element in enumerate(elements)
    )
    if not matrices:
        return state[None, ...].copy() if return_history else state.copy()

    batch_shape = np.broadcast_shapes(
        state.shape[:-1], *(matrix.shape[:-2] for matrix in matrices)
    )
    current = np.broadcast_to(state, batch_shape + (2,)).copy()
    history = [current.copy()] if return_history else None
    for matrix in matrices:
        matrix = np.broadcast_to(matrix, batch_shape + (2, 2))
        current = np.matmul(matrix, current[..., None])[..., 0]
        if return_history:
            history.append(current.copy())
    return np.stack(history, axis=0) if return_history else current


propagate = apply


def probability(state: np.ndarray, projector: np.ndarray) -> np.ndarray | float:
    """Return normalized intensity transmitted by a projector.

    The input may be unnormalized.  The result is ``<E|P|E>/<E|E>`` and is a
    scalar for one state or an array for a batch of states.
    """
    state = _state_batch(state)
    projected = project(state, projector)
    numerator = np.sum(np.conj(state) * projected, axis=-1).real
    denominator = np.sum(np.abs(state) ** 2, axis=-1)
    if np.any(denominator == 0):
        raise ValueError("state cannot contain a zero Jones vector")
    result = np.clip(numerator / denominator, 0.0, 1.0)
    return float(result) if result.ndim == 0 else result


def stokes(state: np.ndarray, *, normalize: bool = True) -> np.ndarray:
    """Return Stokes vectors ``(S0, S1, S2, S3)`` for Jones states.

    The convention is ``S1=|H|²-|V|²``, ``S2=2 Re(H V*)`` and
    ``S3=2 Im(H V*)``.  With ``normalize=True`` (the default), ``S0`` is one.
    """
    state = _state_batch(state)
    h, v = state[..., 0], state[..., 1]
    s0 = np.abs(h) ** 2 + np.abs(v) ** 2
    s1 = np.abs(h) ** 2 - np.abs(v) ** 2
    s2 = 2.0 * np.real(h * np.conj(v))
    s3 = 2.0 * np.imag(h * np.conj(v))
    values = np.stack((s0, s1, s2, s3), axis=-1)
    if not normalize:
        return values
    if np.any(s0 == 0):
        raise ValueError("state cannot contain a zero Jones vector")
    return values / s0[..., None]


def bloch(state: np.ndarray) -> np.ndarray:
    """Return normalized polarization Bloch/Poincare coordinates ``(S1,S2,S3)``."""
    return stokes(state, normalize=True)[..., 1:]


def _axis_state(axis: str) -> np.ndarray:
    try:
        return _AXIS_VECTORS[str(axis).upper()].copy()
    except KeyError as exc:
        raise ValueError("axis must be one of H, V, D or A") from exc


def _analyzer_state(
    angles: Sequence[float],
    retardances: tuple[float, ...],
    axis: str,
) -> np.ndarray:
    """State selected at the input by a waveplate/PBS analyzer."""
    output = _axis_state(axis)
    matrices = [retarder(angle, retardance) for angle, retardance in zip(angles, retardances)]
    # If U is the forward optical matrix, the input analyzer state is U†|axis>.
    for matrix in reversed(matrices):
        output = matrix.conj().T @ output
    return _normalize(output)


def solve_analyzer_angles(
    target: np.ndarray,
    architecture: str | Sequence[str] = ("qwp", "hwp"),
    *,
    axis: str = "H",
    retardances_deg: Sequence[float] | None = None,
) -> dict[str, object]:
    """Find waveplate angles for a PBS projection onto ``target``.

    ``architecture`` is listed in propagation order, e.g. ``("qwp", "hwp")``
    means QWP -> HWP -> PBS.  ``retardances_deg`` optionally supplies one
    measured retardance per plate.  The returned dictionary contains angles
    in propagation order, retardances, and achieved projection fidelity.  A
    single ideal HWP can only analyze linear target states; ideal two-plate
    QWP/HWP and HWP/QWP architectures can analyze arbitrary pure states.
    """
    target = _normalize(target, name="target")
    if target.ndim != 1:
        raise ValueError("target must be one Jones vector with shape (2,)")
    if isinstance(architecture, str):
        architecture = (architecture,)
    architecture = tuple(str(kind).lower() for kind in architecture)
    if not architecture or any(kind not in {"hwp", "qwp"} for kind in architecture):
        raise ValueError("architecture must contain only 'hwp' and 'qwp'")
    if retardances_deg is None:
        retardances = tuple(180.0 if kind == "hwp" else 90.0 for kind in architecture)
    else:
        retardances = tuple(float(value) for value in retardances_deg)
        if len(retardances) != len(architecture):
            raise ValueError("retardances_deg must have one value per waveplate")

    # The one-HWP case has a direct solution and a useful reachability check.
    if architecture == ("hwp",) and retardances == (180.0,) and str(axis).upper() == "H":
        reference = target[0] if abs(target[0]) > 1e-12 else target[1]
        phase_fixed = target * np.exp(-1j * np.angle(reference))
        if abs(phase_fixed[1].imag) > 1e-9:
            raise ValueError("a single HWP followed by PBS-H can only analyze linear polarization")
        pol_angle = np.degrees(np.arctan2(phase_fixed[1].real, phase_fixed[0].real))
        angle = float((pol_angle / 2.0) % 180.0)
        # Verify using the actual analyzer state, avoiding phase/sign ambiguity.
        fidelity = float(
            np.clip(
                abs(np.vdot(target, _analyzer_state((angle,), retardances, axis))) ** 2,
                0.0,
                1.0,
            )
        )
        return {
            "architecture": architecture,
            "angles_deg": (angle,),
            "retardances_deg": retardances,
            "fidelity": fidelity,
        }

    try:
        from scipy.optimize import minimize
    except ImportError as exc:  # pragma: no cover - SciPy is a project dependency
        raise ImportError("solve_analyzer_angles requires scipy") from exc

    n_angles = len(architecture)
    starts = np.array(np.meshgrid(*([np.arange(0.0, 180.0, 30.0)] * n_angles))).T.reshape(-1, n_angles)

    def objective(angles: np.ndarray) -> float:
        analyzer = _analyzer_state(angles, retardances, axis)
        return float(1.0 - abs(np.vdot(target, analyzer)) ** 2)

    best = None
    for start in starts:
        result = minimize(
            objective,
            start,
            method="Nelder-Mead",
            options={"maxiter": 1000, "xatol": 1e-10, "fatol": 1e-12},
        )
        if best is None or result.fun < best.fun:
            best = result
    angles = tuple(float(angle % 180.0) for angle in best.x)
    fidelity = float(np.clip(1.0 - objective(np.asarray(angles)), 0.0, 1.0))
    if fidelity < 1.0 - 1e-7:
        raise ValueError(
            f"architecture {architecture!r} could not realize target; fidelity={fidelity:.9f}"
        )
    return {
        "architecture": architecture,
        "angles_deg": angles,
        "retardances_deg": retardances,
        "fidelity": fidelity,
    }


__all__ = [
    "apply",
    "bloch",
    "hwp",
    "pbs",
    "probability",
    "project",
    "propagate",
    "qwp",
    "retarder",
    "solve_analyzer_angles",
    "stokes",
]
