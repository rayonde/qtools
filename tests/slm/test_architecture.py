"""Tests for the region-oriented qtools.slm API."""

from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pytest

from qtools.slm import DisplayMask, PhaseMask, PhaseRegion, SLM, list_backends
from qtools.slm.phase import lg_radial_amplitude, perfect_spiral, superposition
from qtools.slm.luts import read_lut, write_lut


@pytest.fixture
def slm() -> SLM:
    return SLM("holoeye", model="LETO-II", headless=True)


def test_backend_registry_is_explicit_and_lazy() -> None:
    assert list_backends() == ["holoeye", "simulated"]
    assert "slmsuite" not in sys.modules


def test_canvas_is_an_empty_root_phase_region(slm: SLM) -> None:
    canvas = slm.create_canvas()

    assert isinstance(canvas, PhaseRegion)
    assert isinstance(canvas, PhaseMask)
    assert canvas.bounds == (0, 1920, 0, 1080)
    assert canvas.shape == (1080, 1920)
    assert np.all(canvas.array == 0)


def test_partition_generates_full_size_region_masks(slm: SLM) -> None:
    canvas = slm.create_canvas()
    left, right = canvas.partition(axis="x", ratios=(1, 2))

    assert left.bounds == (0, 640, 0, 1080)
    assert right.bounds == (640, 1920, 0, 1080)

    phase = left.spiral(order=1).lens(f=2.0)
    assert phase.shape == slm.shape
    assert phase.region_bounds == left.bounds
    assert np.all(phase.array[:, 640:] == 0)
    assert np.any(phase.array[:, :640] != 0)


def test_perfect_spiral_matches_spiral_when_radial_frequency_is_zero(
    slm: SLM,
) -> None:
    canvas = slm.create_canvas()
    expected = canvas.spiral(order=-2)
    result = canvas.perfect_spiral(order=-2, radial_frequency=0.0)

    np.testing.assert_allclose(result.array, expected.array)
    assert result.geometry is slm.geometry
    assert result.region_bounds == canvas.bounds


def test_perfect_spiral_uses_azimuthal_and_radial_phase_terms(
    slm: SLM,
) -> None:
    bounds = (10, 18, 20, 26)
    order = 2
    radial_frequency = 0.125
    center = (12.0, 22.0)
    result = perfect_spiral(
        slm.shape,
        bounds,
        order=order,
        radial_frequency=radial_frequency,
        center=center,
    )

    xs = np.arange(bounds[0], bounds[1], dtype=float)
    ys = np.arange(bounds[2], bounds[3], dtype=float)
    xx, yy = np.meshgrid(xs, ys)
    radius = np.hypot(xx - center[0], yy - center[1])
    expected = order * np.arctan2(yy - center[1], xx - center[0])
    expected += 2 * np.pi * radial_frequency * radius

    np.testing.assert_allclose(
        result[bounds[2] : bounds[3], bounds[0] : bounds[1]], expected
    )
    assert np.all(result[: bounds[2]] == 0)
    assert np.all(result[bounds[3] :] == 0)
    assert np.all(result[:, : bounds[0]] == 0)
    assert np.all(result[:, bounds[1] :] == 0)


def test_perfect_spiral_rejects_nonfinite_radial_frequency(slm: SLM) -> None:
    with pytest.raises(ValueError, match="finite"):
        slm.create_canvas().perfect_spiral(radial_frequency=np.inf)

    with pytest.raises(ValueError, match="finite"):
        slm.create_canvas().perfect_spiral(radial_frequency=np.nan)


def test_perfect_spiral_converts_to_display(slm: SLM) -> None:
    phase = slm.create_canvas().perfect_spiral(
        order=1,
        radial_frequency=-0.02,
        center=(slm.resolution[0] / 2, slm.resolution[1] / 2),
    )

    display = phase.to_display(bits=8)

    assert isinstance(display, DisplayMask)
    assert display.array.dtype == np.uint8


def test_compose_combines_regions_and_rejects_overlap(slm: SLM) -> None:
    canvas = slm.create_canvas()
    left, right = canvas.partition(axis="x", ratios=(1, 1))
    combined = canvas.compose(left.spiral(order=1), right.spiral(order=-2))

    assert combined.region_bounds is None
    assert np.any(combined.array[:, :960] != 0)
    assert np.any(combined.array[:, 960:] != 0)

    with pytest.raises(ValueError, match="overlap"):
        canvas.compose(left.spiral(order=1), left.lens(f=1.0))


def test_phase_conversion_and_rgb_packing(slm: SLM) -> None:
    phase = slm.create_canvas().flat(np.pi)

    gray = phase.to_display(bits=8)
    rgb = phase.to_display(bits=10, rgb=True)

    assert isinstance(gray, DisplayMask)
    assert gray.array.dtype == np.uint8
    assert np.all(gray.array == 128)
    assert rgb.rgb is True
    assert rgb.array.shape == (1080, 1920, 3)
    assert np.all(rgb.array[:, :, 2] == 0)


def test_superposition_returns_the_phase_of_a_normalized_complex_field(
    slm: SLM,
) -> None:
    canvas = slm.create_canvas()
    zero = canvas.flat()

    phase = superposition(zero, zero, coefficients=(1.0, 1j))

    assert isinstance(phase, PhaseMask)
    assert phase.geometry is slm.geometry
    assert phase.region_bounds is None
    np.testing.assert_allclose(phase.array, np.pi / 4)

    display = phase.to_display(bits=8)
    assert isinstance(display, DisplayMask)
    assert display.array.dtype == np.uint8


def test_lg_radial_amplitude_matches_p_zero_envelope(slm: SLM) -> None:
    canvas = slm.create_canvas()
    zero = canvas.spiral(order=0)
    center = (slm.resolution[0] / 2, slm.resolution[1] / 2)
    waist = 1e-3

    lg00 = lg_radial_amplitude(zero, waist=waist, order=0, center=center)
    lg01 = lg_radial_amplitude(zero, waist=waist, order=1, center=center)
    lg0_minus_1 = lg_radial_amplitude(zero, waist=waist, order=-1, center=center)

    center_index = (slm.resolution[1] // 2, slm.resolution[0] // 2)
    assert lg00[center_index] == pytest.approx(1.0)
    assert lg01[center_index] == pytest.approx(0.0)
    np.testing.assert_allclose(lg01, lg0_minus_1)
    assert np.isfinite(lg00).all()
    assert np.isfinite(lg01).all()


def test_superposition_matches_manual_complex_field_calculation(slm: SLM) -> None:
    canvas = slm.create_canvas()
    first = canvas.spiral(order=1)
    second = canvas.spiral(order=2)
    coefficients = (0.75, 1.25 * np.exp(1j * 0.37))

    result = superposition(first, second, coefficients=coefficients)
    field = sum(
        coefficient * np.exp(1j * mask.array)
        for coefficient, mask in zip(coefficients, (first, second))
    )
    expected = np.angle(field / np.linalg.norm(field.ravel()))

    np.testing.assert_allclose(result.array, expected)


def test_superposition_accepts_per_pixel_complex_coefficients(slm: SLM) -> None:
    canvas = slm.create_canvas()
    first = canvas.spiral(order=1)
    second = canvas.spiral(order=2)
    amplitude = np.linspace(0.2, 1.0, num=slm.shape[1])[None, :]
    amplitude = np.broadcast_to(amplitude, slm.shape)
    coefficients = (np.ones(slm.shape), amplitude * np.exp(1j * np.pi / 3))

    result = superposition(first, second, coefficients=coefficients)

    assert result.shape == slm.shape
    assert np.isfinite(result.array).all()


def test_superposition_rejects_invalid_inputs(slm: SLM) -> None:
    canvas = slm.create_canvas()
    first = canvas.spiral(order=1)
    second = canvas.spiral(order=2)

    with pytest.raises(ValueError, match="one entry"):
        superposition(first, second, coefficients=(1.0,))
    with pytest.raises(ValueError, match="shape"):
        superposition(first, second, coefficients=(1.0, np.ones((2, 2))))
    with pytest.raises(ValueError, match="non-finite"):
        superposition(first, second, coefficients=(1.0, np.nan))
    with pytest.raises(ValueError, match="zero"):
        superposition(first, first, coefficients=(1.0, -1.0))

    other_slm = SLM("holoeye", model="LETO-II", headless=True)
    with pytest.raises(ValueError, match="same SLM geometry"):
        superposition(first, other_slm.create_canvas(), coefficients=(1.0, 1.0))


def test_rgb_packing_round_trips_high_bit_depth_gray_values() -> None:
    values = np.array([[0, 1, 255, 256, 511, 512, 1023]], dtype=np.uint16)

    packed = DisplayMask(values, bits=10).to_rgb()

    assert np.array_equal(packed.to_grayscale().array, values)


def test_holoeye_headless_loads_display_and_phase_masks(slm: SLM) -> None:
    phase = slm.create_canvas().lens(f=2.0)
    display = phase.to_display(bits=8)

    with slm:
        slm.load(display)
        frame = slm.get_current_image()
        assert frame is not None
        assert frame.shape == (1080, 1920, 3)

        slm.load_phase(phase)
        slm.clear()
        assert np.all(slm.get_current_image() == 0)


def test_load_rejects_raw_display_array_with_the_wrong_resolution(slm: SLM) -> None:
    with slm:
        with pytest.raises(ValueError, match="resolution"):
            slm.load(np.zeros((3, 4), dtype=np.uint8))
        assert slm.get_current_image().shape == (1080, 1920, 3)


def test_holoeye_model_metadata_and_display_resolution(slm: SLM) -> None:
    assert slm.name == "holoeye"
    assert slm.model == "LETO-II"
    assert slm.resolution == (1920, 1080)
    assert slm.geometry.pitch_um == (6.4, 6.4)

    with slm:
        with pytest.raises(ValueError, match="resolution"):
            slm.load(DisplayMask.zeros((4, 3)))


def test_lut_round_trip_and_calibrated_conversion(tmp_path) -> None:
    path = tmp_path / "identity.lut"
    source = np.arange(256, dtype=np.uint16)
    write_lut(path, source)
    assert np.array_equal(read_lut(path), source)

    inverted = np.arange(255, -1, -1, dtype=np.uint16)
    slm = SLM("holoeye", headless=True, lut=inverted)
    encoded = slm.create_canvas().flat(0).to_display(bits=8)
    assert np.all(encoded.array == 255)


def test_cross_region_arithmetic_drops_misleading_region_metadata(slm: SLM) -> None:
    canvas = slm.create_canvas()
    left, right = canvas.partition(axis="x", ratios=(1, 1))

    assert (left.flat(1.0) - right.flat(1.0)).region_bounds is None


def test_simulated_backend_loads_slmsuite_only_when_selected() -> None:
    assert "slmsuite" not in sys.modules

    if importlib.util.find_spec("slmsuite") is None:
        with pytest.raises(ImportError, match="slmsuite"):
            SLM("simulated")
    else:
        simulated = SLM("simulated", resolution=(16, 12))
        assert "slmsuite" in sys.modules
        assert simulated.resolution == (16, 12)
