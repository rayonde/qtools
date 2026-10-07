"""Holoeye calibration settings."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import numpy.typing as npt

from qtools.slm.luts import read_lut, validate_lut


def load_lut(value: str | Path | Sequence[int] | npt.NDArray[np.integer]) -> npt.NDArray[np.uint16]:
    if isinstance(value, (str, Path)):
        return read_lut(value)
    return validate_lut(value)


__all__ = ["load_lut"]
