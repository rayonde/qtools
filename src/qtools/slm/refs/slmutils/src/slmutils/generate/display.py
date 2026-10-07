import typing
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Union

import imageio.v3 as iio
import numpy as np
import numpy.typing as npt

from slmutils.generate.utils import EMPTY_WINDOW, resolve_bounds
from slmutils.typing import DisplayMaskArray, Integer, PathLike, Real
from slmutils.utils import show_image

if TYPE_CHECKING:
    from slmutils.generate.phase import PhaseMask


SUPPORTED_EXTENSIONS = (".png", ".bmp", ".gif", ".tiff")


class DisplayMask:
    """Represents a display to be passed directly to an SLM."""

    def __init__(
        self,
        input: Union["PhaseMask", "DisplayMask", npt.NDArray, PathLike, tuple[Integer, Integer]],
    ):
        """Creates a display mask.

        Args:
            input:
                PhaseMask, or DisplayMask, or array, or shape,
                or filepath to a saved display mask.
        """
        if isinstance(input, PathLike):
            array = iio.imread(input)
            if not np.issubdtype(array.dtype, np.uint8):
                warnings.warn(
                    "Image was not originally 8-bit grayscale, and will be "
                    "compressed into 8-bit grayscale."
                )
        elif isinstance(input, typing.Sequence):
            array = np.zeros(input[::-1], dtype=np.uint8)  # use standardized "Width x Height"
        elif isinstance(input, np.ndarray) or isinstance(input, DisplayMask):
            array = DisplayMask.asarray(input)
        else:  # PhaseMask
            array = input.to_display().array
        self.array: DisplayMaskArray = np.asarray(array, dtype=np.uint8)

    @staticmethod
    def asarray(array: Union["DisplayMask", npt.NDArray]) -> DisplayMaskArray:
        """Coerce into a display mask array."""
        if isinstance(array, DisplayMask):
            array = array.array.copy()
        else:
            array = array.copy()
        return np.asarray(array, dtype=np.uint8)

    def show(self):
        """Shows display mask using OS default image viewer."""
        show_image(self.array)

    def save(self, filename: PathLike):
        """Saves display mask as an image file."""
        if Path(filename).suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"File extension must be one of {SUPPORTED_EXTENSIONS}")
        iio.imwrite(filename, self.array)

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
        background: Integer = 0,
    ):
        """Crops display mask, with background fill.

        Args:
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
            background: Fill gray level.
        """
        window = (left, right, top, bottom)
        left, right, top, bottom = resolve_bounds(*window, self.array)
        base = np.ones_like(self.array, dtype=np.uint8) * np.uint8(background)
        base[top:bottom, left:right] = self.array[top:bottom, left:right]
        return DisplayMask(base)

    def add(
        self,
        display: Union["DisplayMask", npt.NDArray],
        left: Integer | None = None,
        right: Integer | None = None,
        top: Integer | None = None,
        bottom: Integer | None = None,
    ):
        """Adds display mask within optional window.

        Args:
            display: Mask or array to add.
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
        """
        mask = DisplayMask.asarray(display)
        window = (left, right, top, bottom)
        if window == EMPTY_WINDOW:
            return DisplayMask(self.array + mask)

        left, right, top, bottom = resolve_bounds(*window, mask)
        base = DisplayMask.asarray(self)
        base[top:bottom, left:right] += mask[top:bottom, left:right]
        return DisplayMask(base)

    def replace(
        self,
        display: Union["DisplayMask", npt.NDArray],
        left: Integer | None = None,
        right: Integer | None = None,
        top: Integer | None = None,
        bottom: Integer | None = None,
    ):
        """Overwrites display mask within optional window.

        Args:
            display: Mask or array to add.
            left: Index of window left edge.
            right: Index of window right edge (excluded).
            top: Index of window top edge.
            bottom: Index of window bottom edge (excluded).
        """
        display = DisplayMask.asarray(display)
        window = (left, right, top, bottom)
        if window == EMPTY_WINDOW:
            return DisplayMask(display)

        left, right, top, bottom = resolve_bounds(*window, display)
        base = DisplayMask.asarray(self)
        base[top:bottom, left:right] = display[top:bottom, left:right]
        return DisplayMask(base)

    def shift(self, x: Integer = 0, y: Integer = 0, *, background: Integer = 0):
        """Translates mask by (x, y), with background fill.

        Args:
            x: Number of indices to shift mask along x-axis.
            y: Number of indices to shift mask along y-axis.
            background: Fill gray level.
        """
        display = DisplayMask.asarray(self)
        if y > 0:
            display[y:] = display[:-y]
            display[:y] = background
        elif y < 0:
            display[:y] = display[-y:]
            display[y:] = background
        if x > 0:
            display[x:] = display[:-x]
            display[:x] = background
        elif x < 0:
            display[:x] = display[-x:]
            display[x:] = background
        return DisplayMask(display)

    def flip(self):
        """Flips mask left-right."""
        display = np.flip(DisplayMask.asarray(self))
        return DisplayMask(display)

    def __add__(self, display):
        return self.add(display)

    def __radd__(self, display):
        return self.add(display)

    def __iadd__(self, display):
        return self.add(display)

    ###############
    #  FUNCTIONS  #
    ###############

    def flat(self, level: Integer = 0) -> "DisplayMask":
        """Creates a flat level layer.

        Args:
            level: Gray level.
        """
        display = np.ones_like(self.array) * level
        return DisplayMask(display)

    def circle(
        self,
        level: Integer,
        radius: Real,
        x: Real | None = None,
        y: Real | None = None,
    ) -> "DisplayMask":
        """Draws a flat circle on current mask.

        If no coordinates provided, draws a circle in the center.

        Args:
            level: Gray level.
            radius: Circle radius.
            x: Circle center x-coordinate, in pixel units.
            y: Circle center y-coordinate, in pixel units.
        """
        height, width = self.array.shape
        xs = np.arange(width)
        ys = np.arange(height)
        xx, yy = np.meshgrid(xs, ys)

        if x is None:
            xx -= width // 2
        else:
            xx = xx - x
        if y is None:
            yy -= height // 2
        else:
            yy = yy - y

        rr = (xx**2 + yy**2) ** 0.5
        display = np.where(rr < radius, level, self.array)
        return DisplayMask(display)

    def binary(
        self,
        period: Integer | tuple[Integer, Integer] = 0,
        *,
        level1: Integer = 0,
        level2: Integer = 128,
    ) -> "DisplayMask":
        """Creates a binary grating with (level1, level2) values.

        If 'period' is a scalar value, it is assumed to be along x-axis.

        Note that supplying a tuple for 'period' creates a checkerboard pattern,
        and not an angled binary grating. Use PhaseMask.binary() for the latter.

        Args:
            period: Binary grating period, in pixel units.
        """
        if not isinstance(period, typing.Sequence):
            vector = (period, 0)
        else:
            vector = period

        x, y = vector
        if x % 2 != 0 or y % 2 != 0:
            raise NotImplementedError("Only even periods currently supported.")

        # xy-case
        height, width = self.array.shape
        match vector:
            case (0, 0):
                return self.flat(level1)
            case (x, 0):
                hx = x // 2
                tile = np.array([level1] * hx + [level2] * hx, dtype=np.uint8)
                array = np.tile(tile, (height, (width - 1) // x + 1))
                return DisplayMask(array[:, :width])
            case (0, y):
                hy = y // 2
                tile = np.array([level1] * hy + [level2] * hy, dtype=np.uint8)[:, np.newaxis]
                array = np.tile(tile, ((height - 1) // y + 1, width))
                return DisplayMask(array[:height, :])
            case (x, y):
                hx = x // 2
                hy = y // 2
                tile = np.array([level1] * hx + [level2] * hx, dtype=np.uint8)
                rtile = np.flip(tile)
                supertile = np.array([tile] * hy + [rtile] * hy)
                array = np.tile(supertile, ((height - 1) // y + 1, (width - 1) // x + 1))
                return DisplayMask(array[:height, :width])

    def random(self) -> "DisplayMask":
        """Creates a random display mask."""
        display = np.random.randint(low=0, high=256, size=self.array.shape)
        return DisplayMask(display)
