import numpy as np
import pytest

from qtools.pctrl import OptimizeResult, PolarizationController


CONFIG_TEMPLATE = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        optimal_phys_angle: 12.0
      - name: "alice1550_hwp_2"
        servo_id: 2
        waveplate: "HWP"
        order: 2
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        optimal_phys_angle: 88.0
"""


def _controller(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_file.write_text(CONFIG_TEMPLATE)
    return PolarizationController(config_path=str(config_file), mock=True)


def test_previous_optimize_result_is_a_valid_warm_start(tmp_path):
    ctrl = _controller(tmp_path)
    try:
        coarse = ctrl.optimize(
            target="alice",
            maxiter=1,
            step_size_deg=60.0,
            verbose=False,
        )
        fine = ctrl.optimize(
            target="alice",
            initial_angles=coarse,
            search_radius_deg=20.0,
            maxiter=1,
            step_size_deg=10.0,
            verbose=False,
        )
    finally:
        ctrl.close()

    assert isinstance(coarse, OptimizeResult)
    assert fine.initial_angles == pytest.approx(coarse.optimal_angles)
    for center, (lower, upper) in zip(
        fine.initial_angles, fine.search_bounds, strict=True
    ):
        assert lower == pytest.approx(max(-90.0, center - 20.0))
        assert upper == pytest.approx(min(90.0, center + 20.0))
    assert fine.step_size_deg == 10.0


def test_saved_and_mapping_radii_are_supported(tmp_path):
    ctrl = _controller(tmp_path)
    try:
        result = ctrl.optimize(
            target="alice",
            initial_angles="saved",
            search_radius_deg={
                "alice1550_qwp_1": 5.0,
                "alice1550_hwp_2": 10.0,
            },
            maxiter=1,
            step_size_deg=3.0,
            verbose=False,
        )
    finally:
        ctrl.close()

    assert result.initial_angles == pytest.approx([12.0, 88.0])
    assert result.search_bounds == pytest.approx([(7.0, 17.0), (78.0, 90.0)])


def test_simplex_uses_requested_angular_step():
    from qtools.pctrl.optimize import _build_initial_simplex

    simplex = _build_initial_simplex(
        [0.0, 0.0],
        [(-90.0, 90.0), (-90.0, 90.0)],
        12.0,
    )

    assert np.allclose(
        simplex,
        [[0.0, 0.0], [12.0, 0.0], [0.0, 12.0]],
    )


def test_search_radius_must_be_positive(tmp_path):
    ctrl = _controller(tmp_path)
    try:
        with pytest.raises(ValueError, match="greater than zero"):
            ctrl.optimize(
                target="alice",
                search_radius_deg=0.0,
                maxiter=1,
                verbose=False,
            )
    finally:
        ctrl.close()


def test_missing_saved_angle_raises(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_file.write_text(
        CONFIG_TEMPLATE.replace("        optimal_phys_angle: 12.0\n", "")
    )
    ctrl = PolarizationController(config_path=str(config_file), mock=True)
    try:
        with pytest.raises(ValueError, match="No saved optimal angle"):
            ctrl.optimize(
                target="alice",
                initial_angles="saved",
                maxiter=1,
                verbose=False,
            )
    finally:
        ctrl.close()
