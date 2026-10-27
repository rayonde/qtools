"""DMP40 factory modes and normalized pointing coordinates.

Thorlabs Z4..Z15 use the order in TLDFMX_def.h, not Noll indexing.
No actuator or optical calibration is synthesized here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real


def finite_real(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    return result


class ZernikeMode(str, Enum):
    """The twelve modes supported by the TLDFMX factory pattern interface."""

    ASTIGMATISM_45 = "astigmatism_45"
    DEFOCUS = "defocus"
    ASTIGMATISM_0 = "astigmatism_0"
    TREFOIL_Y = "trefoil_y"
    COMA_X = "coma_x"
    COMA_Y = "coma_y"
    TREFOIL_X = "trefoil_x"
    TETRAFOIL_Y = "tetrafoil_y"
    SECONDARY_ASTIGMATISM_Y = "secondary_astigmatism_y"
    SPHERICAL = "spherical"
    SECONDARY_ASTIGMATISM_X = "secondary_astigmatism_x"
    TETRAFOIL_X = "tetrafoil_x"

    @property
    def position(self) -> int:
        return tuple(type(self)).index(self)

    @property
    def flag(self) -> int:
        return 1 << self.position

    @property
    def thorlabs_index(self) -> int:
        return self.position + 4

    @property
    def noll_index(self) -> int:
        return _NOLL[self.position]

    @property
    def nm(self) -> tuple[int, int]:
        return _NM[self.position]

    @classmethod
    def from_thorlabs(cls, index: int) -> ZernikeMode:
        """Convert a Thorlabs Z4..Z15 index (not an SDK bit flag)."""
        index = _index(index)
        if not 4 <= index <= 15:
            raise ValueError("The factory SDK supports Thorlabs Z4 through Z15.")
        return tuple(cls)[index - 4]

    @classmethod
    def from_noll(cls, index: int) -> ZernikeMode:
        """Convert Noll j=4..15; Noll tip/tilt and piston are not factory modes."""
        index = _index(index)
        try:
            return tuple(cls)[_NOLL.index(index)]
        except ValueError as exc:
            raise ValueError(
                "The factory SDK supports Noll indices 4 through 15."
            ) from exc

    @classmethod
    def from_nm(cls, n: int, m: int) -> ZernikeMode:
        """Convert radial/azimuthal orders; negative m denotes sine terms."""
        pair = (_index(n), _index(m))
        try:
            return tuple(cls)[_NM.index(pair)]
        except ValueError as exc:
            raise ValueError(
                f"Unsupported factory mode (n, m)={pair}; supported n=2..4."
            ) from exc


_NOLL = (5, 4, 6, 9, 8, 7, 10, 15, 13, 11, 12, 14)
_NM = (
    (2, -2),
    (2, 0),
    (2, 2),
    (3, -3),
    (3, 1),
    (3, -1),
    (3, 3),
    (4, -4),
    (4, -2),
    (4, 0),
    (4, 2),
    (4, 4),
)


def _index(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError("A Zernike index must be an integer.")
    return int(value)


def resolve_mode(mode: ZernikeMode | str) -> ZernikeMode:
    if isinstance(mode, ZernikeMode):
        return mode
    if not isinstance(mode, str):
        raise TypeError(
            "Use a mode name or ZernikeMode.from_noll/from_thorlabs/from_nm."
        )
    try:
        return ZernikeMode(mode.lower())
    except ValueError as exc:
        raise ValueError(
            f"Unknown Zernike mode {mode!r}; use a name from ZernikeMode."
        ) from exc


def zernike_vector(
    coefficients: Mapping[ZernikeMode | str, Real],
    *,
    minimum: float = -1.0,
    maximum: float = 1.0,
) -> tuple[float, ...]:
    """Pack named device amplitudes in the twelve-element TLDFMX order.

    Unspecified modes are zero. The defaults are the nominal SDK range;
    connected controllers use the bounds returned by TLDFMX_get_parameters.
    """
    if not isinstance(coefficients, Mapping):
        raise TypeError("coefficients must map mode names to device amplitudes.")
    minimum = finite_real(minimum, "minimum")
    maximum = finite_real(maximum, "maximum")
    if minimum > maximum or not minimum <= 0 <= maximum:
        raise ValueError("Amplitude bounds must be ordered and include zero.")
    values = [0.0] * len(ZernikeMode)
    seen: set[ZernikeMode] = set()
    for key, value in coefficients.items():
        mode = resolve_mode(key)
        if mode in seen:
            raise ValueError(f"Duplicate mode: {mode.value}.")
        seen.add(mode)
        amplitude = finite_real(value, mode.value)
        if not minimum <= amplitude <= maximum:
            raise ValueError(
                f"{mode.value} amplitude must be in [{minimum}, {maximum}]."
            )
        values[mode.position] = amplitude
    return tuple(values)


@dataclass(frozen=True)
class TipTilt:
    """Normalized SDK X/Y pointing command, within the unit disk.

    X is qtools yaw and Y is qtools pitch. Signs are in the SDK coordinate frame;
    mounting orientation determines their relation to laboratory coordinates.
    """

    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", finite_real(self.x, "x"))
        object.__setattr__(self, "y", finite_real(self.y, "y"))
        if math.hypot(self.x, self.y) > 1.0:
            raise ValueError("Normalized tip/tilt requires hypot(x, y) <= 1.")

    @property
    def amplitude(self) -> float:
        return math.hypot(self.x, self.y)

    @property
    def azimuth_deg(self) -> float:
        return math.degrees(math.atan2(self.y, self.x)) if self.amplitude else 0.0

    @classmethod
    def from_polar(cls, amplitude: float, azimuth_deg: float) -> TipTilt:
        amplitude = finite_real(amplitude, "amplitude")
        angle = math.radians(finite_real(azimuth_deg, "azimuth_deg") % 360)
        if not 0 <= amplitude <= 1:
            raise ValueError("Normalized tilt amplitude must be in [0, 1].")
        x, y = amplitude * math.cos(angle), amplitude * math.sin(angle)
        # Roundoff at the unit circle must not reject an otherwise valid command.
        radius = math.hypot(x, y)
        if radius > 1:
            x, y = x / radius, y / radius
        return cls(x=x, y=y)
