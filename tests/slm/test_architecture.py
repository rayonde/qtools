"""Tests for the region-oriented qtools.slm API."""

from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pytest

from qtools.slm import DisplayMask, PhaseMask, PhaseRegion, SLM, list_backends
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
