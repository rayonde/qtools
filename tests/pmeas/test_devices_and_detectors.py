"""Tests for unified devices schema, dual detectors, task defaults, and device-keyed calibrations sync."""

import tempfile
from pathlib import Path
from qtools.pmeas.config import ConfigManager
from qtools.pmeas.api import MeasController, TaskController


def test_devices_schema_and_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "polmeas_config.yaml"
        cfg = ConfigManager.resolve(cfg_file)
        cfg._cfg["devices"] = []

        cfg.upsert_device(key="55119234", id="alice", name="alice1550_basis_hwp",
                          optical_path="alice", port="COM3", serial="55119234")
        cfg.save()

        cfg2 = ConfigManager.resolve(cfg_file)

        assert "devices" in cfg2._cfg
        devices = cfg2.get_all_devices()
        assert len(devices) == 1
        assert devices[0]["name"] == "alice1550_basis_hwp"
        assert devices[0]["optical_path"] == "alice"
        assert devices[0]["id"] == "alice"

        dev_by_id = cfg2.get_device("alice")
        assert dev_by_id is not None
        assert dev_by_id["name"] == "alice1550_basis_hwp"

        dev_by_path = cfg2.get_device("alice")
        assert dev_by_path is not None
        assert dev_by_path["serial"] == "55119234"


def test_task_detectors_and_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "polmeas_config.yaml"
        cfg = ConfigManager.resolve(cfg_file)

        cfg.set_value("detectors.powermeter", {"backend": "PM100D", "port": "USB0::0x1313::P0001"})
        cfg.set_value("detectors.tdc", {"backend": "quTAG", "port": "usb:0"})
        cfg.set_value("calibration.detector", "powermeter")
        cfg.set_value("calibration.meas_type", "power")
        cfg.set_value("scan.detector", "tdc")
        cfg.set_value("scan.meas_type", "pairs")
        cfg.save()

        ctrl = MeasController(config_path=str(cfg_file))
        det_cal, meas_cal = ctrl.get_default_detector(task="calibration")
        assert det_cal == "powermeter"
        assert meas_cal == "power"

        det_scan, meas_scan = ctrl.get_default_detector(task="scan")
        assert det_scan == "tdc"
        assert meas_scan == "pairs"


def test_device_keyed_calibrations_and_sync():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "polmeas_config.yaml"
        cfg = ConfigManager.resolve(cfg_file)

        cfg.register_device(serial="55119234", name="alice1550_basis_hwp", optical_path="alice", role="basis")
        cfg.save()

        cal_data = {
            "timestamp": "2026-07-24 04:00:00",
            "theta_0": 15.2,
            "fast_axis": 15.2,
            "visibility": 0.98,
            "bases": {"H": 15.2, "V": 60.2, "D": 37.7, "A": 82.7},
            "cal_file": "output/calibration_hwp_123.png",
        }
        cfg.add_calibration("alice1550_basis_hwp", cal_data)
        cfg.save()

        cfg2 = ConfigManager.resolve(cfg_file)
        stored_cal = cfg2.get_calibration("alice1550_basis_hwp")
        assert stored_cal is not None
        assert stored_cal["theta_0"] == 15.2
        assert stored_cal["bases"]["H"] == 15.2

        dev = cfg2.get_device("alice1550_basis_hwp")
        assert dev is not None
        # zero_offset is NOT synced from calibration — it is a manual motor parameter
        assert dev["zero_offset"] == 0.0
        # theta_0 lives in the device's calibration sub-dict
        assert dev.get("calibration", {}).get("theta_0") == 15.2
        # bases are still synced to top-level
        assert dev["bases"]["H"] == 15.2
        assert dev["calibration"]["fast_axis"] == 15.2
        assert dev["calibration"]["cal_file"] == "output/calibration_hwp_123.png"


def test_motor_manager_get_motor_delegation(monkeypatch):
    from types import SimpleNamespace

    from qtools.pmeas import motor_manager
    from qtools.pmeas.motor_manager import MotorManager

    fake_motor = SimpleNamespace(port="COM3")
    connections = []

    def fake_get_motor(*, port=None, target=None, blocking=True, backend=None):
        if port != "COM3":
            raise ConnectionError(f"No simulated motor for {target}")
        connections.append((port, blocking, backend))
        return fake_motor

    monkeypatch.setattr(motor_manager, "_check_availability", lambda port: port == "COM3")
    monkeypatch.setattr(motor_manager, "sm_get_motor", fake_get_motor)

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "polmeas_config.yaml"
        cfg = ConfigManager.resolve(cfg_file)
        cfg.upsert_device(
            key="55119234",
            id="alice",
            name="alice1550_basis_hwp",
            optical_path="alice",
            port="COM3",
            _serial="55119234",
        )
        cfg.save()

        mm = MotorManager(cfg)
        motor = mm.get_motor("alice")
        assert motor is fake_motor
        assert motor.port == "COM3"

        # Check caching and alias matching
        assert mm.get_motor("alice") is motor
        assert mm.get_motor("alice1550_basis_hwp") is motor
        assert len(connections) == 1
        assert connections[0][:2] == ("COM3", False)


