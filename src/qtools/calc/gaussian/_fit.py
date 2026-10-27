"""Bounded Gaussian least squares using only NumPy and SciPy."""

from operator import index

import numpy as np
from scipy.ndimage import center_of_mass, gaussian_filter, label, maximum_filter
from scipy.optimize import least_squares

from ._io import read_image, validate_image
from ._models import BeamParameters, GaussianFitResult


def _positive_integer(value, name):
    try:
        result = index(value)
    except TypeError as error:
        raise ValueError(f"{name} must be a positive integer.") from error
    if isinstance(value, (bool, np.bool_)) or result < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return result


def _validate_detection(shape, threshold_factor, min_distance):
    if not np.isfinite(threshold_factor) or not 0 < threshold_factor < 1:
        raise ValueError("threshold_factor must be between 0 and 1 (exclusive).")
    if min_distance is None:
        return max(3, min(shape) // 40)
    return _positive_integer(min_distance, "min_distance")


def find_beam_centers(data, n_beams=1, *, threshold_factor=0.1, min_distance=None):
    """Return separated bright centers as an (n_beams, 2) array of (x, y).

    Smooth by one pixel before detection. The threshold is a fraction of
    peak height above median background; min_distance is measured in pixels.
    Unresolved/strongly overlapping beams need explicit centers passed to fit.
    """
    array = validate_image(data).astype(float, copy=False)
    n_beams = _positive_integer(n_beams, "n_beams")
    distance = _validate_detection(array.shape, threshold_factor, min_distance)
    smooth = gaussian_filter(array, 1.0)
    background = float(np.median(smooth))
    height = float(smooth.max() - background)
    if height <= 0:
        raise ValueError("No bright beam detected above the background.")
    maxima = smooth == maximum_filter(smooth, size=2 * distance + 1)
    maxima &= smooth > background + threshold_factor * height
    regions, count = label(maxima)
    if not count:
        raise ValueError(
            "No beam peaks found; lower threshold_factor or supply centers."
        )
    candidates = np.asarray(center_of_mass(maxima, regions, np.arange(1, count + 1)))
    iy, ix = np.rint(candidates).astype(int).T
    order = np.argsort(-smooth[iy, ix], kind="stable")
    selected = []
    for candidate in candidates[order]:
        if all(
            np.linalg.norm(candidate - previous) >= distance for previous in selected
        ):
            selected.append(candidate)
            if len(selected) == n_beams:
                break
    if len(selected) < n_beams:
        raise ValueError(
            f"Found {len(selected)} separated peaks, requested {n_beams}; "
            "adjust threshold_factor/min_distance or supply centers."
        )
    centers = np.asarray(selected)[:, ::-1]
    return centers[np.lexsort((centers[:, 1], centers[:, 0]))]


def _initial_parameters(data, centers, fix_theta, *, use_moment_center=True):
    y, x = np.ogrid[: data.shape[0], : data.shape[1]]
    weights = np.maximum(data, 0)
    weights[weights < weights.max() * 0.1] = 0
    nearest = None
    if len(centers) > 1:
        nearest = np.zeros(data.shape, dtype=int)
        best_distance = np.full(data.shape, np.inf)
        for i, (cx, cy) in enumerate(centers):
            distance = (x - cx) ** 2 + (y - cy) ** 2
            mask = distance < best_distance
            nearest[mask] = i
            best_distance[mask] = distance[mask]
    parameters = []
    for i, (cx, cy) in enumerate(centers):
        local = weights if nearest is None else np.where(nearest == i, weights, 0)
        mass = local.sum()
        if mass <= 0:
            raise ValueError(
                "An initial beam has no signal; adjust centers or n_beams."
            )
        mx, my = float(np.sum(local * x) / mass), float(np.sum(local * y) / mass)
        dx, dy = x - mx, y - my
        covariance = (
            np.array(
                [
                    [np.sum(local * dx * dx), np.sum(local * dx * dy)],
                    [np.sum(local * dx * dy), np.sum(local * dy * dy)],
                ]
            )
            / mass
        )
        if fix_theta:
            sx, sy = np.sqrt(np.maximum(np.diag(covariance), 0.25))
            theta = 0.0
        else:
            values, vectors = np.linalg.eigh(covariance)
            sx, sy = np.sqrt(np.maximum(values[::-1], 0.25))
            theta = (
                np.arctan2(vectors[1, 1], vectors[0, 1]) + np.pi / 2
            ) % np.pi - np.pi / 2
        if len(centers) == 1 and use_moment_center:
            cx, cy = mx, my
        parameters.extend([float(local.max()), cx, cy, sx, sy])
        if not fix_theta:
            parameters.append(theta)
    parameters.append(0.0)
    return np.asarray(parameters)


def _evaluate(parameters, x, y, n_beams, fix_theta, *, jacobian=False):
    stride = 5 if fix_theta else 6
    output = (
        np.ones((x.size, len(parameters)))
        if jacobian
        else np.full(x.size, parameters[-1])
    )
    for i in range(n_beams):
        start = i * stride
        amplitude, cx, cy, sx, sy = parameters[start : start + 5]
        theta = 0.0 if fix_theta else parameters[start + 5]
        cosine, sine = np.cos(theta), np.sin(theta)
        dx, dy = x - cx, y - cy
        u, v = cosine * dx + sine * dy, -sine * dx + cosine * dy
        envelope = np.exp(-0.5 * ((u / sx) ** 2 + (v / sy) ** 2))
        signal = amplitude * envelope
        if jacobian:
            output[:, start] = envelope
            output[:, start + 1] = signal * (cosine * u / sx**2 - sine * v / sy**2)
            output[:, start + 2] = signal * (sine * u / sx**2 + cosine * v / sy**2)
            output[:, start + 3] = signal * u**2 / sx**3
            output[:, start + 4] = signal * v**2 / sy**3
            if not fix_theta:
                output[:, start + 5] = signal * u * v * (1 / sy**2 - 1 / sx**2)
        else:
            output += signal
    return output


def fit(
    source,
    *,
    n_beams=1,
    pixel_size=1.0,
    unit="px",
    shape=None,
    bit_depth=8,
    fix_theta=False,
    threshold_factor=0.1,
    min_distance=None,
    centers=None,
    max_points=100_000,
    max_nfev=300,
):
    """Fit one or more positive Gaussian beams plus a shared constant background.

    source: 2D grayscale array, RAW path, or image path.
    pixel_size/unit: physical length per pixel and its label (e.g. 3.75, 'um').
    shape: (height, width), needed for non-4:3 RAW files.
    centers: optional initial (x, y) pixel coordinates, one per beam.
    max_points: target sample count; None fits every pixel. A uniform stride
        is limited to resolve estimated beam widths. All quality metrics and
        plotted/evaluated images use the original full resolution.

    Positions and sigma in the returned beams stay in pixels; to_dict() and
    plotting apply pixel_size. Rotating fits use major/minor axes. Fixed-theta
    fits preserve x/y axes. Nonconvergence raises RuntimeError.
    """
    n_beams = _positive_integer(n_beams, "n_beams")
    max_nfev = _positive_integer(max_nfev, "max_nfev")
    if not np.isfinite(pixel_size) or pixel_size <= 0:
        raise ValueError("pixel_size must be finite and positive.")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit must be a nonempty string.")
    if max_points is not None:
        max_points = _positive_integer(max_points, "max_points")
    data = np.array(
        read_image(source, shape=shape, bit_depth=bit_depth), dtype=float, copy=True
    )
    height, width = data.shape
    distance = _validate_detection(data.shape, threshold_factor, min_distance)
    scale = float(np.ptp(data))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Cannot fit an image with no intensity variation.")
    background = float(np.percentile(data, 10))
    normalized = (data - background) / scale
    use_moment_center = centers is None
    if centers is None:
        if n_beams == 1:
            centers = np.array([[(width - 1) / 2, (height - 1) / 2]])
        else:
            centers = find_beam_centers(
                normalized,
                n_beams,
                threshold_factor=threshold_factor,
                min_distance=distance,
            )
    else:
        centers = np.asarray(centers, dtype=float)
        if centers.shape != (n_beams, 2) or not np.isfinite(centers).all():
            raise ValueError(
                "centers must have shape (n_beams, 2) with finite (x, y) coordinates."
            )
        if np.any(centers < 0) or np.any(centers > [width - 1, height - 1]):
            raise ValueError("centers must lie inside the image.")
    initial = _initial_parameters(
        normalized, centers, fix_theta, use_moment_center=use_moment_center
    )
    stride = 5 if fix_theta else 6
    step = 1
    if max_points is not None:
        target_step = int(np.ceil(np.sqrt(data.size / max_points)))
        min_sigma = min(initial[i * stride + j] for i in range(n_beams) for j in (3, 4))
        step = max(1, min(target_step, int(min_sigma / 2)))
    y, x = np.mgrid[0:height:step, 0:width:step]
    x, y = x.ravel().astype(float), y.ravel().astype(float)
    observed = normalized[::step, ::step].ravel()
    if observed.size <= initial.size:
        raise ValueError("Not enough sampled pixels for the requested number of beams.")
    lower, upper = [], []
    for _ in range(n_beams):
        lower.extend([0, 0, 0, 0.05, 0.05])
        upper.extend(
            [np.inf, width - 1, height - 1, 2 * max(data.shape), 2 * max(data.shape)]
        )
        if not fix_theta:
            lower.append(-np.pi)
            upper.append(np.pi)
    lower.append(-np.inf)
    upper.append(np.inf)
    optimized = least_squares(
        lambda p: _evaluate(p, x, y, n_beams, fix_theta) - observed,
        initial,
        jac=lambda p: _evaluate(p, x, y, n_beams, fix_theta, jacobian=True),
        bounds=(lower, upper),
        x_scale="jac",
        max_nfev=max_nfev,
        ftol=1e-9,
        xtol=1e-9,
        gtol=1e-9,
    )
    if not optimized.success:
        raise RuntimeError(f"Gaussian fit did not converge: {optimized.message}")
    beams = []
    for i in range(n_beams):
        amplitude, cx, cy, sx, sy = (
            float(v) for v in optimized.x[i * stride : i * stride + 5]
        )
        theta = 0.0 if fix_theta else float(optimized.x[i * stride + 5])
        if not fix_theta:
            if sy > sx:
                sx, sy = sy, sx
                theta += np.pi / 2
            theta = (theta + np.pi / 2) % np.pi - np.pi / 2
        beams.append(BeamParameters(amplitude * scale, cx, cy, sx, sy, theta))
    beams.sort(key=lambda beam: beam.center)
    data.setflags(write=False)
    return GaussianFitResult(
        beams=tuple(beams),
        offset=float(optimized.x[-1] * scale + background),
        data=data,
        pixel_size=float(pixel_size),
        unit=unit,
        success=bool(optimized.success),
        message=str(optimized.message),
        nfev=optimized.nfev,
        sample_step=step,
    )
