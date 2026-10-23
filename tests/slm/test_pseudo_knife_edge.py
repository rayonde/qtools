"""Tests for pseudo-knife-edge phase generation and beam-center scans."""

from __future__ import annotations

import numpy as np
import pytest

from qtools.slm import PhaseMask, PhaseRegion, SLMGeometry
from qtools.slm.phase import pseudo_knife_edge
from qtools.slm.scripts.find_position import (
    cumulative_gaussian,
    fit_cumulative_gaussian,
    make_camera_measurement,
    measure_camera_roi,
    roi_sum,
    scan_beam_center,
)


@pytest.fixture
def geometry() -> SLMGeometry:
    return SLMGeometry(
        resolution=(80, 60),
        pitch_um=(6.4, 6.4),
        wavelength=532e-9,
    )


def test_pseudo_knife_edge_is_seeded_and_moves_only_the_boundary() -> None:
    shape = (8, 10)
    bounds = (2, 9, 1, 7)

    first = pseudo_knife_edge(
        shape,
        bounds,
        "x",
        5,
        seed=17,
        phase_range=(1.0, 2.0),
    )
    repeated = pseudo_knife_edge(
        shape,
        bounds,
        "x",
        5,
        seed=17,
        phase_range=(1.0, 2.0),
    )
    moved = pseudo_knife_edge(
        shape,
        bounds,
        "x",
        7,
        seed=17,
        phase_range=(1.0, 2.0),
    )

    np.testing.assert_array_equal(first, repeated)
    np.testing.assert_array_equal(first[:, :5], moved[:, :5])
    assert np.all(first[1:7, 2:5] >= 1.0)
    assert np.all(first[1:7, 5:] == 0.0)
    assert np.all(first[:1] == 0.0)
    assert np.all(first[7:] == 0.0)


def test_pseudo_knife_edge_supports_y_orientation() -> None:
    result = pseudo_knife_edge(
        (8, 10),
        (2, 9, 1, 7),
        "y",
        4,
        seed=3,
        phase_range=(1.0, 2.0),
    )

    assert np.all(result[1:4, 2:9] >= 1.0)
    assert np.all(result[4:, 2:9] == 0.0)
    assert np.all(result[:, :2] == 0.0)
    assert np.all(result[:, 9:] == 0.0)


@pytest.mark.parametrize(
    ("axis", "edge"),
    [("z", 4), ("x", 1), ("y", 8)],
)
def test_pseudo_knife_edge_rejects_invalid_axis_and_edge(axis: str, edge: int) -> None:
    with pytest.raises(ValueError):
        pseudo_knife_edge((8, 10), (2, 9, 1, 7), axis, edge)


def test_pseudo_knife_edge_rejects_scan_region_outside_active_region() -> None:
    with pytest.raises(ValueError, match="inside bounds"):
        pseudo_knife_edge(
            (8, 10),
            (2, 9, 1, 7),
            "x",
            5,
            scan_bounds=(0, 9, 1, 7),
        )


def test_phase_mask_pseudo_knife_edge_composes_with_a_base_phase(
    geometry: SLMGeometry,
) -> None:
    base = PhaseMask(np.ones(geometry.shape), geometry)

    result = base.pseudo_knife_edge(
        "x",
        40,
        scan_bounds=(10, 70, 10, 50),
        seed=2,
        phase_range=(0.2, 0.3),
    )

    assert result.geometry is geometry
    np.testing.assert_array_equal(result.array[:10], base.array[:10])
    np.testing.assert_array_equal(result.array[10:50, 40:70], 1.0)
    assert np.all((result.array[10:50, 10:40] >= 1.2))
    assert np.all(result.array[10:50, 10:40] < 1.3)


@pytest.mark.parametrize("amplitude", [2.0, -1.5])
def test_fit_cumulative_gaussian_recovers_center_and_width(amplitude: float) -> None:
    xs = np.arange(0.0, 81.0, 4.0)
    expected = (37.0, 8.0, amplitude, 0.4)
    ys = cumulative_gaussian(xs, *expected)

    fitted = fit_cumulative_gaussian(xs, ys)

    np.testing.assert_allclose(fitted, expected, rtol=1e-6, atol=1e-6)


def test_scan_beam_center_runs_both_axes_with_hardware_neutral_callbacks(
    geometry: SLMGeometry,
) -> None:
    scan_bounds = (5, 75, 4, 56)
    x_coordinates = np.arange(5, 76, 10, dtype=float)
    y_coordinates = np.r_[np.arange(4, 57, 10), 56.0]
    expected_measurements = np.r_[
        cumulative_gaussian(x_coordinates, 41.0, 9.0, 2.0, 0.1),
        cumulative_gaussian(y_coordinates, 27.0, 7.0, -1.5, 3.0),
    ]
    displayed: list[PhaseMask] = []
    remaining = iter(expected_measurements)

    def display_phase(mask: PhaseMask) -> None:
        displayed.append(mask.copy())

    def measure() -> float:
        return float(next(remaining))

    result = scan_beam_center(
        geometry=geometry,
        display_phase=display_phase,
        measure=measure,
        scan_bounds=scan_bounds,
        step=10,
        seed=23,
    )

    assert result.x == pytest.approx(41.0)
    assert result.y == pytest.approx(27.0)
    assert result.sigma_x == pytest.approx(9.0)
    assert result.sigma_y == pytest.approx(7.0)
    assert len(displayed) == len(expected_measurements) + 1
    assert all(mask.shape == geometry.shape for mask in displayed)
    assert np.all(displayed[-1].array == 0.0)


def test_camera_measurement_sums_roi_and_averages_frames() -> None:
    first = np.arange(20, dtype=np.float64).reshape(4, 5)
    second = first + 10.0

    class FakeCamera:
        def __init__(self) -> None:
            self.images = iter((first, second))

        def capture(self) -> np.ndarray:
            return next(self.images)

    roi = (1, 3, 1, 2)
    assert roi_sum(first, roi) == pytest.approx(13.0)
    assert measure_camera_roi(FakeCamera(), roi, frames=2) == pytest.approx(23.0)

    camera = FakeCamera()
    measurement = make_camera_measurement(camera, roi, frames=2)
    assert measurement() == pytest.approx(23.0)


def test_roi_sum_rejects_non_image_and_invalid_roi() -> None:
    with pytest.raises(ValueError, match="two-dimensional"):
        roi_sum(np.zeros((2, 2, 1)))
    with pytest.raises(ValueError, match="Invalid roi"):
        roi_sum(np.zeros((3, 4)), (0, 5, 0, 2))


def test_phase_region_keeps_its_region_metadata(geometry: SLMGeometry) -> None:
    region = PhaseRegion(geometry, (10, 70, 10, 50))

    result = region.pseudo_knife_edge("x", 40, seed=11)

    assert result.region_bounds == region.bounds
