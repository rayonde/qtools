"""DMP40 modal control using the Thorlabs ctypes example's SDK workflow."""

from __future__ import annotations

import ctypes as ct
import math
import os
import time
import warnings
from collections.abc import Mapping
from dataclasses import asdict
from numbers import Integral, Real
from threading import RLock

import numpy as np
import numpy.typing as npt

from qtools.dm.exceptions import DMCapabilityError, DMConnectionError, DMError
from qtools.dm.info import MirrorCapabilities, MirrorInfo, ParameterInfo
from qtools.dm.modes import (
    TipTilt,
    ZernikeMode,
    finite_real,
    resolve_mode,
    zernike_vector,
)

from .sdk import (
    ALL_ZERNIKES,
    DMP40SDK,
    DeviceInfo,
    ViInt32,
    ViReal64,
    ViSession,
    ViUInt32,
)


class DMP40:
    """Lazy DMP40 controller. Connect explicitly or use a context manager.

    The object caches its last successful modal commands, not measured optical
    state. Closing the connection leaves the hardware output unchanged.
    """

    def __init__(
        self,
        *,
        serial: str | None = None,
        resource: str | None = None,
        dll_dir: str | os.PathLike[str] | None = None,
        sdk: DMP40SDK | None = None,
    ) -> None:
        if serial is not None and resource is not None:
            raise ValueError("Select the device by serial or resource, not both.")
        for name, value in (("serial", serial), ("resource", resource)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonempty string.")
        if sdk is not None and dll_dir is not None:
            raise ValueError("Pass either sdk or dll_dir.")
        self._serial = serial
        self._resource = resource
        self._sdk = sdk if sdk is not None else DMP40SDK(dll_dir)
        self._session = ViSession()
        self._info: DeviceInfo | None = None
        self._capabilities: MirrorCapabilities | None = None
        self._zernikes: tuple[float, ...] | None = None
        self._tip_tilt: TipTilt | None = None
        self._lock = RLock()

    @classmethod
    def discover(
        cls, *, dll_dir: str | os.PathLike[str] | None = None
    ) -> list[DeviceInfo]:
        sdk = DMP40SDK(dll_dir)
        try:
            return sdk.discover()
        finally:
            sdk.unload()

    @property
    def is_connected(self) -> bool:
        return bool(self._session.value)

    @property
    def info(self) -> MirrorInfo:
        """Snapshot of supported controls, SDK bounds and cached command values.

        Printing this snapshot renders a table. Reading it does not call the
        SDK, change outputs, or infer modal values from voltage setpoints.
        """
        with self._lock:
            cap = self.capabilities
            assert self._info is not None
            parameters: dict[str, ParameterInfo] = {}
            constraints = [
                "Current values are setpoints, not measured optical readback."
            ]
            if cap.tilt_count:
                pointing = self._tip_tilt
                x = pointing.x if pointing is not None else None
                y = pointing.y if pointing is not None else None
                for name, current, setter in (
                    ("pitch", y, "set_orientation"),
                    ("yaw", x, "set_orientation"),
                    ("x", x, "set_tip_tilt"),
                    ("y", y, "set_tip_tilt"),
                ):
                    parameters[name] = ParameterInfo(
                        -1.0, 1.0, current, "normalized", setter
                    )
                parameters["amplitude"] = ParameterInfo(
                    0.0,
                    1.0,
                    pointing.amplitude if pointing is not None else None,
                    "normalized",
                    "set_tilt",
                )
                parameters["azimuth_deg"] = ParameterInfo(
                    None,
                    None,
                    pointing.azimuth_deg if pointing is not None else None,
                    "deg",
                    "set_tilt",
                )
                constraints.extend(
                    [
                        "pitch = y; yaw = x; pitch**2 + yaw**2 <= 1 (also x**2 + y**2 <= 1).",
                        "azimuth_deg is periodic (360 deg); current is shown in [-180, 180].",
                        "Pointing amplitudes are normalized commands, not mechanical angles.",
                    ]
                )
            else:
                constraints.append(
                    "Independent tilt control is unavailable on this device."
                )
            for mode in ZernikeMode:
                current = (
                    self._zernikes[mode.position]
                    if self._zernikes is not None
                    else None
                )
                parameters[mode.value] = ParameterInfo(
                    cap.zernike_minimum,
                    cap.zernike_maximum,
                    current,
                    "normalized",
                    "set_zernikes",
                )
            constraints.append(
                "Zernike bounds are SDK device amplitudes; combinations must also pass SDK voltage range checks."
            )
            return MirrorInfo(
                **asdict(self._info),
                parameters=parameters,
                constraints=tuple(constraints),
            )

    @property
    def capabilities(self) -> MirrorCapabilities:
        self._require_connection()
        assert self._capabilities is not None
        return self._capabilities

    @property
    def zernikes(self) -> dict[ZernikeMode, float] | None:
        """Last commanded coefficients, or None when unknown; never a measurement."""
        with self._lock:
            return (
                None
                if self._zernikes is None
                else dict(zip(ZernikeMode, self._zernikes))
            )

    @property
    def tip_tilt(self) -> TipTilt | None:
        """Last commanded pointing coordinates, or None when unknown."""
        with self._lock:
            return self._tip_tilt

    def _require_connection(self) -> None:
        if not self.is_connected:
            raise DMConnectionError(
                "DMP40 is not connected; call connect() or use 'with'."
            )

    def connect(self) -> DMP40:
        """Open via TLDFMX_init with ID query and without resetting the device."""
        with self._lock:
            if self.is_connected:
                return self
            try:
                devices = self._sdk.discover()
                matches = [
                    d
                    for d in devices
                    if (self._serial is None or d.serial == self._serial)
                    and (self._resource is None or d.resource == self._resource)
                ]
                if not matches:
                    raise DMConnectionError(
                        "No matching Thorlabs deformable mirror found."
                    )
                if len(matches) > 1:
                    raise DMConnectionError(
                        "Multiple mirrors found; select serial= or resource= explicitly."
                    )
                device = matches[0]
                if not device.available:
                    raise DMConnectionError(
                        f"Mirror {device.serial} is already in use."
                    )
                self._sdk.check(
                    "TLDFMX_init",
                    device.resource.encode("ascii"),
                    1,
                    0,
                    ct.byref(self._session),
                )
                if not self.is_connected:
                    raise DMConnectionError("TLDFMX_init returned an empty session.")
                self._capabilities = self._read_capabilities()
                self._sdk.check("TLDFMX_set_pattern_range_check", self._session, 1)
                self._info = device
            except BaseException:
                if self.is_connected:
                    try:
                        self._sdk.check("TLDFMX_close", self._session)
                    except (DMError, OSError) as exc:
                        warnings.warn(
                            f"Could not close the partially opened DMP40: {exc}",
                            RuntimeWarning,
                        )
                self._session = ViSession()
                self._info = None
                self._capabilities = None
                self._sdk.unload()
                raise
            return self

    def _read_capabilities(self) -> MirrorCapabilities:
        def read(name, kind=ViReal64):
            return self._sdk.scalar(name, self._session, kind)

        segments = int(read("TLDFM_get_segment_count", ViUInt32))
        tilts = int(read("TLDFM_get_tilt_count", ViUInt32))
        if segments != 40 or tilts not in (0, 3):
            raise DMCapabilityError(
                f"Expected 40 segments and 0/3 tilt arms; got {segments}/{tilts}."
            )
        minimum, maximum = ViReal64(), ViReal64()
        count, measurement_steps, relax_steps = ViInt32(), ViInt32(), ViInt32()
        self._sdk.check(
            "TLDFMX_get_parameters",
            self._session,
            ct.byref(minimum),
            ct.byref(maximum),
            ct.byref(count),
            ct.byref(measurement_steps),
            ct.byref(relax_steps),
        )
        if count.value != len(ZernikeMode):
            raise DMCapabilityError(
                f"Expected 12 factory Zernike modes, got {count.value}."
            )
        segment_min, segment_max = (
            float(read(f"TLDFM_get_segment_{s}")) for s in ("minimum", "maximum")
        )
        tilt_min, tilt_max = (
            (float(read(f"TLDFM_get_tilt_{s}")) for s in ("minimum", "maximum"))
            if tilts
            else (None, None)
        )
        limits = [(minimum.value, maximum.value), (segment_min, segment_max)]
        if tilts:
            limits.append((tilt_min, tilt_max))
        for lo, hi in limits:
            if not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
                raise DMError("The SDK reported invalid device limits.")
        if not minimum.value <= 0 <= maximum.value:
            raise DMError("The SDK amplitude range does not include zero.")
        return MirrorCapabilities(
            segments,
            tilts,
            minimum.value,
            maximum.value,
            segment_min,
            segment_max,
            tilt_min,
            tilt_max,
        )

    def close(self) -> None:
        """Release the SDK session. This does not reset voltages or relax the mirror."""
        with self._lock:
            if self.is_connected:
                self._zernikes = None
                self._tip_tilt = None
                self._sdk.check("TLDFMX_close", self._session)
                self._session = ViSession()
            self._info = None
            self._capabilities = None
            self._sdk.unload()

    def disconnect(self) -> None:
        self.close()

    def _vector(
        self, coefficients: Mapping[ZernikeMode | str, Real]
    ) -> tuple[float, ...]:
        cap = self.capabilities
        return zernike_vector(
            coefficients, minimum=cap.zernike_minimum, maximum=cap.zernike_maximum
        )

    def _validate_pattern(
        self, pattern, *, tilt: bool = False
    ) -> npt.NDArray[np.float64]:
        values = np.array(pattern, dtype=np.float64, copy=True)
        cap = self.capabilities
        lo = cap.tilt_voltage_minimum if tilt else cap.segment_voltage_minimum
        hi = cap.tilt_voltage_maximum if tilt else cap.segment_voltage_maximum
        if (
            lo is None
            or hi is None
            or not np.all(np.isfinite(values))
            or np.any(values < lo)
            or np.any(values > hi)
        ):
            raise DMError(
                "SDK pattern contains non-finite or out-of-range voltages; no pattern was written."
            )
        return values

    def _calculate(self, vector: tuple[float, ...], single: ZernikeMode | None = None):
        pattern = (ViReal64 * self.capabilities.segment_count)()
        if single is None:
            amplitudes = (ViReal64 * len(ZernikeMode))(*vector)
            self._sdk.check(
                "TLDFMX_calculate_zernike_pattern",
                self._session,
                ALL_ZERNIKES,
                amplitudes,
                pattern,
            )
        else:
            self._sdk.check(
                "TLDFMX_calculate_single_zernike_pattern",
                self._session,
                single.flag,
                vector[single.position],
                pattern,
            )
        self._validate_pattern(pattern)
        return pattern

    def calculate_zernikes(
        self, coefficients: Mapping[ZernikeMode | str, Real]
    ) -> npt.NDArray[np.float64]:
        """Ask the connected SDK for a pattern without writing it to the mirror."""
        with self._lock:
            return np.array(
                self._calculate(self._vector(coefficients)), dtype=np.float64, copy=True
            )

    def _apply_zernikes(
        self, vector: tuple[float, ...], single: ZernikeMode | None = None
    ) -> None:
        pattern = self._calculate(vector, single)
        self._zernikes = None  # A failing write can leave hardware state uncertain.
        self._sdk.check("TLDFM_set_segment_voltages", self._session, pattern)
        self._zernikes = vector

    def set_zernike(self, mode: ZernikeMode | str, amplitude: float) -> None:
        """Apply one mode, replacing all previous mirror-shape coefficients."""
        with self._lock:
            mode = resolve_mode(mode)
            self._apply_zernikes(self._vector({mode: amplitude}), single=mode)

    def set_zernikes(self, coefficients: Mapping[ZernikeMode | str, Real]) -> None:
        """Replace the complete shape; omitted modes become zero. Pointing is retained."""
        with self._lock:
            self._apply_zernikes(self._vector(coefficients))

    def update_zernikes(self, coefficients: Mapping[ZernikeMode | str, Real]) -> None:
        """Update specified modes after a successful set; preserve the other modes."""
        with self._lock:
            self._require_connection()
            if self._zernikes is None:
                raise DMError(
                    "Modal state is unknown; first call set_zernike(s) or zero_zernikes()."
                )
            validated = self._vector(coefficients)
            merged = list(self._zernikes)
            for key in coefficients:
                position = resolve_mode(key).position
                merged[position] = validated[position]
            self._apply_zernikes(tuple(merged))

    def zero_zernikes(self) -> None:
        """Apply zero SDK coefficients (the factory reference, not measured flatness)."""
        self.set_zernikes({})

    def set_tip_tilt(self, *, x: float, y: float) -> None:
        """Set normalized X/Y pointing via the SDK polar-coordinate function."""
        command = TipTilt(x, y)
        with self._lock:
            if not self.capabilities.tilt_count:
                raise DMCapabilityError(
                    "This mirror has no independent tilt arms (e.g. DMH40)."
                )
            self._tip_tilt = None
            self._sdk.check(
                "TLDFM_set_tilt_amplitude_angle",
                self._session,
                command.amplitude,
                command.azimuth_deg,
            )
            self._tip_tilt = command

    def set_orientation(self, *, pitch: float, yaw: float) -> None:
        """Set normalized pitch (SDK Y) and yaw (SDK X), not physical angle units."""
        self.set_tip_tilt(x=yaw, y=pitch)

    def set_tilt(self, *, amplitude: float, azimuth_deg: float) -> None:
        """Set a normalized tilt magnitude and direction in degrees."""
        command = TipTilt.from_polar(amplitude, azimuth_deg)
        self.set_tip_tilt(x=command.x, y=command.y)

    def relax(
        self, *, part: str = "both", interval_s: float = 0.01, max_steps: int = 10000
    ) -> int:
        """Run the reference relaxation sequence; return the applied step count.

        Shape/pointing state becomes unknown for each affected part. On mirrors
        without tilt arms, 'both' relaxes only the mirror. No other control call
        on this object may interleave with relaxation.
        """
        if part not in ("mirror", "tilt", "both"):
            raise ValueError("part must be 'mirror', 'tilt', or 'both'.")
        interval_s = finite_real(interval_s, "interval_s")
        if interval_s < 0:
            raise ValueError("interval_s must be nonnegative.")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, Integral)
            or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer.")
        with self._lock:
            cap = self.capabilities
            if part == "tilt" and not cap.tilt_count:
                raise DMCapabilityError("This mirror has no tilt arms.")
            mirror = part != "tilt"
            tilt = part != "mirror" and cap.tilt_count > 0
            target = 2 if mirror and tilt else (0 if mirror else 1)
            mirror_pattern = (ViReal64 * cap.segment_count)()
            tilt_pattern = (ViReal64 * cap.tilt_count)()
            remaining = ViInt32()
            for step in range(max_steps):
                self._sdk.check(
                    "TLDFMX_relax",
                    self._session,
                    target,
                    int(step == 0),
                    0,
                    mirror_pattern,
                    tilt_pattern,
                    ct.byref(remaining),
                )
                if remaining.value < 0:
                    raise DMError(
                        "SDK relaxation returned a negative remaining step count."
                    )
                if mirror:
                    self._validate_pattern(mirror_pattern)
                if tilt:
                    self._validate_pattern(tilt_pattern, tilt=True)
                if mirror:
                    self._zernikes = None
                    self._sdk.check(
                        "TLDFM_set_segment_voltages", self._session, mirror_pattern
                    )
                if tilt:
                    self._tip_tilt = None
                    self._sdk.check(
                        "TLDFM_set_tilt_voltages", self._session, tilt_pattern
                    )
                if remaining.value == 0:
                    return step + 1
                time.sleep(interval_s)
            raise DMError(
                f"Relaxation did not finish after {max_steps} steps; outputs remain at the last applied step."
            )

    def read_voltages(self) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Read driver voltage setpoints for diagnostics, not measured wavefront data."""
        with self._lock:
            cap = self.capabilities
            mirror = (ViReal64 * cap.segment_count)()
            tilt = (ViReal64 * cap.tilt_count)()
            self._sdk.check("TLDFM_get_segment_voltages", self._session, mirror)
            if cap.tilt_count:
                self._sdk.check("TLDFM_get_tilt_voltages", self._session, tilt)
            return np.array(mirror, copy=True), np.array(tilt, copy=True)

    def __enter__(self) -> DMP40:  # noqa: PYI034 - Python 3.10, no typing.Self
        return self.connect()

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.close()
        except Exception as close_error:
            if exc is None:
                raise
            warnings.warn(
                f"DMP40 close also failed: {close_error}", RuntimeWarning, stacklevel=2
            )


__all__ = ["DMP40", "MirrorCapabilities"]
