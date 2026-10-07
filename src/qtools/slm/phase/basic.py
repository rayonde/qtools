"""Basic analytic phase generators."""

from __future__ import annotations

import numpy as np


def flat(shape: tuple[int, int], bounds: tuple[int, int, int, int], phase: float) -> np.ndarray:
    result = np.zeros(shape, dtype=np.float64)
    left, right, top, bottom = bounds
    result[top:bottom, left:right] = float(phase)
    return result


def lens(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    pitch_um: tuple[float, float],
    wavelength: float,
    focal_length: float | tuple[float, float],
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    if isinstance(focal_length, (tuple, list)):
        fx, fy = float(focal_length[0]), float(focal_length[1])
    else:
        fx = fy = float(focal_length)
    if fx == 0 or fy == 0:
        raise ValueError("Lens focal length cannot be zero.")

    left, right, top, bottom = bounds
    default_center = ((left + right - 1) / 2, (top + bottom - 1) / 2)
    cx, cy = default_center if center is None else (float(center[0]), float(center[1]))
    xs = (np.arange(left, right, dtype=np.float64) - cx) * pitch_um[0] * 1e-6
    ys = (np.arange(top, bottom, dtype=np.float64) - cy) * pitch_um[1] * 1e-6
    xx, yy = np.meshgrid(xs, ys)
    values = np.pi * (xx**2 / (wavelength * fx) + yy**2 / (wavelength * fy))
    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


def binary(shape: tuple[int, int], bounds: tuple[int, int, int, int], period: float | tuple[float, float]) -> np.ndarray:
    px, py = (period, 0) if not isinstance(period, (tuple, list)) else period
    px, py = float(px), float(py)
    if px < 0 or py < 0:
        raise ValueError("Binary periods must be non-negative.")
    left, right, top, bottom = bounds
    xs = np.arange(left, right)
    ys = np.arange(top, bottom)
    xx, yy = np.meshgrid(xs, ys)
    if px == 0 and py == 0:
        values = np.zeros_like(xx, dtype=np.float64)
    else:
        x_phase = np.zeros_like(xx, dtype=np.float64) if px == 0 else np.mod(xx - left, px) >= px / 2
        y_phase = np.zeros_like(yy, dtype=np.float64) if py == 0 else np.mod(yy - top, py) >= py / 2
        values = np.where(np.logical_xor(x_phase, y_phase), np.pi, 0.0)
    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


__all__ = ["binary", "flat", "lens"]
