"""Image loading without camera SDKs or OpenCV."""

from math import isqrt
from operator import index
from os import PathLike
from pathlib import Path

import numpy as np


def validate_image(data):
    array = np.asarray(data)
    if array.ndim != 2 or min(array.shape, default=0) < 2:
        raise ValueError(
            "Expected a 2D grayscale image with at least two rows and columns."
        )
    if array.dtype.kind not in "buif" or not np.isfinite(array).all():
        raise ValueError("Image must contain finite, real numeric values.")
    return array


def read_raw(filename, *, shape=None, bit_depth=8):
    """Read headerless 8-bit or little-endian 16-bit RAW data.

    shape is (height, width). Without it, only an exact 4:3 image is
    inferred, preserving the original camera-file convention.
    """
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth must be 8 or 16.")
    dtype = np.dtype("u1" if bit_depth == 8 else "<u2")
    path = Path(filename)
    size = path.stat().st_size
    if size == 0 or size % dtype.itemsize:
        raise ValueError("RAW byte count does not match the selected bit depth.")
    count = size // dtype.itemsize
    if shape is None:
        scale = isqrt(count // 12)
        if scale == 0 or 12 * scale * scale != count:
            raise ValueError("Cannot infer RAW dimensions; pass shape=(height, width).")
        shape = (3 * scale, 4 * scale)
    try:
        height, width = (index(value) for value in shape)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "shape must contain two positive integers (height, width)."
        ) from error
    if height < 2 or width < 2 or height * width != count:
        raise ValueError("RAW sample count does not match shape=(height, width).")
    return np.fromfile(path, dtype=dtype).reshape(height, width)


def read_image(source, *, shape=None, bit_depth=8):
    """Read an array, RAW file, or Pillow-supported image. RGB files use luminance."""
    if isinstance(source, (str, PathLike)):
        path = Path(source)
        if path.suffix.lower() in {".raw", ".bin"}:
            data = read_raw(path, shape=shape, bit_depth=bit_depth)
        else:
            from PIL import Image

            with Image.open(path) as image:
                if image.mode in {"RGB", "RGBA", "P", "CMYK", "LA"}:
                    image = image.convert("RGB").convert("F")
                data = np.array(image)
    else:
        data = np.asarray(source)
    return validate_image(data)
