import imageio.v3 as iio
import numpy as np
import numpy.typing as npt
from PIL import Image

from slmutils.typing import PathLike

# fmt: off
# For d=2 array
VALID_IMAGE_TYPES = (
    np.int8, np.uint8,  # 8-bit grayscale, equivalent representation
    np.uint16,  # 16-bit grayscale
    np.int16,  # 8-bit grayscale in 16-bit container
    np.int32, np.uint32,  # 8-bit grayscale in 32-bit container (32-bit RGBA otherwise)
    np.float32, np.float64,  # 12-bit grayscale in float container
)
# fmt: on


def show_image(array: npt.NDArray, rescale: bool = False):
    """Shows array image using OS default image viewer.

    Compatible array dtypes are:
    - 8-bit: uint8, int8, uint32, int32, int16
    - 12-bit: float32, float64
    - 16-bit: uint16

    Set 'rescale' to True to maximize dynamic range.
    """
    if rescale:
        min, max = np.min(array), np.max(array)
        array = (array - min) / (max - min)
        array = np.round(array * 255).astype(np.uint8)
    Image.fromarray(array).show()


def save_image(array: npt.NDArray, filename: PathLike, rescale: bool = False):
    """Shows array image using OS default image viewer.

    Compatible array dtypes are:
    - 8-bit: uint8, int8, uint32, int32, int16
    - 12-bit: float32, float64
    - 16-bit: uint16

    Set 'rescale' to True to maximize dynamic range.
    """
    if rescale:
        min, max = np.min(array), np.max(array)
        array = (array - min) / (max - min)
        array = np.round(array * 255).astype(np.uint8)
    iio.imwrite(filename, array)
