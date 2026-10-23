"""Perfect-vortex phase generation."""

from __future__ import annotations

import numpy as np


def perfect_spiral(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    order: int,
    radial_frequency: float,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    """Return an axicon-plus-spiral phase for a perfect vortex beam.

    ``radial_frequency`` is the radial spatial frequency in cycles per pixel.
    Coordinates and ``center`` use global SLM pixel coordinates in ``(x, y)``
    order. The returned array has ``shape`` in ``(height, width)`` order and
    is zero outside ``bounds``.
    """

    radial_frequency = float(radial_frequency)
    if not np.isfinite(radial_frequency):
        raise ValueError("radial_frequency must be finite.")

    left, right, top, bottom = bounds
    default_center = ((left + right - 1) / 2, (top + bottom - 1) / 2)
    cx, cy = default_center if center is None else (float(center[0]), float(center[1]))
    xs = np.arange(left, right, dtype=np.float64)
    ys = np.arange(top, bottom, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)
    radius = np.hypot(xx - cx, yy - cy)
    azimuth = np.arctan2(yy - cy, xx - cx)
    values = float(order) * azimuth + 2 * np.pi * radial_frequency * radius

    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


__all__ = ["perfect_spiral"]
