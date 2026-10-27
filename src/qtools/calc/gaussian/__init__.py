"""Gaussian beam analysis: fit arrays/RAW/images without camera dependencies.

Example: result = fit(frame, pixel_size=3.75, unit="um")
Beam parameters are in pixels; result.to_dict() applies the physical scale.
"""

from ._fit import find_beam_centers, fit
from ._io import read_image, read_raw
from ._models import BeamParameters, GaussianFitResult, gauss_flat, gaussian2d
from ._profile import Profile

__all__ = [
    "BeamParameters",
    "GaussianFitResult",
    "Profile",
    "find_beam_centers",
    "fit",
    "gauss_flat",
    "gaussian2d",
    "plot",
    "read_image",
    "read_raw",
]


def plot(result, *, show=False):
    """Plot a fit result, importing matplotlib only when requested."""
    from ._plot import plot as plot_result

    return plot_result(result, show=show)
