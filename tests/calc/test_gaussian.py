"""Numerical and public API regression tests for Gaussian beam analysis."""

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from qtools.calc import gaussian
from qtools.calc.gaussian._fit import _evaluate


def image(shape=(80, 120), beams=((120, 57.4, 38.2, 11.0, 5.0, 0.43),), offset=7.0):
    """Independent quadratic-form implementation of synthetic image fixtures."""
    y, x = np.indices(shape, dtype=float)
    result = np.full(shape, float(offset))
    for amplitude, cx, cy, sx, sy, theta in beams:
        c, s = np.cos(theta), np.sin(theta)
        a = c * c / (2 * sx * sx) + s * s / (2 * sy * sy)
        b = c * s * (1 / (2 * sx * sx) - 1 / (2 * sy * sy))
        d = s * s / (2 * sx * sx) + c * c / (2 * sy * sy)
        result += amplitude * np.exp(
            -(a * (x - cx) ** 2 + 2 * b * (x - cx) * (y - cy) + d * (y - cy) ** 2)
        )
    return result


def test_public_imports_remain_lazy():
    script = """
import sys
import qtools
assert 'numpy' not in sys.modules
assert qtools.calc.gaussian.fit
from qtools.calc import gaussian
assert gaussian is qtools.calc.gaussian
assert all(name not in sys.modules for name in ['cv2', 'lmfit', 'matplotlib.pyplot', 'qtools.camera', 'qtools.tdc'])
try:
    qtools.calc.unknown
except AttributeError:
    pass
else:
    raise AssertionError('Unknown subpackage must raise AttributeError')
"""
    subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )


@pytest.mark.parametrize("theta", [-1.3, -0.4, 0.0, 0.65, 1.4])
def test_recovers_rotating_gaussian(theta):
    expected = (120, 57.4, 38.2, 11.0, 5.0, theta)
    result = gaussian.fit(image(beams=(expected,), offset=-9))
    actual = result.beam
    np.testing.assert_allclose(
        [
            actual.amplitude,
            actual.xo,
            actual.yo,
            actual.sigma_x,
            actual.sigma_y,
            actual.theta,
        ],
        expected,
        atol=1e-6,
    )
    assert result.offset == pytest.approx(-9)
    assert result.rmse < 1e-7
    assert result.r_squared == pytest.approx(1)
    assert result.fitted_image.shape == result.data.shape
    assert not result.data.flags.writeable
    assert not result.fitted_image.flags.writeable


def test_fixed_theta_preserves_x_y_width_order():
    result = gaussian.fit(image(beams=((100, 53, 42, 4, 12, 0),)), fix_theta=True)
    assert result.beam.sigma == pytest.approx((4, 12), abs=1e-6)
    assert result.beam.theta == 0


def test_rotating_fit_canonicalizes_swapped_axes():
    result = gaussian.fit(image(beams=((100, 53, 42, 4, 12, 0.2),)))
    assert result.beam.sigma == pytest.approx((12, 4), abs=1e-6)
    assert result.beam.theta == pytest.approx(0.2 - np.pi / 2)


def test_high_bit_depth_and_negative_background():
    data = np.rint(
        image(beams=((42_000, 57.4, 38.2, 11, 5, 0.43),), offset=3500)
    ).astype(np.uint16)
    result = gaussian.fit(data)
    assert result.beam.amplitude == pytest.approx(42_000, rel=1e-4)
    assert result.beam.center == pytest.approx((57.4, 38.2), abs=0.002)
    assert result.offset == pytest.approx(3500, abs=0.1)
    assert result.rmse < 0.3


def test_multi_beam_joint_fit_and_stable_order():
    beams = ((100, 30, 32, 8, 4, 0.3), (60, 92, 45, 7, 5, -0.5))
    result = gaussian.fit(image(beams=beams), n_beams=2)
    assert len(result.beams) == 2
    for fitted, expected in zip(result.beams, beams):
        assert fitted.amplitude == pytest.approx(expected[0], abs=1e-5)
        assert fitted.center == pytest.approx(expected[1:3], abs=1e-5)
        assert fitted.sigma == pytest.approx(expected[3:5], abs=1e-5)
        assert fitted.theta == pytest.approx(expected[5], abs=1e-5)
    assert result.rmse < 1e-6
    assert result.values["beam0_xo"] == pytest.approx(30)
    with pytest.raises(ValueError, match="result.beams"):
        _ = result.beam


def test_three_beam_uint16_fit():
    beams = (
        (30000, 35, 40, 8, 4, 0.3),
        (60000, 100, 80, 9, 5, -0.4),
        (10000, 165, 40, 7, 3, 0.6),
    )
    data = np.rint(image(shape=(128, 200), beams=beams, offset=1500)).astype(np.uint16)
    result = gaussian.fit(data, n_beams=3)
    assert len(result.beams) == 3
    for beam, expected in zip(result.beams, beams):
        assert beam.center == pytest.approx(expected[1:3], abs=0.01)
        assert beam.sigma == pytest.approx(expected[3:5], abs=0.01)
    assert result.rmse < 0.3


def test_manual_centers_fit_overlapping_beams():
    beams = ((100, 52, 38, 9, 5, 0), (65, 64, 38, 8, 5, 0))
    result = gaussian.fit(
        image(beams=beams),
        n_beams=2,
        fix_theta=True,
        centers=[(52, 38), (64, 38)],
        max_nfev=500,
    )
    assert result.rmse < 1e-5
    np.testing.assert_allclose(
        [b.center for b in result.beams], [(52, 38), (64, 38)], atol=1e-4
    )


def test_threshold_and_distance_affect_peak_detection():
    data = image(beams=((100, 30, 40, 6, 5, 0), (15, 80, 40, 6, 5, 0)))
    with pytest.raises(ValueError, match="requested 2"):
        gaussian.find_beam_centers(data, 2, threshold_factor=0.5)
    centers = gaussian.find_beam_centers(data, 2, threshold_factor=0.05)
    np.testing.assert_allclose(centers, [(30, 40), (80, 40)], atol=1)
    with pytest.raises(ValueError, match="requested 2"):
        gaussian.find_beam_centers(data, 2, threshold_factor=0.05, min_distance=60)


def test_quantized_flat_peak_is_not_counted_twice():
    data = image(shape=(60, 80), beams=((200, 39.5, 29.5, 8, 6, 0),)).astype(np.uint8)
    with pytest.raises(ValueError, match="requested 2"):
        gaussian.find_beam_centers(data, 2)


@pytest.mark.parametrize("fix_theta", [False, True])
def test_analytical_jacobian_matches_central_differences(fix_theta):
    parameters = [2, 4, 3, 2, 1]
    if not fix_theta:
        parameters += [0.4]
    parameters = np.array(parameters + [0.1], dtype=float)
    x, y = np.meshgrid(np.arange(9.0), np.arange(7.0))
    x, y = x.ravel(), y.ravel()
    actual = _evaluate(parameters, x, y, 1, fix_theta, jacobian=True)
    numerical = np.empty_like(actual)
    for i in range(len(parameters)):
        delta = np.zeros_like(parameters)
        delta[i] = 1e-5
        numerical[:, i] = (
            _evaluate(parameters + delta, x, y, 1, fix_theta)
            - _evaluate(parameters - delta, x, y, 1, fix_theta)
        ) / 2e-5
    np.testing.assert_allclose(actual, numerical, rtol=1e-6, atol=1e-9)


def test_sampling_and_scaled_summary():
    data = image(shape=(240, 320), beams=((100, 155, 112, 24, 12, 0.4),))
    result = gaussian.fit(data, max_points=10_000, pixel_size=3.75, unit="um")
    full = gaussian.fit(data, max_points=None)
    assert result.sample_step > 1
    assert full.sample_step == 1
    assert result.beam.center == pytest.approx(full.beam.center, abs=1e-5)
    summary = result.to_dict()
    assert summary["beams"][0]["center"] == pytest.approx((581.25, 420))
    assert summary["beams"][0]["waist"] == pytest.approx((180, 90))
    assert summary["beams"][0]["fwhm"] == pytest.approx(
        np.array((24, 12)) * 3.75 * 2 * np.sqrt(2 * np.log(2))
    )
    assert summary["unit"] == "um"
    json.dumps(summary)
    assert result.best_fit.shape == (data.size,)
    assert result.residual.shape == data.shape


@pytest.mark.parametrize(
    "data",
    [
        np.zeros((5, 5)),
        np.ones((4, 5)),
        np.ones(3),
        np.ones((3, 4, 3)),
        [[1, np.nan], [2, 3]],
        [[1, np.inf], [2, 3]],
        np.ones((3, 3), dtype=complex),
    ],
)
def test_rejects_invalid_image_data(data):
    with pytest.raises(ValueError):
        gaussian.fit(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_beams": 0},
        {"n_beams": 1.5},
        {"n_beams": True},
        {"pixel_size": 0},
        {"pixel_size": np.nan},
        {"max_points": 0},
        {"max_nfev": 0},
        {"unit": ""},
        {"threshold_factor": 0},
        {"threshold_factor": 1},
        {"min_distance": -1},
        {"centers": [(1, 2), (3, 4)]},
        {"centers": [(300, 2)]},
        {"centers": [(np.nan, 2)]},
    ],
)
def test_rejects_invalid_options(kwargs):
    with pytest.raises(ValueError):
        gaussian.fit(image(), **kwargs)


def test_nonconvergence_is_reported():
    with pytest.raises(RuntimeError, match="did not converge"):
        gaussian.fit(image(), max_nfev=1)


@pytest.mark.parametrize("bit_depth", [8, 16])
def test_raw_reading_inference_and_explicit_shape(tmp_path, bit_depth):
    dtype = np.dtype("u1" if bit_depth == 8 else "<u2")
    data = np.arange(48, dtype=dtype).reshape(6, 8)
    if bit_depth == 16:
        data *= 1000
    path = tmp_path / "beam.raw"
    data.tofile(path)
    np.testing.assert_array_equal(gaussian.read_raw(path, bit_depth=bit_depth), data)
    np.testing.assert_array_equal(
        gaussian.read_raw(path, bit_depth=bit_depth, shape=(8, 6)), data.reshape(8, 6)
    )
    with pytest.raises(ValueError, match="sample count"):
        gaussian.read_raw(path, bit_depth=bit_depth, shape=(4, 4))


def test_raw_rejects_ambiguous_or_truncated_data(tmp_path):
    path = tmp_path / "beam.raw"
    path.write_bytes(bytes(range(35)))
    with pytest.raises(ValueError, match="shape"):
        gaussian.read_raw(path)
    assert gaussian.read_raw(path, shape=(5, 7)).shape == (5, 7)
    with pytest.raises(ValueError, match="byte count"):
        gaussian.read_raw(path, bit_depth=16)
    with pytest.raises(ValueError, match="bit_depth"):
        gaussian.read_raw(path, bit_depth=12)
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="byte count"):
        gaussian.read_raw(path)


def test_standard_image_preserves_16bit_and_supports_rgb(tmp_path):
    from PIL import Image

    data = np.rint(image(beams=((40000, 57, 38, 11, 5, 0.3),), offset=2000)).astype(
        np.uint16
    )
    path = tmp_path / "beam.tif"
    Image.fromarray(data).save(path)
    np.testing.assert_array_equal(gaussian.read_image(path), data)
    assert gaussian.fit(path).beam.amplitude == pytest.approx(40000, rel=1e-4)
    rgb = tmp_path / "color.png"
    Image.fromarray(np.zeros((5, 6, 3), dtype=np.uint8)).save(rgb)
    assert gaussian.read_image(rgb).shape == (5, 6)


def test_profile_compatibility_and_frame_moments(tmp_path):
    from qtools.calc.gaussian.gauss_fit import Profile, gauss_flat

    data = image(beams=((200, 55, 4, 6, 2, 0),))
    profile = Profile()
    with pytest.raises(ValueError, match="Load"):
        profile.fitted()
    profile.frame2array(data)
    assert np.isfinite(profile.x_bar)
    assert np.isfinite(profile.y_bar)
    assert np.isfinite(profile.angle)
    assert min(profile.eig) > 0
    assert profile.maxrow_col() == (4, 55)
    np.testing.assert_allclose(profile.rowmaxs[1], data.max(axis=1))
    np.testing.assert_allclose(profile.colmaxs[1], data.max(axis=0))
    result = profile.fitted(fix_theta=True)
    assert isinstance(
        profile.fitted_multi_beam(1, fix_theta=True), gaussian.GaussianFitResult
    )
    y, x = np.indices(data.shape)
    modeled = gauss_flat(np.column_stack([x.ravel(), y.ravel()]), **result.values)
    np.testing.assert_allclose(modeled, result.best_fit)
    assert result.beam.center == pytest.approx((55, 4), abs=1e-4)
    path = tmp_path / "frame.raw"
    data.astype(np.uint8).tofile(path)
    profile.raw2array(path, shape=data.shape)
    assert profile.result is None


def test_failed_profile_load_preserves_previous_result():
    profile = gaussian.Profile(image())
    result = profile.fitted()
    original_data = profile.data.copy()
    original_center = (profile.x_bar, profile.y_bar)
    with pytest.raises(ValueError, match="constant image"):
        profile.frame2array(np.zeros((20, 30)))
    np.testing.assert_array_equal(profile.data, original_data)
    assert profile.result is result
    assert (profile.x_bar, profile.y_bar) == original_center


def test_plot_uses_rotated_full_model_without_showing(monkeypatch, tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    monkeypatch.setattr(
        plt, "show", lambda: pytest.fail("plot must not show by default")
    )
    data = image(beams=((100, 30, 32, 8, 4, 0.3), (60, 92, 45, 7, 5, -0.5)))
    result = gaussian.fit(data, n_beams=2, pixel_size=3.75, unit="um")
    figure = gaussian.plot(result)
    for i, beam in enumerate(result.beams):
        actual = figure.axes[1].lines[2 * i + 1].get_ydata()
        np.testing.assert_allclose(
            actual, result.evaluate(np.arange(data.shape[1]), round(beam.yo))
        )
    output = tmp_path / "fit.png"
    figure.savefig(output)
    plt.close(figure)
    assert output.stat().st_size > 0


def test_vectorized_beam_removal_preserves_input():
    from qtools.calc.gaussian.create_single_beam_raw import remove_beam

    data = np.full((10, 15), 1000, dtype=np.uint16)
    actual = remove_beam(data, (3, 5), radius=2)
    y, x = np.indices(data.shape)
    expected = np.where((y - 3) ** 2 + (x - 5) ** 2 < 4, 0, 1000)
    np.testing.assert_array_equal(actual, expected)
    assert np.all(data == 1000)
    assert actual.dtype == data.dtype


@pytest.mark.parametrize(
    "module", ["qtools.calc.gaussian", "qtools.calc.gaussian.gauss_fit"]
)
def test_module_cli_emits_json_without_gui(tmp_path, module):
    path = tmp_path / "beam.raw"
    np.rint(image(shape=(60, 80), beams=((150, 35, 27, 9, 4, 0),))).astype(
        np.uint8
    ).tofile(path)
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            str(path),
            "-fit",
            "-xy",
            "--pixel-size",
            "3.75",
            "--unit",
            "um",
        ],
        env={**os.environ, "MPLBACKEND": "Agg"},
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(process.stdout)
    assert output["success"]
    assert output["beams"][0]["center"] == pytest.approx((131.25, 101.25), abs=0.1)
