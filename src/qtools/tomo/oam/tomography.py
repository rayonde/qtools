"""Standalone finite-dimensional tomography for OAM experiments.

This module intentionally does not import or modify ``qtools.tomo.tomography``.
It provides the explicit-POVM path needed by truncated OAM experiments while
leaving the historical qubit tomography implementation untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import leastsq


def _validate_dims(dims: int | Iterable[int]) -> tuple[int, ...]:
    if isinstance(dims, (int, np.integer)) and not isinstance(dims, bool):
        values = (int(dims),)
    else:
        try:
            values = tuple(int(value) for value in dims)
        except (TypeError, ValueError):
            raise ValueError("dims must be a positive integer or a sequence of positive integers")
    if not values or any(value < 1 for value in values):
        raise ValueError("dims must contain at least one positive integer")
    return values


def _as_density_matrix(rho: np.ndarray, dimension: int) -> np.ndarray:
    array = np.asarray(rho, dtype=complex)
    if array.shape != (dimension, dimension):
        raise ValueError(f"rho must have shape ({dimension}, {dimension})")
    array = (array + array.conj().T) / 2.0
    values, vectors = np.linalg.eigh(array)
    values = np.maximum(values, 0.0)
    array = (vectors * values) @ vectors.conj().T
    trace = float(np.real(np.trace(array)))
    if trace <= 1e-14:
        raise ValueError("rho must have positive trace")
    return array / trace


def _t_matrix(parameters: np.ndarray, dimension: int) -> np.ndarray:
    values = np.asarray(parameters, dtype=float).reshape(-1)
    if values.size != dimension * dimension:
        raise ValueError("Cholesky parameter vector has the wrong length")
    matrix = np.zeros((dimension, dimension), dtype=complex)
    cursor = 0
    for row in range(dimension):
        matrix[row, row] = values[cursor]
        cursor += 1
        for column in range(row):
            matrix[row, column] = values[cursor] + 1j * values[cursor + 1]
            cursor += 2
    return matrix


def _parameters_from_t(matrix: np.ndarray) -> np.ndarray:
    dimension = matrix.shape[0]
    values: list[float] = []
    for row in range(dimension):
        values.append(float(np.real(matrix[row, row])))
        for column in range(row):
            values.extend([float(np.real(matrix[row, column])), float(np.imag(matrix[row, column]))])
    return np.asarray(values, dtype=float)


def _density_from_parameters(parameters: np.ndarray, dimension: int, normalize: bool = False) -> np.ndarray:
    matrix = _t_matrix(parameters, dimension)
    rho = matrix @ matrix.conj().T
    if normalize:
        trace = np.real(np.trace(rho))
        if trace > 1e-14:
            rho = rho / trace
    return rho


def _parameters_from_density(rho: np.ndarray, scale: float = 1.0) -> np.ndarray:
    dimension = rho.shape[0]
    regularized = (rho + rho.conj().T) / 2.0
    values, vectors = np.linalg.eigh(regularized)
    values = np.maximum(values, 1e-10)
    square_root = (vectors * np.sqrt(values)) @ vectors.conj().T
    return _parameters_from_t(square_root * np.sqrt(max(float(scale), 1e-12)))


def partial_transpose(rho: np.ndarray, dims: Iterable[int], subsystem: int = 0) -> np.ndarray:
    """Return the partial transpose of a multipartite density matrix."""
    dimensions = _validate_dims(dims)
    matrix = np.asarray(rho, dtype=complex)
    dimension = int(np.prod(dimensions))
    if matrix.ndim == 1:
        if matrix.size != dimension:
            raise ValueError("dims do not match rho shape")
        matrix = np.outer(matrix, matrix.conj())
    if matrix.shape != (dimension, dimension):
        raise ValueError("dims do not match rho shape")
    if subsystem < 0:
        subsystem += len(dimensions)
    if subsystem < 0 or subsystem >= len(dimensions):
        raise ValueError("subsystem index is out of range")
    tensor = matrix.reshape(dimensions + dimensions)
    axes = list(range(2 * len(dimensions)))
    axes[subsystem], axes[subsystem + len(dimensions)] = (
        axes[subsystem + len(dimensions)],
        axes[subsystem],
    )
    return tensor.transpose(axes).reshape((dimension, dimension))


def negativity(rho: np.ndarray, dims: Iterable[int], subsystem: int = 0) -> float:
    """Return the trace-norm negativity for an explicitly partitioned state."""
    transposed = partial_transpose(rho, dims=dims, subsystem=subsystem)
    eigenvalues = np.linalg.eigvalsh((transposed + transposed.conj().T) / 2.0)
    return float(np.sum(np.abs(eigenvalues[eigenvalues < 0.0])))


@dataclass(frozen=True)
class OAMTomographyResult:
    """Result object returned by :meth:`OAMTomography.fit_povm`.

    The object is iterable, so existing code can also unpack it as
    ``rho, intensity, fval``.
    """

    rho: np.ndarray
    intensity: float
    fval: float

    def __iter__(self):
        yield self.rho
        yield self.intensity
        yield self.fval


class OAMTomography:
    """MLE/HMLE for finite-dimensional explicit POVMs.

    ``dims`` describes subsystem dimensions, not necessarily qubit counts. For
    example, ``[2, 5]`` is polarization times a five-mode OAM truncation and
    ``[5, 5]`` is two five-dimensional OAM subsystems.
    """

    def __init__(
        self,
        dims: int | Iterable[int],
        *,
        beta: float = 0.0,
        ftol: float = 1.49012e-8,
        xtol: float = 1.49012e-8,
        gtol: float = 0.0,
        maxfev: int = 0,
    ):
        self.dims = _validate_dims(dims)
        self.dimension = int(np.prod(self.dims))
        self.beta = float(beta)
        self.ftol = float(ftol)
        self.xtol = float(xtol)
        self.gtol = float(gtol)
        self.maxfev = int(maxfev)
        self.last_result: OAMTomographyResult | None = None

    def set_dims(self, dims: int | Iterable[int]) -> None:
        self.dims = _validate_dims(dims)
        self.dimension = int(np.prod(self.dims))
        self.last_result = None

    def getDimension(self) -> int:
        """Return the total Hilbert-space dimension."""
        return self.dimension

    @staticmethod
    def _prepare_inputs(measurements, counts, accidentals, intensities, dimension):
        effects = np.asarray(measurements, dtype=complex)
        if effects.ndim == 3:
            effects = effects[:, np.newaxis, :, :]
        if effects.ndim != 4 or effects.shape[2] != effects.shape[3]:
            raise ValueError("measurements must have shape (n_settings,n_outcomes,D,D)")
        n_settings, n_outcomes, effect_dimension, _ = effects.shape
        if effect_dimension != dimension:
            raise ValueError(f"POVM dimension {effect_dimension} does not match dims")

        observed = np.asarray(counts, dtype=float)
        if observed.ndim == 1:
            observed = observed[:, np.newaxis]
        if observed.shape != (n_settings, n_outcomes):
            raise ValueError("counts must have shape (n_settings,n_outcomes)")

        if accidentals is None:
            accidental_values = np.zeros_like(observed)
        else:
            accidental_values = np.asarray(accidentals, dtype=float)
            if accidental_values.ndim == 1:
                accidental_values = accidental_values[:, np.newaxis]
            if accidental_values.shape != observed.shape:
                raise ValueError("accidentals must match counts shape")

        if intensities is None:
            setting_norms = np.ones(n_settings, dtype=float)
        elif np.isscalar(intensities):
            setting_norms = np.full(n_settings, float(intensities), dtype=float)
        else:
            setting_norms = np.asarray(intensities, dtype=float)
            if setting_norms.shape != (n_settings,):
                raise ValueError("intensities must have one value per measurement setting")

        arrays = (effects, observed, accidental_values, setting_norms)
        if any(np.any(~np.isfinite(array)) for array in arrays):
            raise ValueError("measurements, counts, accidentals and intensities must be finite")
        if np.any(observed < 0.0):
            raise ValueError("counts must be non-negative")
        if np.any(accidental_values < 0.0):
            raise ValueError("accidentals must be non-negative")
        if np.any(setting_norms <= 0.0):
            raise ValueError("intensities must be positive")

        for effect in effects.reshape((-1, dimension, dimension)):
            if not np.allclose(effect, effect.conj().T, atol=1e-8):
                raise ValueError("POVM effects must be Hermitian")
            if np.min(np.linalg.eigvalsh((effect + effect.conj().T) / 2.0)) < -1e-8:
                raise ValueError("POVM effects must be positive semidefinite")

        flat_effects = effects.reshape((-1, dimension, dimension))
        flat_counts = observed.reshape(-1)
        flat_accidentals = accidental_values.reshape(-1)
        flat_norms = np.repeat(setting_norms, n_outcomes)
        if flat_effects.shape[0] < dimension * dimension:
            raise ValueError(
                "POVM data are underdetermined for MLE: need at least "
                f"dimension**2={dimension * dimension} results, got {flat_effects.shape[0]}"
            )
        return flat_effects, flat_counts, flat_accidentals, flat_norms

    def _residual(self, parameters, counts, effects, accidentals, norms, method):
        raw_rho = _density_from_parameters(parameters, self.dimension, normalize=False)
        predictions = norms * np.real(np.einsum("nij,ji->n", effects, raw_rho)) + accidentals
        predictions = np.maximum(predictions, 1e-12)
        base = (predictions - counts) / np.sqrt(predictions)
        if method == "MLE":
            return base
        determinant = max(float(np.real(np.linalg.det(raw_rho))), 1e-300)
        hedge = -2.0 * self.beta * np.log(determinant) / max(len(counts), 1)
        return np.sqrt(np.maximum(base * base + hedge, 0.0))

    def fit_povm(
        self,
        measurements,
        counts,
        *,
        accidentals=None,
        intensities=None,
        method: str = "MLE",
        beta: float | None = None,
        rho_start: np.ndarray | None = None,
    ) -> OAMTomographyResult:
        """Fit a normalized density matrix to explicit POVM count data."""
        method = str(method).upper()
        if method not in {"MLE", "HMLE"}:
            raise ValueError("OAMTomography supports only MLE and HMLE for explicit POVMs")
        effects, observed, accidental_values, setting_norms = self._prepare_inputs(
            measurements, counts, accidentals, intensities, self.dimension
        )
        if method == "HMLE":
            hedge_beta = self.beta if beta is None else float(beta)
            if hedge_beta <= 0.0:
                raise ValueError("HMLE requires a positive beta")
            old_beta = self.beta
            self.beta = hedge_beta
        else:
            old_beta = self.beta

        if rho_start is None:
            starting_state = np.eye(self.dimension, dtype=complex) / self.dimension
        else:
            starting_state = _as_density_matrix(rho_start, self.dimension)
        initial_scale = max(
            float(np.mean(observed / np.maximum(setting_norms, 1e-12))),
            1e-6,
        ) * self.dimension
        parameters = _parameters_from_density(starting_state, scale=initial_scale)

        try:
            fitted, _ = leastsq(
                self._residual,
                parameters,
                args=(observed, effects, accidental_values, setting_norms, method),
                ftol=self.ftol,
                xtol=self.xtol,
                gtol=self.gtol,
                maxfev=self.maxfev,
            )
            residual = self._residual(fitted, observed, effects, accidental_values, setting_norms, method)
        finally:
            self.beta = old_beta

        raw_rho = _density_from_parameters(fitted, self.dimension, normalize=False)
        intensity = float(np.real(np.trace(raw_rho)))
        if intensity <= 1e-14:
            raise RuntimeError("MLE returned a zero-trace state")
        rho = (raw_rho / intensity + raw_rho.conj().T / intensity) / 2.0
        result = OAMTomographyResult(rho=rho, intensity=intensity, fval=float(np.sum(residual * residual)))
        self.last_result = result
        return result

    # Familiar spelling for callers porting only the explicit POVM path from
    # the historical tomography package. This is a method of the OAM class,
    # not a change to the historical Tomography class.
    StateTomography_POVM = fit_povm

    def state_properties(self, rho: np.ndarray | None = None) -> dict[str, float]:
        """Return dimension-independent basic state properties."""
        if rho is None:
            if self.last_result is None:
                raise ValueError("no fitted state is available")
            rho = self.last_result.rho
        matrix = _as_density_matrix(rho, self.dimension)
        eigenvalues = np.linalg.eigvalsh(matrix)
        positive = eigenvalues[eigenvalues > 1e-14]
        entropy = float(-np.sum(positive * np.log2(positive)))
        return {
            "purity": float(np.real(np.trace(matrix @ matrix))),
            "entropy": entropy,
            "trace": float(np.real(np.trace(matrix))),
        }


# Explicit alias for users who prefer the shorter name inside qtools.tomo.oam.
Tomography = OAMTomography


__all__ = [
    "OAMTomography",
    "OAMTomographyResult",
    "Tomography",
    "partial_transpose",
    "negativity",
]
