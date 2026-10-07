"""PhaseMask and region-aware phase construction."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import numpy as np
import numpy.typing as npt

from qtools.slm.phase import basic, blaze as blaze_module, spiral as spiral_module, zernike as zernike_module

if TYPE_CHECKING:
    from qtools.slm.slm import SLMGeometry
    from qtools.slm.display.displaymask import DisplayMask


Bounds = tuple[int, int, int, int]


def _intersection(first: Bounds, second: Bounds) -> bool:
    left = max(first[0], second[0])
    right = min(first[1], second[1])
    top = max(first[2], second[2])
    bottom = min(first[3], second[3])
    return left < right and top < bottom


def _contains(container: Bounds, child: Bounds) -> bool:
    return (
        container[0] <= child[0] <= child[1] <= container[1]
        and container[2] <= child[2] <= child[3] <= container[3]
    )


class PhaseMask:
    """A complete SLM-sized phase array, stored in radians."""

    def __init__(
        self,
        array: npt.ArrayLike,
        geometry: "SLMGeometry",
        *,
        region_bounds: Bounds | None = None,
    ):
        values = np.asarray(array, dtype=np.float64)
        if values.shape != geometry.shape:
            raise ValueError(f"Phase shape {values.shape} does not match SLM shape {geometry.shape}.")
        self.array = np.ascontiguousarray(values.copy())
        self.geometry = geometry
        self.region_bounds = region_bounds

    @classmethod
    def zeros(cls, geometry: "SLMGeometry", *, region_bounds: Bounds | None = None) -> "PhaseMask":
        return cls(np.zeros(geometry.shape, dtype=np.float64), geometry, region_bounds=region_bounds)

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape

    @property
    def resolution(self) -> tuple[int, int]:
        return self.geometry.resolution

    def copy(self) -> "PhaseMask":
        return PhaseMask(self.array, self.geometry, region_bounds=self.region_bounds)

    def to_display(self, bits: int = 8, rgb: bool = False) -> "DisplayMask":
        from qtools.slm.display.displaymask import DisplayMask

        return DisplayMask.from_phase(self, bits=bits, rgb=rgb)

    def save(self, filename: str | Path, *, bits: int = 8, rgb: bool = False) -> None:
        self.to_display(bits=bits, rgb=rgb).save(filename)

    def save_phase(self, filename: str | Path) -> None:
        path = Path(filename)
        if path.suffix != ".npy":
            path = path.with_suffix(path.suffix + ".npy") if path.suffix else path.with_suffix(".npy")
        np.save(path, self.array)

    def __add__(self, other: "PhaseMask" | npt.ArrayLike | float) -> "PhaseMask":
        if isinstance(other, PhaseMask):
            self._check_compatible(other)
            bounds = self.region_bounds if self.region_bounds == other.region_bounds else None
            return PhaseMask(self.array + other.array, self.geometry, region_bounds=bounds)
        return PhaseMask(self.array + np.asarray(other), self.geometry, region_bounds=self.region_bounds)

    def __radd__(self, other: "PhaseMask" | npt.ArrayLike | float) -> "PhaseMask":
        return self.__add__(other)

    def __sub__(self, other: "PhaseMask" | npt.ArrayLike | float) -> "PhaseMask":
        if isinstance(other, PhaseMask):
            self._check_compatible(other)
            return PhaseMask(self.array - other.array, self.geometry, region_bounds=self.region_bounds)
        return PhaseMask(self.array - np.asarray(other), self.geometry, region_bounds=self.region_bounds)

    def __mul__(self, scalar: float) -> "PhaseMask":
        return PhaseMask(self.array * float(scalar), self.geometry, region_bounds=self.region_bounds)

    def __rmul__(self, scalar: float) -> "PhaseMask":
        return self.__mul__(scalar)

    def __neg__(self) -> "PhaseMask":
        return PhaseMask(-self.array, self.geometry, region_bounds=self.region_bounds)

    def _check_compatible(self, other: "PhaseMask") -> None:
        if self.geometry is not other.geometry:
            raise ValueError("Phase masks must belong to the same SLM geometry.")

    def _active_region(self) -> "PhaseRegion":
        return PhaseRegion(self.geometry, self.region_bounds)

    def flat(self, phase: float = 0.0) -> "PhaseMask":
        """Add a flat phase layer over this mask's active region."""

        return self + self._active_region().flat(phase)

    def lens(
        self,
        f: float | tuple[float, float] = np.inf,
        center: tuple[float, float] | None = None,
    ) -> "PhaseMask":
        """Add a lens phase over this mask's active region."""

        return self + self._active_region().lens(f, center)

    def binary(self, period: float | tuple[float, float] = 0) -> "PhaseMask":
        """Add a binary phase grating over this mask's active region."""

        return self + self._active_region().binary(period)

    def spiral(self, order: int = 1, center: tuple[float, float] | None = None) -> "PhaseMask":
        """Add a spiral phase over this mask's active region."""

        return self + self._active_region().spiral(order, center)

    def blaze(self, angle: float | tuple[float, float] = 0.0) -> "PhaseMask":
        """Add a blaze phase over this mask's active region."""

        return self + self._active_region().blaze(angle)

    def zernike(
        self,
        index: int,
        radius: float | tuple[float, float],
        weight: float = 1.0,
        center: tuple[float, float] | None = None,
    ) -> "PhaseMask":
        """Add a Zernike phase over this mask's active region."""

        return self + self._active_region().zernike(index, radius, weight, center)


class PhaseRegion(PhaseMask):
    """An empty SLM-sized phase mask constrained to a rectangular region."""

    def __init__(self, geometry: "SLMGeometry", bounds: Bounds | None = None):
        bounds = bounds or (0, geometry.resolution[0], 0, geometry.resolution[1])
        _validate_bounds(bounds, geometry.resolution)
        super().__init__(np.zeros(geometry.shape, dtype=np.float64), geometry, region_bounds=bounds)
        self.bounds = bounds

    @property
    def width(self) -> int:
        return self.bounds[1] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[2]

    def partition(
        self,
        axis: str,
        ratios: Sequence[float],
    ) -> tuple["PhaseRegion", ...]:
        if len(ratios) < 2 or any(float(ratio) <= 0 for ratio in ratios):
            raise ValueError("partition() needs at least two positive ratios.")
        axis = axis.lower()
        if axis not in {"x", "y"}:
            raise ValueError("axis must be 'x' or 'y'.")
        total = float(sum(ratios))
        start = self.bounds[0] if axis == "x" else self.bounds[2]
        stop = self.bounds[1] if axis == "x" else self.bounds[3]
        length = stop - start
        edges = [start]
        cumulative = 0.0
        for ratio in ratios[:-1]:
            cumulative += float(ratio)
            edges.append(start + round(length * cumulative / total))
        edges.append(stop)
        regions: list[PhaseRegion] = []
        for left_edge, right_edge in zip(edges[:-1], edges[1:]):
            if axis == "x":
                bounds = (left_edge, right_edge, self.bounds[2], self.bounds[3])
            else:
                bounds = (self.bounds[0], self.bounds[1], left_edge, right_edge)
            regions.append(PhaseRegion(self.geometry, bounds))
        return tuple(regions)

    def compose(self, *masks: PhaseMask) -> PhaseMask:
        """Merge masks generated for this region into one full-size phase mask."""

        result = np.zeros(self.geometry.shape, dtype=np.float64)
        used: list[Bounds] = []
        for mask in masks:
            if not isinstance(mask, PhaseMask):
                raise TypeError("compose() accepts PhaseMask instances.")
            self._check_compatible(mask)
            bounds = mask.region_bounds
            if bounds is not None:
                if not _contains(self.bounds, bounds):
                    raise ValueError(f"Mask region {bounds} is outside canvas region {self.bounds}.")
                for previous in used:
                    if _intersection(previous, bounds):
                        raise ValueError(f"Phase regions overlap: {previous} and {bounds}.")
                used.append(bounds)
            result += mask.array
        return PhaseMask(result, self.geometry)

    def flat(self, phase: float = 0.0) -> PhaseMask:
        return PhaseMask(basic.flat(self.geometry.shape, self.bounds, phase), self.geometry, region_bounds=self.bounds)

    def lens(
        self,
        f: float | tuple[float, float] = np.inf,
        center: tuple[float, float] | None = None,
    ) -> PhaseMask:
        return PhaseMask(
            basic.lens(self.geometry.shape, self.bounds, self.geometry.pitch_um, self.geometry.wavelength, f, center),
            self.geometry,
            region_bounds=self.bounds,
        )

    def binary(self, period: float | tuple[float, float] = 0) -> PhaseMask:
        from qtools.slm.phase import basic as basic_module

        return PhaseMask(
            basic_module.binary(self.geometry.shape, self.bounds, period),
            self.geometry,
            region_bounds=self.bounds,
        )

    def spiral(self, order: int = 1, center: tuple[float, float] | None = None) -> PhaseMask:
        return PhaseMask(
            spiral_module.spiral(self.geometry.shape, self.bounds, order, center),
            self.geometry,
            region_bounds=self.bounds,
        )

    def blaze(self, angle: float | tuple[float, float] = 0.0) -> PhaseMask:
        return PhaseMask(
            blaze_module.blaze(
                self.geometry.shape,
                self.bounds,
                self.geometry.pitch_um,
                self.geometry.wavelength,
                angle,
            ),
            self.geometry,
            region_bounds=self.bounds,
        )

    def zernike(
        self,
        index: int,
        radius: float | tuple[float, float],
        weight: float = 1.0,
        center: tuple[float, float] | None = None,
    ) -> PhaseMask:
        return PhaseMask(
            zernike_module.zernike(self.geometry.shape, self.bounds, index, radius, weight, center),
            self.geometry,
            region_bounds=self.bounds,
        )


def _validate_bounds(bounds: Bounds, resolution: tuple[int, int]) -> None:
    left, right, top, bottom = (int(value) for value in bounds)
    width, height = resolution
    if not (0 <= left <= right <= width and 0 <= top <= bottom <= height):
        raise ValueError(f"Invalid bounds {bounds} for resolution {resolution}.")
    if left == right or top == bottom:
        raise ValueError("A phase region cannot have zero area.")


__all__ = ["Bounds", "PhaseMask", "PhaseRegion"]
