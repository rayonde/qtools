"""Small image and array utilities used by the SLM package."""

from __future__ import annotations

from pathlib import Path

import imageio.v3 as iio
import numpy as np
import numpy.typing as npt
from PIL import Image


def show_image(array: npt.NDArray, *, rescale: bool = False) -> None:
    image = np.asarray(array)
    if rescale:
        low, high = float(image.min()), float(image.max())
        image = np.zeros_like(image, dtype=np.uint8) if high <= low else (
            (image - low) / (high - low) * 255
        ).round().astype(np.uint8)
    Image.fromarray(image).show()


def save_image(array: npt.NDArray, filename: str | Path, *, rescale: bool = False) -> None:
    image = np.asarray(array)
    if rescale:
        low, high = float(image.min()), float(image.max())
        image = np.zeros_like(image, dtype=np.uint8) if high <= low else (
            (image - low) / (high - low) * 255
        ).round().astype(np.uint8)
    iio.imwrite(filename, image)


__all__ = ["save_image", "show_image"]
