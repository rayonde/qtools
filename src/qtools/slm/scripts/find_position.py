"""Pseudo-knife-edge beam-center scans.

The scan itself is hardware agnostic.  A caller supplies one callback that
displays a :class:`~qtools.slm.phase.PhaseMask` and another that returns the
current scalar optical measurement.  The command-line entry point wires those
callbacks to :class:`qtools.slm.SLM` and :class:`qtools.camera.Camera`.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erf

from qtools.slm.phase.phasemask import Bounds, PhaseMask, PhaseRegion

if TYPE_CHECKING:
    from qtools.slm.slm import SLMGeometry


Measurement = Callable[[], float]
DisplayPhase = Callable[[PhaseMask], None]


@dataclass(frozen=True)
class AxisScan:
    """Raw samples and fit parameters for one knife-edge direction."""

    coordinates: np.ndarray
    measurements: np.ndarray
    fit_parameters: tuple[float, float, float, float]

    @property
    def center(self) -> float:
        return self.fit_parameters[0]

    @property
    def sigma(self) -> float:
        return self.fit_parameters[1]


@dataclass(frozen=True)
class BeamCenterResult:
    """Result of independent x and y pseudo-knife-edge scans."""

    x: float
    y: float
    sigma_x: float
    sigma_y: float
    x_scan: AxisScan
    y_scan: AxisScan

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return ``(x, y, sigma_x, sigma_y)`` for compact use."""

        return self.x, self.y, self.sigma_x, self.sigma_y


def cumulative_gaussian(
    x: np.ndarray,
    center: float,
    sigma: float,
    amplitude: float,
    background: float,
) -> np.ndarray:
    """Evaluate the cumulative-Gaussian edge response."""

    if sigma <= 0:
        raise ValueError("sigma must be positive.")
    values = np.asarray(x, dtype=float)
    return background + amplitude * 0.5 * (
        erf((values - center) / (np.sqrt(2.0) * sigma)) + 1.0
    )


def fit_cumulative_gaussian(
    xs: np.ndarray,
    ys: np.ndarray,
) -> tuple[float, float, float, float]:
    """Fit an edge response and return center, sigma, amplitude, background."""

    x_values = np.asarray(xs, dtype=float)
    y_values = np.asarray(ys, dtype=float)
    if x_values.ndim != 1 or y_values.ndim != 1 or x_values.size != y_values.size:
        raise ValueError("xs and ys must be equally sized one-dimensional arrays.")
    if x_values.size < 4:
        raise ValueError("At least four samples are required for an edge fit.")
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise ValueError("xs and ys must contain only finite values.")
    if np.any(np.diff(x_values) <= 0):
        raise ValueError("xs must be strictly increasing.")

    span = float(np.ptp(x_values))
    if span <= 0:
        raise ValueError("xs must span a non-zero interval.")
    amplitude = float(y_values[-1] - y_values[0])
    background = float(y_values[0])
    if np.isclose(amplitude, 0.0):
        raise ValueError("The edge response has no measurable change.")

    midpoint = background + amplitude / 2.0
    one_sigma_level = background + amplitude / np.e**2
    center_guess = float(x_values[np.argmin(np.abs(y_values - midpoint))])
    sigma_guess = abs(
        float(
            x_values[np.argmin(np.abs(y_values - one_sigma_level))]
            - center_guess
        )
    )
    sigma_guess = max(
        sigma_guess,
        span / max(6.0, x_values.size),
        np.finfo(float).eps,
    )
    p0 = (center_guess, sigma_guess, amplitude, background)

    result, _ = curve_fit(
        cumulative_gaussian,
        x_values,
        y_values,
        p0=p0,
        bounds=(
            [x_values[0] - span, np.finfo(float).eps, -np.inf, -np.inf],
            [x_values[-1] + span, max(2.0 * span, sigma_guess), np.inf, np.inf],
        ),
        maxfev=10_000,
    )
    center, sigma, fitted_amplitude, fitted_background = result
    return (
        float(center),
        float(sigma),
        float(fitted_amplitude),
        float(fitted_background),
    )


def roi_sum(image: np.ndarray, roi: Bounds | None = None) -> float:
    """Return the integrated intensity in an image ROI.

    ``roi`` uses ``(left, right, top, bottom)`` with the right and bottom
    edges excluded, matching NumPy slicing and the SLM phase APIs.
    """

    values = np.asarray(image)
    if values.ndim != 2:
        raise ValueError("Camera images must be two-dimensional arrays.")
    if roi is None:
        selected = values
    else:
        left, right, top, bottom = _validate_roi(roi, values.shape)
        selected = values[top:bottom, left:right]
    return float(np.sum(selected, dtype=np.float64))


def measure_camera_roi(
    camera: Any,
    roi: Bounds | None = None,
    *,
    frames: int = 1,
) -> float:
    """Capture and average ROI-integrated intensity from a camera."""

    if int(frames) <= 0:
        raise ValueError("frames must be positive.")
    measurements = [roi_sum(camera.capture(), roi) for _ in range(int(frames))]
    return float(np.mean(measurements))


def make_camera_measurement(
    camera: Any,
    roi: Bounds | None = None,
    *,
    frames: int = 1,
) -> Measurement:
    """Create a zero-argument measurement callback for a camera."""

    return lambda: measure_camera_roi(camera, roi, frames=frames)


def scan_beam_center(
    *,
    geometry: "SLMGeometry",
    display_phase: DisplayPhase,
    measure: Measurement,
    scan_bounds: Bounds,
    base_phase: PhaseMask | None = None,
    step: int = 5,
    settle_s: float = 0.0,
    seed: int | None = 0,
    phase_range: tuple[float, float] = (0.0, 2 * np.pi),
    plot: bool | str | Path = False,
) -> BeamCenterResult:
    """Run x/y pseudo-knife-edge scans and fit the beam center.

    ``display_phase`` is called once per edge position.  ``measure`` should
    return the scalar intensity of the desired optical channel, commonly the
    sum of a camera ROI or a power-meter reading.
    """

    bounds = _validate_scan_bounds(scan_bounds, geometry.resolution)
    if int(step) <= 0:
        raise ValueError("step must be positive.")
    if float(settle_s) < 0:
        raise ValueError("settle_s must be non-negative.")
    if base_phase is not None:
        if not isinstance(base_phase, PhaseMask):
            raise TypeError("base_phase must be a PhaseMask.")
        if base_phase.geometry is not geometry:
            raise ValueError("base_phase must belong to the supplied geometry.")

    region = PhaseRegion(geometry, bounds)
    x_values = _edge_positions(bounds[0], bounds[1], int(step))
    y_values = _edge_positions(bounds[2], bounds[3], int(step))

    def scan_axis(axis: str, coordinates: np.ndarray) -> np.ndarray:
        values: list[float] = []
        for edge in coordinates:
            phase = region.pseudo_knife_edge(
                axis,
                int(edge),
                seed=seed,
                phase_range=phase_range,
            )
            if base_phase is not None:
                phase = base_phase + phase
            display_phase(phase)
            if settle_s:
                time.sleep(float(settle_s))
            value = float(measure())
            if not np.isfinite(value):
                raise ValueError("measure() must return a finite scalar.")
            values.append(value)
        return np.asarray(values, dtype=float)

    try:
        x_measurements = scan_axis("x", x_values)
        y_measurements = scan_axis("y", y_values)
        x_fit = fit_cumulative_gaussian(x_values, x_measurements)
        y_fit = fit_cumulative_gaussian(y_values, y_measurements)
    finally:
        display_phase(base_phase if base_phase is not None else PhaseMask.zeros(geometry))

    result = BeamCenterResult(
        x=x_fit[0],
        y=y_fit[0],
        sigma_x=x_fit[1],
        sigma_y=y_fit[1],
        x_scan=AxisScan(x_values, x_measurements, x_fit),
        y_scan=AxisScan(y_values, y_measurements, y_fit),
    )
    if plot is not False:
        plot_scan(result, None if plot is True else plot)
    return result


def plot_scan(result: BeamCenterResult, filename: str | Path | None = None):
    """Plot raw x/y scan data and cumulative-Gaussian fits."""

    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(2, 1, figsize=(7, 6), constrained_layout=True)
    for axis, scan, label, color in (
        (axes[0], result.x_scan, "x", "tab:blue"),
        (axes[1], result.y_scan, "y", "tab:orange"),
    ):
        axis.plot(scan.coordinates, scan.measurements, "x", color=color, label="data")
        axis.plot(
            scan.coordinates,
            cumulative_gaussian(scan.coordinates, *scan.fit_parameters),
            "--",
            color="black",
            label="cumulative Gaussian fit",
        )
        axis.set_xlabel(f"{label} edge coordinate (pixel)")
        axis.set_ylabel("ROI intensity / measurement")
        axis.set_title(
            f"Beam center {label} = {scan.center:.2f}, "
            f"sigma = {scan.sigma:.2f} px"
        )
        axis.legend()

    if filename is None:
        plt.show()
    else:
        figure.savefig(filename, dpi=200)
    return figure


def _validate_scan_bounds(bounds: Sequence[int], resolution: tuple[int, int]) -> Bounds:
    if len(bounds) != 4:
        raise ValueError("scan_bounds must contain (left, right, top, bottom).")
    left, right, top, bottom = (int(value) for value in bounds)
    width, height = resolution
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"Invalid scan_bounds {tuple(bounds)} for resolution {resolution}.")
    return left, right, top, bottom


def _validate_roi(roi: Sequence[int], image_shape: tuple[int, int]) -> Bounds:
    if len(roi) != 4:
        raise ValueError("roi must contain (left, right, top, bottom).")
    left, right, top, bottom = (int(value) for value in roi)
    height, width = image_shape
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"Invalid roi {tuple(roi)} for image shape {image_shape}.")
    return left, right, top, bottom


def _edge_positions(start: int, stop: int, step: int) -> np.ndarray:
    values = list(range(start, stop + 1, step))
    if values[-1] != stop:
        values.append(stop)
    return np.asarray(values, dtype=float)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="LETO-II", help="Holoeye SLM model.")
    parser.add_argument("--wavelength", type=float, default=532e-9, help="Wavelength in metres.")
    parser.add_argument("--monitor", type=int, default=None, help="Monitor index for the SLM.")
    parser.add_argument("--camera-backend", default="flir", help="qtools.camera backend name.")
    parser.add_argument("--camera-serial", default="", help="Camera serial number.")
    parser.add_argument(
        "--scan-bounds",
        nargs=4,
        type=int,
        metavar=("LEFT", "RIGHT", "TOP", "BOTTOM"),
    )
    parser.add_argument(
        "--roi",
        nargs=4,
        type=int,
        metavar=("LEFT", "RIGHT", "TOP", "BOTTOM"),
    )
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--settle", type=float, default=0.05, help="Display settle time in seconds.")
    parser.add_argument("--frames", type=int, default=1, help="Camera frames averaged per edge.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--plot", type=Path, help="Save the scan diagnostic plot.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> BeamCenterResult:
    """Run a physical Holoeye + camera beam-center scan."""

    args = _parse_args(argv)
    from qtools.camera import Camera
    from qtools.slm import SLM

    with SLM(
        "holoeye",
        model=args.model,
        wavelength=args.wavelength,
        monitor=args.monitor,
    ) as slm, Camera(backend=args.camera_backend, serial=args.camera_serial) as camera:
        scan_bounds = args.scan_bounds or (0, slm.resolution[0], 0, slm.resolution[1])
        measurement = make_camera_measurement(
            camera,
            None if args.roi is None else tuple(args.roi),
            frames=args.frames,
        )
        result = scan_beam_center(
            geometry=slm.geometry,
            display_phase=slm.load_phase,
            measure=measurement,
            scan_bounds=tuple(scan_bounds),
            base_phase=slm.create_canvas().flat(),
            step=args.step,
            settle_s=args.settle,
            seed=args.seed,
            plot=args.plot or False,
        )

    print(
        f"beam center: x={result.x:.3f}, y={result.y:.3f}; "
        f"sigma_x={result.sigma_x:.3f}, sigma_y={result.sigma_y:.3f}"
    )
    return result


__all__ = [
    "AxisScan",
    "BeamCenterResult",
    "cumulative_gaussian",
    "fit_cumulative_gaussian",
    "main",
    "make_camera_measurement",
    "measure_camera_roi",
    "plot_scan",
    "roi_sum",
    "scan_beam_center",
]


if __name__ == "__main__":
    main()
