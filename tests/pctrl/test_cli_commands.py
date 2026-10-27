from unittest.mock import patch, MagicMock
from qtools.pctrl.utils import run_reset, run_direct_set
from qtools.pctrl.backends import COMM_SUCCESS


class FakePHSts:
    def __init__(self):
        self.writes = []
        self.port_handler = None
        self.positions = {}

    def WritePosEx(self, sid, pos, speed, acc):
        self.writes.append((sid, pos, speed, acc))
        return COMM_SUCCESS

    def ReadPosSpeed(self, sid):
        return 512, 0, COMM_SUCCESS, 0

    def write1ByteTxRx(self, sid, reg, val):
        return COMM_SUCCESS

    def ReadMoving(self, sid):
        return 0, COMM_SUCCESS, 0

    def move(self, sid, pos, speed, acc):
        self.writes.append((sid, pos, speed, acc))
        return 0, 0

    def close(self):
        pass


def test_run_reset_connection_reuse(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
channels:
  - path: "alice"
    wavelength: 1550
    name: "test channel"
    servos:
      - name: "alice1550_qwp_1"
        servo_id: 1
        zero_position: 512
"""
    config_file.write_text(config_content)

    fake_sts = FakePHSts()
    run_reset(config=str(config_file), ph_sts=fake_sts)
    assert len(fake_sts.writes) == 1
    assert fake_sts.writes[0] == (1, 512, 114, 50)


def test_run_limit_writes_eeprom(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1560
    servos:
      - name: "alice1560_qwp_1"
        servo_id: 1
        zero_position: 426
        deg_per_step: 0.2933
        phy_angle_range: 300.0
        phy_position_range: 1023
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    from qtools.pctrl.backends import ServoBackend
    from qtools.pctrl.utils import run_limit
    from qtools.pctrl.config import ConfigManager

    backend = ServoBackend(port="MOCK_PORT", baudrate=1000000, servo_type="scs", mock=True)
    run_limit(config=str(config_file), target="alice1560_qwp_1",
              min_angle=-45.0, max_angle=45.0, ph_sts=backend)

    cfg = ConfigManager(str(config_file))
    cfg.load()
    s = cfg.get_servo("alice1560_qwp_1")
    assert s["min_angle"] == -45.0
    assert s["max_angle"] == 45.0
    assert s["min_position"] == 273   # round(426 - 45/0.2933)
    assert s["max_position"] == 579   # round(426 + 45/0.2933)
    # raw encoder positions read back from the (mock) EEPROM registers
    assert backend.get_limits(1)[0][2:] == (273, 579)


def test_run_set_middle_writes_eeprom(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1560
    servos:
      - name: "alice1560_qwp_1"
        servo_id: 1
        zero_position: 512
        deg_per_step: 0.2933
        phy_angle_range: 300.0
        phy_position_range: 1023
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    from qtools.pctrl.backends import ServoBackend
    from qtools.pctrl.utils import run_set_middle
    from qtools.pctrl.config import ConfigManager

    backend = ServoBackend(port="MOCK_PORT", baudrate=1000000, servo_type="scs", mock=True)
    backend.set_pos(1, 426)
    run_set_middle(config=str(config_file), target="alice1560_qwp_1", ph_sts=backend)

    cfg = ConfigManager(str(config_file))
    cfg.load()
    s = cfg.get_servo("alice1560_qwp_1")
    assert s["zero_position"] == 426
    assert s["min_angle"] == -90.0
    assert s["max_angle"] == 90.0
    assert s["min_position"] == 119   # round(426 - 90/0.2933)
    assert s["max_position"] == 733   # round(426 + 90/0.2933)
    assert abs(s["phy_zero_angle"] - 124.9267) < 1e-6
    assert backend.get_limits(1)[0][2:] == (119, 733)


def test_run_set_middle_clamps_at_physical_range(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1560
    servos:
      - name: "alice1560_qwp_1"
        servo_id: 1
        zero_position: 512
        deg_per_step: 0.2933
        phy_angle_range: 300.0
        phy_position_range: 1023
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    from qtools.pctrl.backends import ServoBackend
    from qtools.pctrl.utils import run_set_middle
    from qtools.pctrl.config import ConfigManager

    backend = ServoBackend(port="MOCK_PORT", baudrate=1000000, servo_type="scs", mock=True)
    backend.set_pos(1, 10)
    run_set_middle(config=str(config_file), target="alice1560_qwp_1", ph_sts=backend)

    cfg = ConfigManager(str(config_file))
    cfg.load()
    s = cfg.get_servo("alice1560_qwp_1")
    assert s["min_position"] == 0        # round(10 - 90/0.2933) = -297 clamps to 0
    assert s["max_position"] == 317      # round(10 + 90/0.2933)
    assert backend.get_limits(1)[0][2] == 0


def test_servo_sweep_bounds_consistent_after_set_home():
    """Once set-home writes consistent min/max_position, the sweep spans ±90."""
    from qtools.pctrl.calibration import servo_sweep_bounds

    s = {
        "zero_position": 426,
        "min_position": 119,
        "max_position": 733,
        "deg_per_step": 0.2933,
        "min_angle": -90.0,
        "max_angle": 90.0,
    }
    lo, hi = servo_sweep_bounds(s)
    assert abs(lo - (-90.0)) < 0.1
    assert abs(hi - 90.0) < 0.1


def test_run_calibration_mock(tmp_path):
    """Calibration entrypoint accepts mock=True and does not require real sensors."""
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
        deg_per_step: 0.293
        min_angle: -90.0
        max_angle: 90.0
        retardance: 0.25
"""
    config_file.write_text(config_content)

    from qtools.pctrl.calibration import run_calibration

    # Fast mock calibration; may not update config if fidelity check fails on flat mock signal
    run_calibration(
        config=str(config_file),
        target="alice1550_qwp_1",
        basis="h",
        fast=True,
        mock=True,
    )


def test_servo_sweep_bounds_honors_software_limits():
    """Sweep bounds clamp to min_angle/max_angle, not just the encoder range."""
    from qtools.pctrl.calibration import servo_sweep_bounds, generate_sweep

    # Off-centre zero within a wide encoder range: the encoder-only bounds
    # would reach +115.3 deg, exceeding the configured +90 software limit.
    s = {
        "zero_position": 426,
        "min_position": 205,
        "max_position": 819,
        "deg_per_step": 0.2933,
        "min_angle": -90.0,
        "max_angle": 90.0,
    }
    lo, hi = servo_sweep_bounds(s)
    assert hi <= 90.0
    assert lo >= -90.0
    assert abs(lo - (-64.8)) < 0.1  # left side stays at the encoder bound

    encs, actuals = generate_sweep(5.0, lo, hi, s["deg_per_step"], s["zero_position"])
    # Encoder steps are discrete (deg_per_step), so allow one step of slack.
    assert max(actuals) <= 90.0 + s["deg_per_step"]
    assert min(actuals) >= -90.0 - s["deg_per_step"]


def test_run_direct_set_id_mock(tmp_path):
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
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
"""
    config_file.write_text(config_content)

    from qtools.pctrl.utils import run_direct_set_id
    from qtools.pctrl.config import ConfigManager

    run_direct_set_id(config=str(config_file), ids=[1, 5], mock=True)

    cfg = ConfigManager(str(config_file))
    cfg.load()
    s = cfg.get_servo("alice1550_qwp_1")
    assert s["servo_id"] == 5
