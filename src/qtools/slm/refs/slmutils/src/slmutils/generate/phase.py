import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Union

import numpy as np
import numpy.typing as npt

from slmutils.generate.utils import EMPTY_WINDOW, AbstractGenericSLM, resolve_bounds
from slmutils.typing import Integer, PathLike, Real

if TYPE_CHECKING:
    from slmutils.generate.display import DisplayMask


class PhaseMask:
    """Syntactic sugar for manipulating phase masks."""

    def __init__(
        self,
        input: Union[AbstractGenericSLM, "PhaseMask", npt.NDArray, PathLike],
        slm: AbstractGenericSLM | None = None,
    ):
        """Initializes a new phase mask.

        If 'input' is an SLM itself, this will be conveniently stored within the class,
        so that 'PhaseMask.save' can be directly called without needing another reference to
        the slm instance. This can also be alternatively overridden using the direct 'slm'
        argument.

        Note if SLM is passed as an array, the phase itself will be zeroed. This prevents any
        accidental residual SLM phase from carrying over across multiple PhaseMask creations.

        Unlike DisplayMask, the constructor does not accept a shape (M, N) as input, since it
        is expected to take the form of an SLM input instead which already has an in-built shape.
        """
        self.slm: AbstractGenericSLM | None
        if isinstance(input, PathLike):
            self.array = np.asarray(np.load(input), dtype=np.float64)
            self.slm = slm
        elif isinstance(input, AbstractGenericSLM):
            self.array = np.zeros_like(input.get_device().phase)
            self.slm = input
        else:
            self.array = PhaseMask.asarray(input)
            self.slm = slm if slm is not None else self._retrieve_slm(input)

    @staticmethod
    def asarray(array: Union["PhaseMask", npt.NDArray]) -> npt.NDArray:
        if isinstance(array, PhaseMask):
            array = array.array.copy()
        else:
            array = array.copy()
        return np.asarray(array, dtype=np.float64)

    def _retrieve_slm(self, array: Union["PhaseMask", npt.NDArray]) -> AbstractGenericSLM | None:
        """Propagate embedded SLMs from either self or provided array (binary inputs)."""
        if isinstance(array, np.ndarray):
            return self.slm
        assert isinstance(array, PhaseMask)
        if not hasattr(self, "slm"):  # triggers during initialization
            return array.slm
        if self.slm is not None and array.slm is not None:
            if self.slm != array.slm:
                raise ValueError("Phase masks that belong to different SLMs cannot be added.")
            return self.slm
        return self.slm if self.slm is not None else array.slm

    def save_phase(self, filename: PathLike):
        filepath = Path(filename)
        if filepath.suffix != ".npy":
            filepath = filepath.with_name(filepath.name + ".npy")
            warnings.warn(f"Phase data saved as '{filepath.name}' instead.")
        np.save(filepath, self.array)

    ################
    #  TRANSFORMS  #
    ################

    def crop(
        self,
        left: Integer | None = None,
        right: Integer | None = None,
        top: Integer | None = None,
        bottom: Integer | None = None,
        *,
        background: Real = 0,
    ):
        """Crops phase mask, with background fill.

        Args:
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
            background: Fill phase level.
        """
        window = (left, right, top, bottom)
        left, right, top, bottom = resolve_bounds(*window, self.array)
        base = np.ones_like(self.array, np.float64) * background
        base[top:bottom, left:right] = self.array[top:bottom, left:right]
        return PhaseMask(base, self.slm)

    def add(
        self,
        phase: Union["PhaseMask", npt.NDArray],
        left: Integer | None = None,
        right: Integer | None = None,
        top: Integer | None = None,
        bottom: Integer | None = None,
    ):
        """Adds phase mask within optional window.

        Args:
            phase: Mask or array to add.
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
        """
        slm = self._retrieve_slm(phase)
        phase = PhaseMask.asarray(phase)
        window = (left, right, top, bottom)
        if window == EMPTY_WINDOW:
            return PhaseMask(self.array + phase, slm)

        left, right, top, bottom = resolve_bounds(*window, phase)
        base = self.array.copy()
        base[top:bottom, left:right] += phase[top:bottom, left:right]
        return PhaseMask(base, slm)

    def replace(
        self,
        phase: Union["PhaseMask", npt.NDArray],
        left: Integer | None = None,
        right: Integer | None = None,
        top: Integer | None = None,
        bottom: Integer | None = None,
    ):
        """Overwrites phase mask within optional window.

        Args:
            phase: Mask or array to add.
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
        """
        slm = self._retrieve_slm(phase)
        phase = PhaseMask.asarray(phase)
        window = (left, right, top, bottom)
        if window == EMPTY_WINDOW:
            return PhaseMask(phase, slm)

        left, right, top, bottom = resolve_bounds(*window, phase)
        base = self.array.copy()
        base[top:bottom, left:right] = phase[top:bottom, left:right]
        return PhaseMask(base, slm)

    def shift(self, x: Integer = 0, y: Integer = 0, *, background: Real = 0):
        """Translates mask by (x, y), with background fill.

        Args:
            x: Number of indices to shift mask along x-axis.
            y: Number of indices to shift mask along y-axis.
            background: Fill phase level.
        """
        phase = self.array.copy()
        if y > 0:
            phase[y:] = phase[:-y]
            phase[:y] = background
        elif y < 0:
            phase[:y] = phase[-y:]
            phase[y:] = background
        if x > 0:
            phase[x:] = phase[:-x]
            phase[:x] = background
        elif x < 0:
            phase[:x] = phase[-x:]
            phase[x:] = background
        return PhaseMask(phase, self.slm)

    def flip(self):
        """Flips mask left-right."""
        phase = np.flip(self.array)
        return PhaseMask(phase, self.slm)

    def __add__(self, phase):
        return self.add(phase)

    def __radd__(self, phase):
        return self.add(phase)

    def __iadd__(self, phase):
        return self.add(phase)

    def __getattr__(self, name: str):
        """
        Allows class to forward unknown methods to underlying np.ndarray
        without inheritance or redefining methods.
        """
        f = getattr(self.array, name)  # forward to array itself

        def wrap_phasemask(*args, **kwargs):
            result = f(*args, **kwargs)
            if isinstance(result, np.ndarray):
                return PhaseMask(result, self.slm)
            return result

        return wrap_phasemask

    ################
    #  DELEGATION  #
    ################

    # Defined here purely for the syntactic sugar...
    # These are convenience functions to support fluent API when manipulating
    # phase masks. Requires that the SLM class be passed to the PhaseMask at some
    # point, otherwise this method will raise a ValueError.

    @staticmethod
    def _assert_slm(f):
        fname = f.__name__
        if fname is None:
            fname = "<method>"

        def helper(self, *args, **kwargs):
            if self.slm is None:
                raise ValueError(
                    "SLM not stored in phase mask, so this cannot be called. "
                    "Either initialize the phase mask with 'PhaseMask(SLM(...))', "
                    f"or directly call 'SLM.{fname}(..., PhaseMask)'."
                )
            return f(self, *args, **kwargs)

        return helper

    @_assert_slm
    def flat(self, phase: Real = 0) -> "PhaseMask":
        """Creates a flat phase layer.

        Args:
            phase: Phase, in units of radians.
        """
        assert self.slm is not None
        pm = self.slm.flat(phase)
        return self.add(pm)

    @_assert_slm
    def blaze(self, angle: Real | tuple[Real, Real] = 0) -> "PhaseMask":
        """Creates a blaze grating.

        'angle' represents the blaze angle, resulting in a reflection along twice the angle.
        No grating is created when angle = 0.

        Args:
            angle: Scalar value for blaze angle, in [deg], or 2-tuple (x-angle, y-angle).
        """
        assert self.slm is not None
        pm = self.slm.blaze(angle)
        return self.add(pm)

    @_assert_slm
    def binary(self, period: Real | tuple[Real, Real] = 0) -> "PhaseMask":
        """Creates a binary grating with (0, pi) values.

        No grating is created when period = 0.

        Args:
            width: Scalar value for period, in pixel units, or 2-tuple (x-period, y-period).
        Note:
            Consider implementing a 'fill' or 'duty_factor' argument.
        """
        assert self.slm is not None
        pm = self.slm.binary(period)
        return self.add(pm)

    @_assert_slm
    def lens(
        self, f: Real | tuple[Real, Real] = np.inf, x: Real | None = None, y: Real | None = None
    ) -> "PhaseMask":
        """Creates a lens phase mask.

        Similar to 'slmsuite.holography.toolbox.phase.lens', but with additional (x, y)
        centering functionality. Supply 'f' > 0 for a converging lens, and 'f' < 0 for diverging
        lens.

        Args:
            f: Scalar value for isotropic lens, in [m], or 2-tuple (x-focal, y-focal).
            x: Lens center x-coordinate, in pixel units.
            y: Lens center y-coordinate, in pixel units.
        """
        assert self.slm is not None
        pm = self.slm.lens(f, x, y)
        return self.add(pm)

    @_assert_slm
    def spiral(
        self, order: Integer = 1, x: Real | None = None, y: Real | None = None
    ) -> "PhaseMask":
        """Creates a spiral phase mask.

        'order' > 0 for right-circular phase mask, and 'order' < 0 for left-circular.

        Args:
            order: Topological charge.
            x: Lens center x-coordinate, in pixel units.
            y: Lens center y-coordinate, in pixel units.
        """
        assert self.slm is not None
        pm = self.slm.spiral(order, x, y)
        return self.add(pm)

    @_assert_slm
    def random(self) -> "PhaseMask":
        """Creates a random phase mask."""
        assert self.slm is not None
        pm = self.slm.random()
        return self.add(pm)

    @_assert_slm
    def to_display(self) -> "DisplayMask":
        assert self.slm is not None
        return self.slm.phase2display(self)

    @_assert_slm
    def save(self, filename: PathLike):
        assert self.slm is not None
        self.slm.phase2display(self).save(filename)

    @_assert_slm
    def show(self):
        assert self.slm is not None
        self.slm.phase2display(self).show()
