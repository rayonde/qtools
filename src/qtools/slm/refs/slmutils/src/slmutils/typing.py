from pathlib import Path
from typing import TypeAlias, TypeVar

import numpy as np
import numpy.typing as npt

# Type definitions here
Integer: TypeAlias = int | np.integer
Float: TypeAlias = float | np.floating
Real: TypeAlias = Integer | Float
PathLike: TypeAlias = str | Path

T = TypeVar("T")

# Internal widths
DisplayMaskArray: TypeAlias = npt.NDArray[np.uint8]
PhaseMaskArray: TypeAlias = npt.NDArray[np.float64]
