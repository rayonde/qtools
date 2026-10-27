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
    rendered = Image.fromarray(image)
    # IPython display keeps the image inline in Jupyter.  In a regular Python
    # process PIL falls back to the platform image viewer.
    try:
        from IPython import get_ipython

        shell = get_ipython()
        in_notebook = shell is not None and (
            "IPKernelApp" in getattr(shell, "config", {})
            or shell.__class__.__name__ == "ZMQInteractiveShell"
        )
    except ImportError:
        in_notebook = False
    if in_notebook:
        from IPython.display import display

        display(rendered)
    else:
        rendered.show()


def save_image(array: npt.NDArray, filename: str | Path, *, rescale: bool = False) -> None:
    image = np.asarray(array)
    if rescale:
        low, high = float(image.min()), float(image.max())
        image = np.zeros_like(image, dtype=np.uint8) if high <= low else (
            (image - low) / (high - low) * 255
        ).round().astype(np.uint8)
    iio.imwrite(filename, image)


__all__ = ["save_image", "show_image"]
