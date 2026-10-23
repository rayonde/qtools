"""Coherent superposition of existing phase masks."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from qtools.slm.phase.phasemask import PhaseMask


Coefficient = complex | npt.ArrayLike


def lg_radial_amplitude(
    mask: PhaseMask,
    *,
    waist: float,
    order: int,
    center: tuple[float, float] | None = None,
) -> npt.NDArray[np.float64]:
    """Return the unnormalized ``p=0`` Laguerre-Gaussian radial envelope.

    The returned array is the radial factor from the laboratory note,

    ``exp(-(r / waist) ** 2) * (sqrt(2) * r / waist) ** abs(order)``.

    ``waist`` is in metres. ``center`` uses SLM pixel coordinates in
    ``(x, y)`` order. If the input mask is a region mask, values outside its
    active region are set to zero.
    """

    if not isinstance(mask, PhaseMask):
        raise TypeError("lg_radial_amplitude() expects a PhaseMask.")
    waist = float(waist)
    if not np.isfinite(waist) or waist <= 0:
        raise ValueError("waist must be a finite positive length in metres.")
    if not isinstance(order, (int, np.integer)):
        raise TypeError("order must be an integer.")

    width, height = mask.geometry.resolution
    bounds = mask.region_bounds or (0, width, 0, height)
    left, right, top, bottom = bounds
    default_center = ((left + right - 1) / 2, (top + bottom - 1) / 2)
    cx, cy = default_center if center is None else (float(center[0]), float(center[1]))

    xs = (
        (np.arange(left, right, dtype=np.float64) - cx)
        * mask.geometry.pitch_um[0]
        * 1e-6
    )
    ys = (
        (np.arange(top, bottom, dtype=np.float64) - cy)
        * mask.geometry.pitch_um[1]
        * 1e-6
    )
    xx, yy = np.meshgrid(xs, ys)
    radius = np.hypot(xx, yy)
    radial = np.exp(-(radius / waist) ** 2)
    radial *= (np.sqrt(2) * radius / waist) ** abs(int(order))

    result = np.zeros(mask.shape, dtype=np.float64)
    result[top:bottom, left:right] = radial
    return result


def superposition(
    *masks: PhaseMask,
    coefficients: Sequence[Coefficient],
) -> PhaseMask:
    """Return the phase of a coherently weighted complex-field sum.

    Each input mask stores a phase in radians. It is interpreted as a unit
    phasor and weighted by the corresponding scalar or per-pixel coefficient::

        field = sum(coefficient * exp(1j * mask.array))
        phase = angle(field / ||field||_2)

    Coefficients therefore carry both relative amplitudes and relative phase,
    for example ``(amplitude_0, amplitude_1 * exp(1j * delta))``. The
    normalization makes the intermediate superposition a normalized field;
    it does not change the phase of a non-zero field.

    Parameters
    ----------
    *masks:
        Existing ``PhaseMask`` instances belonging to the same geometry.
    coefficients:
        One scalar or full-size array per input mask. Arrays must have the
        same ``(height, width)`` shape as the masks.
    """

    if not masks:
        raise ValueError("superposition() requires at least one PhaseMask.")
    if coefficients is None:
        raise ValueError("coefficients must be provided.")
    if len(coefficients) != len(masks):
        raise ValueError("coefficients must have one entry per PhaseMask.")

    first = masks[0]
    if not isinstance(first, PhaseMask):
        raise TypeError("superposition() accepts PhaseMask instances only.")
    geometry = first.geometry
    shape = first.shape
    field = np.zeros(shape, dtype=np.complex128)

    for index, (mask, coefficient) in enumerate(zip(masks, coefficients)):
        if not isinstance(mask, PhaseMask):
            raise TypeError("superposition() accepts PhaseMask instances only.")
        if mask.geometry is not geometry:
            raise ValueError("Phase masks must belong to the same SLM geometry.")
        if not np.isfinite(mask.array).all():
            raise ValueError(f"PhaseMask at index {index} contains non-finite values.")

        try:
            weight = np.asarray(coefficient, dtype=np.complex128)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Coefficient at index {index} is not numeric.") from exc

        if weight.ndim != 0 and weight.shape != shape:
            raise ValueError(
                f"Coefficient at index {index} has shape {weight.shape}; "
                f"expected a scalar or {shape}."
            )
        if not np.isfinite(weight).all():
            raise ValueError(f"Coefficient at index {index} contains non-finite values.")

        field += weight * np.exp(1j * mask.array)

    norm = float(np.linalg.norm(field.ravel()))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("The superposition has zero or non-finite L2 norm.")

    phase = np.angle(field / norm)
    return PhaseMask(phase, geometry)


__all__ = ["lg_radial_amplitude", "superposition"]
