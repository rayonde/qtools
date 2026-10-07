"""Blaze grating phase generation."""

from __future__ import annotations

import numpy as np


def blaze(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    pitch_um: tuple[float, float],
    wavelength: float,
    angle: float | tuple[float, float],
) -> np.ndarray:
    ax, ay = (angle, 0.0) if not isinstance(angle, (tuple, list)) else angle
    left, right, top, bottom = bounds
    xs = (np.arange(left, right) - (left + right - 1) / 2) * pitch_um[0] * 1e-6
    ys = (np.arange(top, bottom) - (top + bottom - 1) / 2) * pitch_um[1] * 1e-6
    xx, yy = np.meshgrid(xs, ys)
    values = 2 * np.pi / wavelength * (
        np.sin(np.deg2rad(float(ax))) * xx + np.sin(np.deg2rad(float(ay))) * yy
    )
    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


__all__ = ["blaze"]
