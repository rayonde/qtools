"""Gaussian models and inspectable fit results. Coordinates are (x, y)."""

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np


def gaussian2d(x, y, amplitude, xo, yo, sigma_x, sigma_y, theta=0.0, offset=0.0):
    """Evaluate a rotated Gaussian; sigma is standard deviation, theta is radians."""
    if sigma_x <= 0 or sigma_y <= 0:
        raise ValueError("Gaussian widths must be positive.")
    dx, dy = np.asarray(x) - xo, np.asarray(y) - yo
    cosine, sine = np.cos(theta), np.sin(theta)
    u, v = cosine * dx + sine * dy, -sine * dx + cosine * dy
    return offset + amplitude * np.exp(-0.5 * ((u / sigma_x) ** 2 + (v / sigma_y) ** 2))


def gauss_flat(x, amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
    """Legacy model accepting an (N, 2) array of (x, y) coordinates."""
    coordinates = np.asarray(x)
    return gaussian2d(
        coordinates[:, 0],
        coordinates[:, 1],
        amplitude,
        xo,
        yo,
        sigma_x,
        sigma_y,
        theta,
        offset,
    )


@dataclass(frozen=True)
class BeamParameters:
    """One beam: amplitude above background, positions/widths in pixels.

    For rotating fits sigma_x is the major-axis width and theta its angle
    from +x towards +y, in [-pi/2, pi/2). For fix_theta fits, axes stay x/y.
    """

    amplitude: float
    xo: float
    yo: float
    sigma_x: float
    sigma_y: float
    theta: float

    @property
    def center(self):
        return self.xo, self.yo

    @property
    def sigma(self):
        return self.sigma_x, self.sigma_y

    @property
    def waist(self):
        """1/e² intensity radii, in pixels."""
        return 2 * self.sigma_x, 2 * self.sigma_y

    @property
    def fwhm(self):
        factor = 2 * np.sqrt(2 * np.log(2))
        return factor * self.sigma_x, factor * self.sigma_y

    @property
    def theta_deg(self):
        return float(np.degrees(self.theta))

    def evaluate(self, x, y):
        return gaussian2d(
            x,
            y,
            self.amplitude,
            self.xo,
            self.yo,
            self.sigma_x,
            self.sigma_y,
            self.theta,
        )


@dataclass(frozen=True)
class GaussianFitResult:
    """Shared result type for single/multiple beams; no GUI opens on fitting."""

    beams: tuple[BeamParameters, ...]
    offset: float
    data: np.ndarray = field(repr=False, compare=False)
    pixel_size: float
    unit: str
    success: bool
    message: str
    nfev: int
    sample_step: int

    @property
    def beam(self):
        if len(self.beams) != 1:
            raise ValueError("Use result.beams for a multi-beam fit.")
        return self.beams[0]

    @property
    def values(self):
        """Legacy parameter names, always in pixels/radians."""
        result = {"offset": self.offset}
        for i, beam in enumerate(self.beams):
            prefix = "" if len(self.beams) == 1 else f"beam{i}_"
            for name in ("amplitude", "xo", "yo", "sigma_x", "sigma_y", "theta"):
                result[prefix + name] = getattr(beam, name)
        return result

    def evaluate(self, x, y):
        result = np.full(np.broadcast_shapes(np.shape(x), np.shape(y)), self.offset)
        for beam in self.beams:
            result += beam.evaluate(x, y)
        return result

    @cached_property
    def fitted_image(self):
        y, x = np.ogrid[: self.data.shape[0], : self.data.shape[1]]
        result = self.evaluate(x, y)
        result.setflags(write=False)
        return result

    @property
    def best_fit(self):
        return self.fitted_image.ravel()

    @cached_property
    def residual(self):
        result = self.data - self.fitted_image
        result.setflags(write=False)
        return result

    @cached_property
    def rmse(self):
        return float(np.sqrt(np.mean(self.residual**2)))

    @cached_property
    def r_squared(self):
        total = np.sum((self.data - self.data.mean()) ** 2)
        return float(1 - np.sum(self.residual**2) / total)

    def to_dict(self):
        """JSON-ready summary, with lengths scaled by pixel_size in unit."""
        beams = []
        for beam in self.beams:
            beams.append(
                {
                    "amplitude": beam.amplitude,
                    "center": [value * self.pixel_size for value in beam.center],
                    "sigma": [value * self.pixel_size for value in beam.sigma],
                    "waist": [value * self.pixel_size for value in beam.waist],
                    "fwhm": [value * self.pixel_size for value in beam.fwhm],
                    "theta_deg": beam.theta_deg,
                }
            )
        return {
            "beams": beams,
            "offset": self.offset,
            "unit": self.unit,
            "pixel_size": self.pixel_size,
            "rmse": self.rmse,
            "r_squared": self.r_squared,
            "success": self.success,
            "message": self.message,
            "nfev": self.nfev,
            "sample_step": self.sample_step,
        }

    def plot(self, *, show=False):
        from ._plot import plot

        return plot(self, show=show)
