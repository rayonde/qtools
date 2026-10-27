"""Curve-fitting utilities for polarization calibration."""

from __future__ import annotations

import numpy as np

from .jones import transmission_retarder_pbs

try:
    import lmfit
except ImportError:  # pragma: no cover - lmfit is a project dependency
    lmfit = None


# ═══════════════════════════════════════════════════════════════════════════
# Calibration curve fit
# ═══════════════════════════════════════════════════════════════════════════


def _angle_deg(value: str | float, name: str) -> float:
    """Convert a polarization label or angle to degrees."""
    if isinstance(value, (int, float)):
        return float(value)
    label = str(value).strip().upper()
    angles = {"H": 0.0, "D": 45.0, "V": 90.0, "A": -45.0}
    if label in angles:
        return angles[label]
    try:
        return float(label)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be H, V, D, A or an angle in degrees"
        ) from exc


def _linear_jones(angle_deg: float) -> np.ndarray:
    """Jones vector for a linearly polarized state at ``angle_deg``."""
    angle = np.radians(angle_deg)
    return np.array([np.cos(angle), np.sin(angle)], dtype=complex)


def _transmission_curve(
    angles_deg: np.ndarray,
    theta_0_deg: float,
    retardance_deg: float,
    input_deg: float,
    basis_deg: float,
) -> np.ndarray:
    """Evaluate the Jones retarder/PBS model at a set of stage angles.

    ``transmission_retarder_pbs`` has a horizontal PBS projection.  We use a
    rotated coordinate frame so that arbitrary linear input and analyzer
    bases are represented by the same function.
    """
    input_relative = _linear_jones(input_deg - basis_deg)
    return np.asarray(
        transmission_retarder_pbs(
            angles_deg - theta_0_deg - basis_deg,
            retardance_deg,
            input_relative,
        ),
        dtype=float,
    ).reshape(-1)


def _segment_indices(n_points: int, n_segments: int | None, span_deg: float) -> list[np.ndarray]:
    """Split acquisition-order samples into contiguous amplitude segments."""
    if n_segments is None:
        n_segments = max(1, int(np.ceil(abs(span_deg) / 90.0)))
    if n_segments < 1:
        raise ValueError("n_segments must be at least 1")
    n_segments = min(int(n_segments), n_points)
    return [segment for segment in np.array_split(np.arange(n_points), n_segments) if segment.size]


def _segment_indices_by_valleys(
    angles: np.ndarray,
    values: np.ndarray,
    n_segments: int | None,
) -> list[np.ndarray]:
    """Split a scan at smoothed intensity valleys.

    The scan is assumed to be monotonic in acquisition order.  Segments are
    placed between intensity minima so each segment covers approximately one
    full 90-degree cycle, which makes slow power drift easier to absorb.
    """
    span_deg = float(np.ptp(angles))
    if n_segments is None:
        n_segments = max(1, int(np.ceil(abs(span_deg) / 90.0)))
    n_points = len(values)
    n_segments = min(max(1, int(n_segments)), n_points)

    if n_segments <= 1 or n_points < 6:
        return _segment_indices(n_points, n_segments, span_deg)

    window = max(3, min(n_points // 8, 15))
    kernel = np.ones(window, dtype=float) / window
    smoothed = np.convolve(values, kernel, mode="same")
    grad = np.diff(smoothed)
    valley_indices = [
        idx
        for idx in range(1, n_points - 1)
        if grad[idx - 1] <= 0.0 and grad[idx] >= 0.0
    ]

    if not valley_indices:
        return _segment_indices(n_points, n_segments, span_deg)

    min_angle_sep = abs(span_deg) / (2.0 * max(1, n_segments))
    selected: list[int] = []
    for idx in sorted(valley_indices, key=lambda i: smoothed[i]):
        if all(abs(angles[idx] - angles[other]) >= min_angle_sep for other in selected):
            selected.append(idx)

    boundaries = sorted({0, n_points} | set(selected))
    segments = [
        np.arange(boundaries[i], boundaries[i + 1], dtype=int)
        for i in range(len(boundaries) - 1)
        if boundaries[i] < boundaries[i + 1]
    ]
    if len(segments) < 1:
        return _segment_indices(n_points, n_segments, span_deg)
    return segments


def _nearest_periodic(value_deg: float, reference_deg: float, period_deg: float = 90.0) -> float:
    """Return the equivalent periodic angle nearest to ``reference_deg``."""
    return float(
        reference_deg
        + ((value_deg - reference_deg + period_deg / 2.0) % period_deg)
        - period_deg / 2.0
    )


def _estimate_theta_0_from_valleys(
    angles: np.ndarray,
    values: np.ndarray,
    estimated_theta_0: float,
    input_deg: float,
    basis_deg: float,
) -> float:
    """Return an initial theta_0 estimate from the first intensity valley.

    For an ideal half-wave plate followed by a linear analyzer, intensity
    valleys occur at ``theta_0 + 45 + (input + basis) / 2`` modulo 90 degrees.
    """
    n_points = len(values)
    if n_points < 6:
        return float(estimated_theta_0)
    window = max(3, min(n_points // 8, 15))
    kernel = np.ones(window, dtype=float) / window
    smoothed = np.convolve(values, kernel, mode="same")
    grad = np.diff(smoothed)
    valley_indices = [
        idx
        for idx in range(1, n_points - 1)
        if grad[idx - 1] <= 0.0 and grad[idx] >= 0.0
    ]
    if not valley_indices:
        return float(estimated_theta_0)
    first_valley_angle = float(angles[valley_indices[0]])
    return _nearest_periodic(
        first_valley_angle - 45.0 - (input_deg + basis_deg) / 2.0,
        float(estimated_theta_0),
    )


def fit_calibration_curve(
    angles_deg: np.ndarray,
    rates: np.ndarray,
    input_pol: str | float = "H",
    basis: str | float = "H",
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    n_segments: int | None = None,
    segment: bool = True,
    retardance_deg: float = 180.0,
    amplitude_init: float | np.ndarray | None = None,
) -> dict:
    r"""Fit a waveplate/PBS calibration curve using the Jones model.

    Model
    -----
    The measured power is modelled as

    .. math::
        I(\theta) = B(\theta) + A_k\,T(\theta; \theta_0, \delta),

    where ``T`` is :func:`transmission_retarder_pbs`, ``B`` is the supplied
    native background, ``C`` is a fitted constant offset, and ``A_k`` is an
    independently fitted amplitude for each segment.  Segmented mode places
    segment boundaries at smoothed intensity valleys so each segment covers
    approximately one 90-degree cycle.

    The fast-axis angle is periodic modulo 90° for this measurement geometry.
    The returned ``theta_0`` is therefore the equivalent angle closest to
    ``estimated_theta_0``.  The default estimate is zero, so negative values
    are retained instead of being wrapped to 0–180°.

    Parameters
    ----------
    angles_deg, rates : np.ndarray
        Stage angles and measured powers/count rates.
    input_pol, basis : str | float
        Linear input and PBS analyzer states: ``H``, ``V``, ``D``, ``A`` or
        angles in degrees.
    background : float | np.ndarray, optional
        Fixed background to subtract from the measured rates.  A scalar
        applies to every point; an array can provide one background value per
        angle.  Defaults to ``20.0`` in the input rate unit (for example,
        µW).
    estimated_theta_0 : float, optional
        Initial fast-axis estimate used to select the nearest modulo-90°
        solution.  Defaults to ``0.0`` degrees.
    n_segments : int, optional
        Number of contiguous amplitude segments.  If omitted, use one
        segment per nominal 90° intensity cycle.
    segment : bool, optional
        True uses valley-aligned segmented amplitudes.  False uses a single
        global amplitude for the whole scan.
    retardance_deg : float, optional
        Fixed waveplate retardance used by the Jones model.  Defaults to
        180 degrees for HWP calibration.
    amplitude_init : float | np.ndarray | None, optional
        Optional initial amplitude estimate(s).  A scalar applies to every
        segment; an array supplies one value per segment.  By default each
        segment is initialized from its own measured peak-to-peak range.

    Returns
    -------
    dict
        Keeps the existing ``theta_0``, ``phi``, ``visibility``,
        ``r_squared``, ``coefficients`` and ``model_func`` fields.  Additional
        fields report ``retardance_deg``, ``background``, ``amplitude`` and
        ``amplitude_segments``.
    """
    angles = np.asarray(angles_deg, dtype=float).reshape(-1)
    values = np.asarray(rates, dtype=float).reshape(-1)
    if angles.size != values.size:
        raise ValueError("angles_deg and rates must have the same length")
    if angles.size < 4:
        raise ValueError("at least four calibration points are required")
    if not np.all(np.isfinite(angles)) or not np.all(np.isfinite(values)):
        raise ValueError("angles_deg and rates must contain only finite values")

    input_deg = _angle_deg(input_pol, "input_pol")
    basis_deg = _angle_deg(basis, "basis")

    if np.isscalar(background):
        background_values = np.full_like(values, float(background), dtype=float)
        background_result: float | np.ndarray = float(background)
    else:
        background_values = np.asarray(background, dtype=float).reshape(-1)
        if background_values.size != values.size:
            raise ValueError("background array must have the same length as rates")
        if not np.all(np.isfinite(background_values)):
            raise ValueError("background must contain only finite values")
        background_result = background_values.copy()

    corrected_rates = values - background_values
    span_deg = float(np.ptp(angles))
    if segment:
        segments = _segment_indices_by_valleys(angles, corrected_rates, n_segments)
    else:
        segments = _segment_indices(angles.size, 1, span_deg)

    if lmfit is None:
        raise RuntimeError("lmfit is required for calibration fitting")

    theta_initial = _estimate_theta_0_from_valleys(
        angles,
        corrected_rates,
        estimated_theta_0,
        input_deg,
        basis_deg,
    )
    params = lmfit.Parameters()
    params.add(
        "theta_0",
        value=theta_initial,
        min=theta_initial - 45.0,
        max=theta_initial + 45.0,
    )
    params.add("retardance_deg", value=float(retardance_deg), vary=False)
    params.add(
        "offset",
        value=max(0.0, float(np.min(corrected_rates)) * 0.1),
        min=0.0,
    )
    if amplitude_init is None:
        amplitude_inits = np.asarray(
            [
                max(1.0, float(np.ptp(corrected_rates[indices])))
                for indices in segments
            ],
            dtype=float,
        )
    else:
        amplitude_inits = np.asarray(amplitude_init, dtype=float).reshape(-1)
        if amplitude_inits.size == 1:
            amplitude_inits = np.full(len(segments), float(amplitude_inits[0]))
        elif amplitude_inits.size != len(segments):
            raise ValueError(
                "amplitude_init must be a scalar or have one value per segment"
            )
    if not np.all(np.isfinite(amplitude_inits)) or np.any(amplitude_inits <= 0.0):
        raise ValueError("amplitude_init values must be finite and positive")
    for segment_number, amplitude_init in enumerate(amplitude_inits):
        params.add(
            f"amplitude_{segment_number}",
            value=float(amplitude_init),
            min=0.0,
        )

    def residual_for_lmfit(params):
        theta_0_candidate = float(params["theta_0"].value)
        retardance_candidate = float(params["retardance_deg"].value)
        fitted = np.full_like(corrected_rates, float(params["offset"].value))
        transmission = _transmission_curve(
            angles,
            theta_0_candidate,
            retardance_candidate,
            input_deg,
            basis_deg,
        )
        for segment_number, indices in enumerate(segments):
            fitted[indices] += float(
                params[f"amplitude_{segment_number}"].value
            ) * transmission[indices]
        return corrected_rates - fitted

    fit_result = lmfit.minimize(residual_for_lmfit, params, method="leastsq")
    best_theta = float(fit_result.params["theta_0"].value)
    best_retardance = float(fit_result.params["retardance_deg"].value)
    best_offset = float(fit_result.params["offset"].value)
    best_amplitudes = np.asarray(
        [fit_result.params[f"amplitude_{i}"].value for i in range(len(segments))],
        dtype=float,
    )
    best_fitted_corrected = corrected_rates - np.asarray(fit_result.residual, dtype=float)

    theta_0_deg = float(np.round(_nearest_periodic(best_theta, float(estimated_theta_0)), 12))
    retardance_deg = float(best_retardance)
    retardance_rad = float(np.radians(retardance_deg))

    # Visibility from the fitted offset and amplitude.
    probe_angles = np.linspace(0.0, 360.0, 3601)
    probe_transmission = _transmission_curve(
        probe_angles,
        theta_0_deg,
        retardance_deg,
        input_deg,
        basis_deg,
    )
    t_min = float(np.min(probe_transmission))
    t_max = float(np.max(probe_transmission))
    amplitude_mean = float(np.mean(best_amplitudes))
    denominator = 2.0 * best_offset + amplitude_mean * (t_max + t_min)
    visibility = (
        amplitude_mean * (t_max - t_min) / denominator
        if denominator != 0.0
        else 0.0
    )

    # Build a plotting model.  For a normal monotonic scan, interpolate the
    # segment amplitudes by angle; the original samples use their exact
    # acquisition-order segment amplitudes below.
    segment_centers = np.array([np.mean(angles[idx]) for idx in segments], dtype=float)
    sort_order = np.argsort(segment_centers)
    sorted_centers = segment_centers[sort_order]
    sorted_amplitudes = best_amplitudes[sort_order]
    sorted_background = background_values[np.argsort(angles)]
    sorted_angles = np.sort(angles)

    def model_func(query_angles_deg: np.ndarray) -> np.ndarray | float:
        """Evaluate the fitted Jones model at arbitrary stage angles."""
        query = np.asarray(query_angles_deg, dtype=float)
        flat_query = query.reshape(-1)
        transmission = _transmission_curve(
            flat_query,
            theta_0_deg,
            retardance_deg,
            input_deg,
            basis_deg,
        )
        if sorted_centers.size == 1:
            amplitudes = np.full(flat_query.size, sorted_amplitudes[0])
        else:
            amplitudes = np.interp(
                flat_query,
                sorted_centers,
                sorted_amplitudes,
                left=sorted_amplitudes[0],
                right=sorted_amplitudes[-1],
            )
        if np.isscalar(background):
            query_background = np.full(flat_query.size, float(background))
        else:
            query_background = np.interp(
                flat_query,
                sorted_angles,
                sorted_background,
                left=sorted_background[0],
                right=sorted_background[-1],
            )
        result = query_background + best_offset + amplitudes * transmission
        if query.ndim == 0:
            return float(result[0])
        return result.reshape(query.shape)

    fitted_values = background_values + best_fitted_corrected
    ss_res = float(np.sum((values - fitted_values) ** 2))
    ss_tot = float(np.sum((values - np.mean(values)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    # Keep the legacy Fourier coefficient keys as a summary of the fitted
    # curve.  The actual model is the Jones model above; these coefficients
    # are only a compact projection for callers that still consume them.
    coefficient_angles = np.linspace(float(np.min(angles)), float(np.max(angles)), 721)
    coefficient_values = np.asarray(model_func(coefficient_angles), dtype=float)
    coefficient_theta = np.radians(coefficient_angles)
    coefficient_matrix = np.column_stack([
        np.ones_like(coefficient_theta),
        np.cos(4.0 * coefficient_theta),
        np.sin(4.0 * coefficient_theta),
        coefficient_theta,
    ])
    coefficient_fit, _res, _rank, _singular = np.linalg.lstsq(
        coefficient_matrix,
        coefficient_values,
        rcond=None,
    )
    A, Bc, Bs, C = coefficient_fit

    return {
        "theta_0": theta_0_deg,
        "phi": retardance_rad,
        "retardance_deg": retardance_deg,
        "visibility": visibility,
        "r_squared": float(r_squared),
        "coefficients": {
            "A": float(A),
            "Bc": float(Bc),
            "Bs": float(Bs),
            "C": float(C),
        },
        "background": background_result,
        "offset": best_offset,
        "amplitude": float(np.mean(best_amplitudes)),
        "amplitude_segments": best_amplitudes.copy(),
        "n_segments": len(segments),
        "fit_method": "segmented" if len(segments) > 1 else "global",
        "model_func": model_func,
    }
