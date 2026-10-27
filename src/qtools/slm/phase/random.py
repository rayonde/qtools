"""Random phase-mask generation."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


Bounds = tuple[int, int, int, int]


def random_phase(
    shape: tuple[int, int],
    bounds: Bounds,
    *,
    seed: int | None = None,
    phase_range: tuple[float, float] = (0.0, 2 * np.pi),
) -> npt.NDArray[np.float64]:
    """Generate a reproducible uniform random phase in a rectangular region.

    ``shape`` is ``(height, width)`` and ``bounds`` is
    ``(left, right, top, bottom)``. Pixels outside the region are zero.
    Reusing ``seed`` produces the same phase mask.
    """

    if len(shape) != 2:
        raise ValueError("shape must contain (height, width).")
    height, width = (int(value) for value in shape)
    left, right, top, bottom = (int(value) for value in bounds)
    if height <= 0 or width <= 0:
        raise ValueError("shape dimensions must be positive.")
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"Invalid bounds {bounds} for resolution {(width, height)}.")

    low, high = (float(value) for value in phase_range)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError("phase_range must contain two finite values with high > low.")

    result = np.zeros((height, width), dtype=np.float64)
    result[top:bottom, left:right] = np.random.default_rng(seed).uniform(
        low,
        high,
        size=(bottom - top, right - left),
    )
    return result


__all__ = ["Bounds", "random_phase"]
