"""Image container returned by :mod:`qtools.camera`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt

from qtools.camera.exceptions import CameraDependencyError


class CameraImage(np.ndarray):
    """A NumPy image with acquisition metadata and convenience I/O.

    ``CameraImage`` is an ``ndarray`` subclass, so existing code that expects a
    numeric matrix keeps working. It additionally provides ``info``, ``save``
    and ``show`` for the common single-frame workflow.
    """

    _IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"})

    def __new__(
        cls,
        data: npt.ArrayLike,
        *,
        info: Mapping[str, Any] | None = None,
    ) -> "CameraImage":
        image = np.asarray(data).view(cls)
        image._info = cls._normalize_info(info)
        return image

    def __array_finalize__(self, source: np.ndarray | None) -> None:
        if source is None:
            return
        self._info = dict(getattr(source, "_info", {}))

    @staticmethod
    def _normalize_info(info: Mapping[str, Any] | None) -> dict[str, Any]:
        normalized = dict(info or {})
        if "shape" in normalized:
            normalized["shape"] = tuple(int(value) for value in normalized["shape"])
        return normalized

    @property
    def info(self) -> dict[str, Any]:
        """Return a copy of the acquisition metadata."""

        return dict(self._info)

    def save(self, filename: str | Path, *, overwrite: bool = False) -> Path:
        """Save the image and return the final path.

        ``.npy`` and ``.npz`` store self-describing NumPy data, ``.raw``
        stores only the contiguous pixel bytes, and common image suffixes
        store a viewable image. For ``.raw``, use ``image.info["shape"]``
        and ``image.info["dtype"]`` to reconstruct the array.
        """

        path = Path(filename).expanduser()
        suffix = path.suffix.lower()
        supported = {".npy", ".npz", ".raw", *self._IMAGE_EXTENSIONS}
        if suffix not in supported:
            choices = ", ".join(sorted(supported))
            raise ValueError(f"Unsupported image suffix {suffix!r}; choose from: {choices}.")
        if path.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

        if suffix == ".raw":
            np.ascontiguousarray(self).tofile(path)
        elif suffix == ".npy":
            np.save(path, np.asarray(self))
        elif suffix == ".npz":
            np.savez_compressed(
                path,
                image=np.asarray(self),
                info=np.asarray(json.dumps(self._info, default=str, sort_keys=True)),
            )
        else:
            try:
                import imageio.v3 as iio
            except ImportError as exc:
                raise CameraDependencyError("Saving camera images requires imageio.") from exc
            data: npt.NDArray[np.generic]
            if suffix in {".tif", ".tiff"}:
                data = np.asarray(self)
            else:
                data = self.to_uint8()
            iio.imwrite(path, data)
        return path

    def show(self) -> None:
        """Display an 8-bit preview using Pillow's default viewer."""

        try:
            from PIL import Image
        except ImportError as exc:
            raise CameraDependencyError("CameraImage.show() requires Pillow.") from exc
        Image.fromarray(self.to_uint8()).show()

    def to_uint8(self) -> npt.NDArray[np.uint8]:
        """Convert the image to an 8-bit display representation."""

        return to_uint8(self, self._info.get("bitdepth"))


def to_uint8(
    image: npt.ArrayLike,
    bitdepth: int | None = None,
) -> npt.NDArray[np.uint8]:
    """Convert numeric camera data to an 8-bit preview array."""

    values = np.asarray(image)
    if values.dtype == np.uint8:
        return values
    if values.dtype.kind == "f":
        values = np.clip(values, 0, 1) * 255
    elif bitdepth is not None and bitdepth > 8:
        values = np.right_shift(values.astype(np.uint64), bitdepth - 8)
    else:
        max_value = float(np.max(values, initial=0))
        if max_value > 255:
            values = values / max_value * 255 if max_value else values
    return np.asarray(np.clip(values, 0, 255), dtype=np.uint8)


__all__ = ["CameraImage", "to_uint8"]
