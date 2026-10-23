"""Phase patterns for electronic pseudo-knife-edge measurements."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt


Bounds = tuple[int, int, int, int]


def pseudo_knife_edge(
    shape: tuple[int, int],
    bounds: Bounds,
    axis: str,
    edge: int | float,
    *,
    scan_bounds: Bounds | None = None,
    seed: int | None = None,
    phase_range: tuple[float, float] = (0.0, 2 * np.pi),
) -> npt.NDArray[np.float64]:
    """Generate an SLM-sized random-phase electronic knife edge.

    The returned array is zero outside ``scan_bounds``.  Within the scan
    rectangle, pixels before ``edge`` along ``axis`` contain reproducible
    uniform random phase and the remainder contains zero phase.  Reusing the
    same ``seed`` for several edge positions therefore moves only the edge,
    rather than changing the random texture at every measurement.

    Args:
        shape: Phase-array shape as ``(height, width)``.
        bounds: Active phase-region bounds as ``(left, right, top, bottom)``.
        axis: Scan direction, either ``"x"`` or ``"y"``.
        edge: Edge coordinate in SLM pixel coordinates.
        scan_bounds: Rectangle to scan. Defaults to ``bounds``.
        seed: Optional random seed for deterministic phase texture.
        phase_range: Inclusive lower and exclusive upper random-phase limits,
            in radians.
    """

    height, width = _validate_shape(shape)
    active = _validate_bounds(bounds, (width, height), name="bounds")
    scan = _validate_bounds(
        active if scan_bounds is None else scan_bounds,
        (width, height),
        name="scan_bounds",
    )
    if not _contains(active, scan):
        raise ValueError(f"scan_bounds {scan} must be inside bounds {active}.")

    normalized_axis = axis.lower()
    if normalized_axis not in {"x", "y"}:
        raise ValueError("axis must be 'x' or 'y'.")

    low, high = (float(value) for value in phase_range)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError("phase_range must contain two finite values with high > low.")

    edge_value = int(round(float(edge)))
    edge_min = scan[0] if normalized_axis == "x" else scan[2]
    edge_max = scan[1] if normalized_axis == "x" else scan[3]
    if not edge_min <= edge_value <= edge_max:
        raise ValueError(
            f"edge {edge_value} must lie inside the {normalized_axis}-axis "
            f"scan interval [{edge_min}, {edge_max}]."
        )

    left, right, top, bottom = scan
    rng = np.random.default_rng(seed)
    random_phase = rng.uniform(
        low,
        high,
        size=(bottom - top, right - left),
    )
    result = np.zeros((height, width), dtype=np.float64)

    if normalized_axis == "x":
        result[top:bottom, left:edge_value] = random_phase[:, : edge_value - left]
    else:
        result[top:edge_value, left:right] = random_phase[: edge_value - top, :]
    return result


def _validate_shape(shape: Sequence[int]) -> tuple[int, int]:
    if len(shape) != 2:
        raise ValueError("shape must contain (height, width).")
    height, width = (int(value) for value in shape)
    if height <= 0 or width <= 0:
        raise ValueError("shape dimensions must be positive.")
    return height, width


def _validate_bounds(
    bounds: Sequence[int], resolution: tuple[int, int], *, name: str
) -> Bounds:
    if len(bounds) != 4:
        raise ValueError(f"{name} must contain (left, right, top, bottom).")
    left, right, top, bottom = (int(value) for value in bounds)
    width, height = resolution
    if not (0 <= left <= right <= width and 0 <= top <= bottom <= height):
        raise ValueError(f"Invalid {name} {tuple(bounds)} for resolution {resolution}.")
    if left == right or top == bottom:
        raise ValueError(f"{name} cannot have zero area.")
    return left, right, top, bottom


def _contains(container: Bounds, child: Bounds) -> bool:
    return (
        container[0] <= child[0] <= child[1] <= container[1]
        and container[2] <= child[2] <= child[3] <= container[3]
    )


__all__ = ["Bounds", "pseudo_knife_edge"]
