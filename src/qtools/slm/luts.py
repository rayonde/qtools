"""Holoeye LUT encoding, decoding, validation, and generation."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import numpy.typing as npt


def _count_set_bits(value: int) -> int:
    return int(value).bit_count()


def _groups_to_multipliers(values: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    return np.asarray([_count_set_bits(int(value)) for value in values], dtype=np.uint16)


def _multipliers_to_groups(values: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    return np.asarray([(1 << int(value)) - 1 for value in values], dtype=np.uint16)


def validate_lut(values: Sequence[int] | npt.NDArray[np.integer]) -> npt.NDArray[np.uint16]:
    """Validate and return a 256-entry LUT."""

    array = np.asarray(values)
    if array.ndim != 1 or len(array) != 256:
        raise ValueError("A Holoeye LUT must contain exactly 256 values.")
    if np.any(array < 0) or np.any(array > 255):
        raise ValueError("Holoeye LUT values must be in the range 0..255.")
    return array.astype(np.uint16, copy=True)


def generate_linear_lut() -> npt.NDArray[np.uint16]:
    return np.arange(256, dtype=np.uint16)


def read_lut(filename: str | Path) -> npt.NDArray[np.uint16]:
    """Read a Holoeye ``.lut`` file."""

    converters = {0: int, 1: lambda value: int(value, base=16)}
    data = np.loadtxt(filename, dtype=np.uint16, converters=converters, skiprows=5)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"Invalid LUT file: {filename}")
    _, encoded = data.T[:2]
    encoded = encoded.astype(np.uint16)
    groups = encoded >> 5
    multipliers = _groups_to_multipliers(groups)
    values = (encoded & 0x1F) + multipliers * 0x20
    return validate_lut(values)


def write_lut(filename: str | Path, values: Sequence[int] | npt.NDArray[np.integer]) -> None:
    """Write a 256-entry array in Holoeye ``.lut`` format."""

    array = validate_lut(values)
    multipliers = array // 0x20
    groups = _multipliers_to_groups(multipliers)
    encoded = (array & 0x1F) + (groups << 5)
    header = "# Colors (leave fixed for now)\r\n0 1 2\r\n# Points (leave fixed for now)\r\n256\r\n# \r\n"
    with open(filename, "w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        for index, value in enumerate(encoded):
            handle.write(f"{index}  0x{int(value):04X}\r\n")
        handle.write("\r\n")


__all__ = ["generate_linear_lut", "read_lut", "validate_lut", "write_lut"]
