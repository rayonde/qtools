"""Decode and encode lookup tables for Holoeye LETO-II (8-bit)."""

import numpy as np
import numpy.typing as npt

from slmutils.typing import Integer, PathLike

__all__ = [
    "read_lut",
    "write_lut",
]


def _count_set_bits(n):
    # can also consider using LSB index algo instead
    count = 0
    while n > 0:
        n &= n - 1
        count += 1
    return count


def _convert_group_to_multiplier(vs):
    return np.array([_count_set_bits(v) for v in vs], dtype=np.uint16)


def _set_bits_to_num(count):
    return (1 << count) - 1


def _convert_multiplier_to_group(vs):
    return np.array([_set_bits_to_num(v) for v in vs], dtype=np.uint16)


#########################


def read_lut(filename: PathLike):
    """Read as grayscale LUT in Holoeye LETO format.

    Only the lookup values are returned, with the gray level corresponding
    to the values' indices.
    """
    lut_convertors = {
        0: int,
        1: (lambda v: int(v, base=16)),
    }
    data = np.loadtxt(filename, dtype=np.uint16, converters=lut_convertors, skiprows=5)  # type: ignore
    _, ys = data.T
    groups = ys >> 5
    multipliers = _convert_group_to_multiplier(groups)
    ys = (ys & 0x1F) + (multipliers * 0x20)
    return ys


def write_lut(filename: PathLike, array: npt.NDArray[np.integer] | list[Integer]):
    """Write as grayscale LUT in Holoeye LETO format.

    Array must contain exactly 256 integers, corresponding to the SLM
    bitdepth of 8 bits.
    """
    if len(array) != 256:
        raise ValueError("Array must contain exactly 256 integers (i.e. 8-bit).")
    assert len(array) == 256
    ys = np.asarray(array, dtype=np.uint16)

    # Conversion
    multipliers = ys // 0x20
    groups = _convert_multiplier_to_group(multipliers)
    ys = (ys & 0x1F) + (groups << 5)

    # fmt: off
    header = \
        "# Colors (leave fixed for now)\r\n" \
        "0 1 2\r\n" \
        "# Points (leave fixed for now)\r\n" \
        "256\r\n" \
        "# \r\n"
    # fmt: on
    with open(filename, "w") as f:
        f.write(header)
        for i, y in enumerate(ys):
            hex = f"{round(y):04x}".upper()
            f.write(f"{i}  0x{hex}\r\n")
        f.write("\r\n")


if __name__ == "__main__":
    ys = read_lut("8-5_linear.lut")
    write_lut("test.lut", ys)
