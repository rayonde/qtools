"""Spiral/vortex phase generation."""

from __future__ import annotations

import numpy as np


def spiral(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    order: int,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    left, right, top, bottom = bounds
    default_center = ((left + right - 1) / 2, (top + bottom - 1) / 2)
    cx, cy = default_center if center is None else (float(center[0]), float(center[1]))
    xs = np.arange(left, right, dtype=np.float64)
    ys = np.arange(top, bottom, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)
    values = float(order) * np.arctan2(yy - cy, xx - cx)
    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


__all__ = ["spiral"]
