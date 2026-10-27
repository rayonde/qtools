import pytest
import numpy as np
from qtools.pctrl import PolarizationController


def test_polarization_controller_api(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    # Initialize high-level controller API in mock mode
    with PolarizationController(config_path=str(config_file), mock=True) as ctrl:
        # Verify we can read the initial sensor value
        val = ctrl.get_sensor_value()
        assert isinstance(val, float)

        # Move target servo
        ctrl.set_angles(target="alice1550_qwp_1", angles=45.0)

        # Read back current angles
        angles = ctrl.get_angles(target="alice1550_qwp_1")
        assert "alice1550_qwp_1" in angles
        assert pytest.approx(angles["alice1550_qwp_1"], abs=1.0) == 45.0


def test_polarization_controller_api_custom_metric(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    # Initialize the controller in mock mode
    ctrl = PolarizationController(config_path=str(config_file), mock=True)

    # Custom metric peaks when physical angle is close to 30 deg
    def mock_entanglement(_meas_mgr):
        angles = ctrl.get_angles(target="alice1550_qwp_1")
        current_angle = angles.get("alice1550_qwp_1", 0.0) or 0.0
        concurrence = float(np.exp(-((current_angle - 30.0) ** 2) / 10000.0))
        return concurrence

    res = ctrl.optimize(
        target="alice1550_qwp_1",
        metric_fn=mock_entanglement,
        maxiter=15,
        step_size_deg=10.0,
    )
    assert res is not None
    assert len(res) == 1
    ctrl.close()
