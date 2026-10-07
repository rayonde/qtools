#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "imageio>=2.37.3",
#     "pillow>=12.3.0",
#     "numpy>=2.5.1",
#     "slmsuite>=0.4.1",
# ]
# ///
"""Creates SLM phase masks.

Currently does not assist with loading phase data from wavefront calibration - if needed,
please do it manually :)

Changelog:
    2026-07-05, Justin: Init
    2026-07-08, Justin: Drop requirement to Python 3.10+ for compatibility with pyspin

Note:
    Currently relies on slmsuite to bootstrap certain functionality, including
    phase -> gray level conversions. This requirement can also be removed by reimplementing
    some of the functionality.
"""

import typing

import numpy as np
import numpy.typing as npt

from slmutils.generate.display import DisplayMask
from slmutils.generate.phase import PhaseMask
from slmutils.generate.utils import AbstractGenericSLM
from slmutils.typing import Float, Integer, Real, T


class GenericSLM(AbstractGenericSLM):
    RESOLUTION = (32, 32)
    PITCH_UM: float = 10
    BITDEPTH: int = 8

    def __init__(self, wl: Float, gray_range: Integer | None = None):
        """Initializes SLM wrapper for phase mask generation.

        'gray_range' does not need to be defined if the SLM's LUT can be redefined
        such that the maximum bit depth corresponds to 2pi phase shift. Set 'gray_range'
        to the calibrated gray level otherwise (which automatically sets the correct
        fraction calculated in slmsuite).

        The initial phase array is zeroed, except when 'gray_range' is defined.

        Args:
            wl: Target wavelength, in units of [m].
            gray_range: Gray level width associated with 2pi phase.

        Note:
            self.slm.phase is in normalized units of x/wl, i.e. an additional factor of
            1/wav_um is applied to the xx/yy meshgrid.
        """
        from slmsuite.hardware.slms.simulated import SimulatedSLM

        wav_um = wl * 1e6
        kwargs = {}
        if gray_range is not None:
            ratio = gray_range / (1 << self.BITDEPTH)
            wav_design_um = wav_um / ratio
            kwargs["wav_design_um"] = wav_design_um

        self.slm = SimulatedSLM(
            resolution=self.RESOLUTION,
            pitch_um=self.PITCH_UM,
            bitdepth=self.BITDEPTH,
            wav_um=wav_um,
            **kwargs,
        )
        self.gray_range = gray_range
        self.wl = wl
        self.xpitch = self.slm.pitch_um[0] * 1e-6
        self.ypitch = self.slm.pitch_um[1] * 1e-6

    def to_phase(self) -> PhaseMask:
        """Syntactic sugar to generate a fresh PhaseMask from associated SLM."""
        return PhaseMask(self)

    def get_device(self):
        return self.slm

    def phase2display(self, phase: PhaseMask | npt.NDArray) -> DisplayMask:
        """Converts phase value to logical gray level on SLM."""
        phase = PhaseMask.asarray(phase)
        self.slm.set_phase(phase)
        array = np.asarray(self.slm.display, dtype=np.uint8)
        return DisplayMask(array)

    @property
    def _identity_attributes(self):
        """Solely for equality and hashing comparisons."""
        return (self.RESOLUTION, self.PITCH_UM, self.BITDEPTH, self.gray_range, self.wl)

    def __eq__(self, other):
        if not isinstance(other, GenericSLM):
            return False
        return all(
            [(a == b) for a, b in zip(self._identity_attributes, other._identity_attributes)]
        )

    def __hash__(self):
        return hash(self._identity_attributes)

    @staticmethod
    def _unwrap_xy(value: T | tuple[T, T]) -> tuple[T, T]:
        """Convenience function for unpacking scalar/2-tuple."""
        if not isinstance(value, typing.Sequence):
            return (value, value)
        if len(value) == 1:
            return (value[0], value[0])
        if len(value) != 2:
            raise ValueError("Missing 2-tuple.")
        return typing.cast(tuple[T, T], value)

    @staticmethod
    def _unwrap_x0(value: T | tuple[T, T]) -> tuple[T, T]:
        """Convenience function for unpacking scalar/2-tuple, with default 0."""
        if not isinstance(value, typing.Sequence):
            return (value, type(value)())
        if len(value) == 1:
            return (value[0], type(value[0])())
        if len(value) != 2:
            raise ValueError("Missing 2-tuple.")
        return typing.cast(tuple[T, T], value)

    ###############
    #  FUNCTIONS  #
    ###############

    def flat(self, phase: Real = 0) -> PhaseMask:
        """Creates a flat phase layer.

        Args:
            phase: In units of radians.
        """
        phase_ = np.ones_like(self.slm.phase) * phase
        return PhaseMask(phase_, self)

    def blaze(self, angle: Real | tuple[Real, Real] = 0) -> PhaseMask:
        """Creates a blaze grating.

        'angle' represents the blaze angle, resulting in a reflection along twice the angle.
        No grating is created when angle = 0.

        Args:
            angle: Scalar value for blaze angle, in [deg], or 2-tuple (x-angle, y-angle).
        """
        import slmsuite.holography.toolbox.phase as analytic
        from slmsuite.holography import toolbox

        # Assume to be x-angle only if scalar
        vector = GenericSLM._unwrap_x0(angle)
        vector = toolbox.convert_vector(vector, from_units="deg")
        phase = analytic.blaze(self.slm, vector=vector)
        return PhaseMask(phase, self)

    def binary(self, period: Real | tuple[Real, Real] = 0) -> PhaseMask:
        """Creates a binary grating with (0, pi) values.

        No grating is created when period = 0.

        Args:
            width: Scalar value for period, in pixel units, or 2-tuple (x-period, y-period).
        Note:
            Consider implementing a 'fill' or 'duty_factor' argument.
        """
        import slmsuite.holography.toolbox.phase as analytic

        # Assume to be x-period only if scalar
        vector = GenericSLM._unwrap_x0(period)
        phase = analytic.binary(self.slm, vector)  # pyright: ignore[reportArgumentType]
        return PhaseMask(phase, self)

    def lens(
        self, f: Real | tuple[Real, Real] = np.inf, x: Real | None = None, y: Real | None = None
    ) -> PhaseMask:
        """Creates a lens phase mask.

        Similar to 'slmsuite.holography.toolbox.phase.lens', but with additional (x, y)
        centering functionality. Supply 'f' > 0 for a converging lens, and 'f' < 0 for diverging
        lens.

        Args:
            f: Scalar value for isotropic lens, in [m], or 2-tuple (x-focal, y-focal).
            x: Lens center x-coordinate, in pixel units.
            y: Lens center y-coordinate, in pixel units.
        """
        xf, yf = GenericSLM._unwrap_xy(f)
        fs = np.array([xf, yf]) / self.wl  # normalized units

        xx, yy = self.slm.grid
        if x is not None:
            x -= self.RESOLUTION[0] // 2
            xx = xx - x / (self.wl / self.xpitch)
        if y is not None:
            y -= self.RESOLUTION[1] // 2
            yy = yy - y / (self.wl / self.ypitch)
        phase = np.pi * (xx**2 / fs[0] + yy**2 / fs[1])
        return PhaseMask(phase, self)

    def spiral(self, order: Integer = 1, x: Real | None = None, y: Real | None = None) -> PhaseMask:
        """Creates a spiral phase mask.

        'order' > 0 for right-circular phase mask, and 'order' < 0 for left-circular.

        Args:
            order: Topological charge.
            x: Lens center x-coordinate, in pixel units.
            y: Lens center y-coordinate, in pixel units.
        """
        xx, yy = self.slm.grid
        if x is not None:
            x -= self.RESOLUTION[0] // 2
            xx = xx - x / (self.wl / self.xpitch)
        if y is not None:
            y -= self.RESOLUTION[1] // 2
            yy = yy - y / (self.wl / self.ypitch)
        phase = -order * np.arctan2(xx, yy)
        return PhaseMask(phase, self)

    def zernike(
        self,
        index: Integer,
        r: Real | tuple[Real, Real],
        w: Real = 1,
        x: Real | None = None,
        y: Real | None = None,
    ) -> PhaseMask:
        """Creates a Zernike polynomial of ANSI index and pixel radius.

        Similar to 'slmsuite.holography.toolbox.phase.zernike', but with additional (x, y)
        centering functionality. Outside the circle radius, the phase is zeroed to avoid the
        Zernike polynomial blowing up. Values are scaled to the canonical [-1, 1].

        Args:
            index: ANSI index of the Zernike polynomial, see [1] for visualization.
            r: Scalar value for isotropic radius, in pixel units, or 2-tuple (x-radius, y-radius).
            x: Lens center x-coordinate, in pixel units.
            y: Lens center y-coordinate, in pixel units.

        References:
            [1]: <https://slmsuite.readthedocs.io/en/latest/_examples/zernike_holography.html>
        """
        import slmsuite.holography.toolbox.phase as analytic

        xr, yr = GenericSLM._unwrap_xy(r)
        aperture = (1 / xr * (self.wl / self.xpitch), 1 / yr * (self.wl / self.ypitch))

        xx, yy = self.slm.grid
        if x is not None:
            x -= self.RESOLUTION[0] // 2
            xx = xx - x / (self.wl / self.xpitch)
        if y is not None:
            y -= self.RESOLUTION[1] // 2
            yy = yy - y / (self.wl / self.ypitch)

        phase = analytic.zernike_sum(
            grid=(xx, yy), indices=(int(index),), weights=(w,), aperture=aperture
        )
        return PhaseMask(phase, self)

    def random(self) -> PhaseMask:
        """Creates a random phase mask."""
        phase = np.random.random(self.slm.phase.shape) * 2 * np.pi
        return PhaseMask(phase, self)


# SLM definitions
class HoloeyeLETO(GenericSLM):
    RESOLUTION = (1920, 1080)
    PITCH_UM: float = 6.4
    BITDEPTH: int = 8


if __name__ == "__main__":
    slm = HoloeyeLETO(532e-9)  # 1920x1080
    beam1_xy = (470, 500)
    beam2_xy = (1440, 600)

    # Create a split phase mask
    pm1 = (
        PhaseMask(slm)
        .binary(40)
        .binary((0, 40))  # ...checkboard
        .lens(2, *beam1_xy)  # 2m focusing
        .spiral(1, *beam1_xy)  # l=+1
        .flat(np.pi)  # invert
    )
    pm2 = (
        PhaseMask(slm)
        .blaze(0.2)  # 0.2 deg blaze
        .spiral(-1, *beam2_xy)  # l=-1
    )
    pm = pm1.replace(pm2, 960, 1920, 0, 1080)
    pm.save("phase_example.png")
    pm.show()
