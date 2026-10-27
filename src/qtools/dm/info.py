"""Device metadata and printable snapshots of modal control parameters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    """Device identity returned during discovery, before opening a session."""

    serial: str
    model: str
    manufacturer: str
    resource: str
    available: bool
    index: int


@dataclass(frozen=True)
class MirrorCapabilities:
    segment_count: int
    tilt_count: int
    zernike_minimum: float
    zernike_maximum: float
    segment_voltage_minimum: float
    segment_voltage_maximum: float
    tilt_voltage_minimum: float | None
    tilt_voltage_maximum: float | None


@dataclass(frozen=True)
class ParameterInfo:
    """One control's bounds and last successfully commanded value.

    ``current=None`` means unknown, not zero. Both bounds being None means any
    finite value is accepted (used for the periodic azimuth argument).
    """

    minimum: float | None
    maximum: float | None
    current: float | None
    unit: str
    setter: str


@dataclass(frozen=True, repr=False)
class MirrorInfo(DeviceInfo):
    """Connected-device snapshot, with structured data and a printable table.

    Parameters describe controls actually supported by the connected mirror.
    Values are this object's command history, not hardware/optical measurements.
    Obtain a new snapshot via ``dm.info`` after issuing another command.
    """

    parameters: dict[str, ParameterInfo]
    constraints: tuple[str, ...]

    def __str__(self) -> str:
        rows = [("Parameter", "Current", "Range", "Unit", "Setter")]
        for name, parameter in self.parameters.items():
            current = (
                "unknown" if parameter.current is None else f"{parameter.current:g}"
            )
            bounds = (
                "any finite value"
                if parameter.minimum is None and parameter.maximum is None
                else f"[{parameter.minimum:g}, {parameter.maximum:g}]"
            )
            rows.append((name, current, bounds, parameter.unit, parameter.setter))
        widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
        table = [
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
            for row in rows
        ]
        table.insert(1, "  ".join("-" * width for width in widths))
        return "\n".join(
            [
                f"{self.model} ({self.manufacturer}), serial={self.serial}",
                f"Resource: {self.resource}",
                "Current: last successful command from this object; unknown = not known.",
                *table,
                *self.constraints,
            ]
        )

    def __repr__(self) -> str:
        return str(self)


__all__ = ["DeviceInfo", "MirrorCapabilities", "MirrorInfo", "ParameterInfo"]
