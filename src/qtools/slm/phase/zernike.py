"""ANSI-indexed Zernike phase generation."""

from __future__ import annotations

import math

import numpy as np


def _ansi_nm(index: int) -> tuple[int, int]:
    if index < 0:
        raise ValueError("Zernike index must be non-negative.")
    n = 0
    while (n + 1) * (n + 2) // 2 <= index:
        n += 1
    first = n * (n + 1) // 2
    position = index - first
    m_values = list(range(-n, n + 1, 2))
    return n, m_values[position]


def _radial(n: int, m: int, radius: np.ndarray) -> np.ndarray:
    m = abs(m)
    result = np.zeros_like(radius, dtype=np.float64)
    for k in range((n - m) // 2 + 1):
        coefficient = ((-1) ** k * math.factorial(n - k)) / (
            math.factorial(k)
            * math.factorial((n + m) // 2 - k)
            * math.factorial((n - m) // 2 - k)
        )
        result += coefficient * radius ** (n - 2 * k)
    return result


def zernike(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    index: int,
    radius: float | tuple[float, float],
    weight: float = 1.0,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    rx, ry = (radius, radius) if not isinstance(radius, (tuple, list)) else radius
    rx, ry = float(rx), float(ry)
    if rx <= 0 or ry <= 0:
        raise ValueError("Zernike radii must be positive.")
    left, right, top, bottom = bounds
    default_center = ((left + right - 1) / 2, (top + bottom - 1) / 2)
    cx, cy = default_center if center is None else (float(center[0]), float(center[1]))
    xs = (np.arange(left, right) - cx) / rx
    ys = (np.arange(top, bottom) - cy) / ry
    xx, yy = np.meshgrid(xs, ys)
    rho = np.sqrt(xx**2 + yy**2)
    theta = np.arctan2(yy, xx)
    n, m = _ansi_nm(int(index))
    radial = _radial(n, m, rho)
    values = np.where(rho <= 1, radial * (np.cos(abs(m) * theta) if m >= 0 else np.sin(abs(m) * theta)), 0.0)
    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = float(weight) * values
    return result


__all__ = ["zernike"]
