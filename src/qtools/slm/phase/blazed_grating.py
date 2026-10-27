"""Blazed-grating phase generation."""

from __future__ import annotations

import numpy as np


def normalize_direction(direction: int | str) -> int:
    """Return ``+1`` for an increasing phase ramp or ``-1`` for a decreasing one."""

    if isinstance(direction, str):
        values = {
            "forward": 1,
            "increasing": 1,
            "positive": 1,
            "0->2pi": 1,
            "0_to_2pi": 1,
            "reverse": -1,
            "decreasing": -1,
            "negative": -1,
            "2pi->0": -1,
            "2pi_to_0": -1,
        }
        try:
            return values[direction.lower()]
        except KeyError as exc:
            raise ValueError(
                "direction must be 1/-1 or one of 'forward'/'reverse'."
            ) from exc
    if isinstance(direction, bool):
        raise ValueError("direction must be 1 or -1.")
    try:
        value = float(direction)
    except (TypeError, ValueError) as exc:
        raise ValueError("direction must be 1 or -1.") from exc
    if not np.isfinite(value) or value not in (-1.0, 1.0):
        raise ValueError("direction must be 1 or -1.")
    return int(value)


def validate_period(period: int | float) -> int:
    """Validate and normalize a pixel period."""

    if isinstance(period, bool):
        raise TypeError("period must be a positive integer number of pixels.")
    value = float(period)
    if not np.isfinite(value) or value <= 0 or not value.is_integer():
        raise ValueError("period must be a positive integer number of pixels.")
    return int(value)


def effective_pitch_um(period_angle: float, pitch_um: tuple[float, float]) -> float:
    """Return pixel pitch along the grating normal for ``period_angle``."""

    theta = np.deg2rad(float(period_angle))
    # The grating normal is (cos(angle), -sin(angle)) in image coordinates.
    return float(np.hypot(pitch_um[0] * np.cos(theta), pitch_um[1] * np.sin(theta)))


def predicted_deflection_angle(
    period: int | float,
    angle: float,
    pitch_um: tuple[float, float],
    wavelength: float,
    direction: int | str = 1,
) -> float | None:
    """Predict the first-order deflection angle in degrees.

    ``None`` means that the requested period is below the propagating
    diffraction limit for the selected wavelength and pixel pitch.
    """

    pixels = validate_period(period)
    sign = normalize_direction(direction)
    if not np.isfinite(float(angle)):
        raise ValueError("angle must be a finite number of degrees.")
    pitch_m = effective_pitch_um(angle, pitch_um) * 1e-6
    sine = float(wavelength) / (pixels * pitch_m)
    if sine > 1:
        return None
    return float(sign * np.degrees(np.arcsin(sine)))


def blazed_grating(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    pitch_um: tuple[float, float],
    wavelength: float,
    *,
    period: int | float,
    angle: float = 0.0,
    direction: int | str = 1,
    max_phase: float = 2 * np.pi,
    order: int | None = None,
) -> np.ndarray:
    """Generate a pixel-periodic blazed grating in radians.

    ``period`` is the number of pixels per phase cycle. ``angle`` is the
    orientation in degrees: zero ramps left to right, +90 ramps bottom to top,
    and -90 ramps top to bottom. ``order`` is the number of equally spaced
    phase levels per cycle; when omitted, there is one phase level per pixel.
    """

    pixels = validate_period(period)
    sign = normalize_direction(direction)
    if not np.isfinite(float(angle)):
        raise ValueError("angle must be a finite number of degrees.")
    phase_limit = float(max_phase)
    if not np.isfinite(phase_limit) or phase_limit <= 0:
        raise ValueError("max_phase must be a finite positive number of radians.")
    if order is None:
        levels = pixels
    else:
        if isinstance(order, bool) or int(order) != order or int(order) < 1:
            raise ValueError("order must be a positive integer number of phase levels.")
        levels = int(order)

    left, right, top, bottom = bounds
    xs = np.arange(left, right) - (left + right - 1) / 2
    ys = np.arange(top, bottom) - (top + bottom - 1) / 2
    xx, yy = np.meshgrid(xs, ys)
    theta = np.deg2rad(float(angle))
    coordinate = np.cos(theta) * xx - np.sin(theta) * yy
    fraction = np.mod(sign * coordinate / pixels, 1.0)
    values = np.floor(fraction * levels) / levels * phase_limit

    result = np.zeros(shape, dtype=np.float64)
    result[top:bottom, left:right] = values
    return result


__all__ = [
    "blazed_grating",
    "effective_pitch_um",
    "normalize_direction",
    "predicted_deflection_angle",
    "validate_period",
]
