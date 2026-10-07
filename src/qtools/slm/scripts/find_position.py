"""Utilities for scanning and fitting a beam position.

The measurement-specific camera and plotting code intentionally stays outside the
core package.  This module provides a small, dependency-light fitting primitive
that experiment scripts can reuse.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit


def gaussian_background(x: np.ndarray, center: float, sigma: float, amplitude: float, background: float) -> np.ndarray:
    return background + amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def fit_position(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float, float]:
    """Fit a one-dimensional Gaussian and return center, sigma, amplitude, background."""

    x_values = np.asarray(xs, dtype=float)
    y_values = np.asarray(ys, dtype=float)
    if x_values.ndim != 1 or y_values.ndim != 1 or x_values.size != y_values.size:
        raise ValueError("xs and ys must be equally sized one-dimensional arrays.")
    if x_values.size < 4:
        raise ValueError("At least four samples are required for a position fit.")
    center = float(x_values[np.argmax(y_values)])
    sigma = max(float(np.ptp(x_values)) / 6, np.finfo(float).eps)
    guess = (center, sigma, float(np.ptp(y_values)), float(y_values.min()))
    result, _ = curve_fit(gaussian_background, x_values, y_values, p0=guess, maxfev=10_000)
    return tuple(float(value) for value in result)  # type: ignore[return-value]


__all__ = ["fit_position", "gaussian_background"]
