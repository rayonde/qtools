"""Tests for unified devices schema, dual detectors, task defaults, and device-keyed calibrations sync."""

import argparse
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qtools.motor.backends.motor import MotorDeviceInfo
from qtools.pmeas.api import MeasController, TaskController
from qtools.pmeas.commands.config import cmd_config
from qtools.pmeas.config import ConfigManager


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
        assert devices[0]["id"] == 1

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

def test_multiple_devices_on_one_optical_path_remain_distinct():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "polmeas_config.yaml"
        cfg = ConfigManager.resolve(cfg_file)
        cfg._cfg["devices"] = []
        cfg.upsert_device(
            key="SN-HWP",
            id="SN-HWP",
            name="alice_547_basis_hwp",
            optical_path="alice",
            serial="SN-HWP",
            port="COM1",
            role="basis",
            waveplate="hwp",
        )
        cfg.upsert_device(
            key="SN-QWP",
            id="SN-QWP",
            name="alice_547_basis_qwp",
            optical_path="alice",
            serial="SN-QWP",
            port="COM2",
            role="basis",
            waveplate="qwp",
        )

        assert len(cfg.get_all_devices()) == 2
        assert [dev["id"] for dev in cfg.get_all_devices()] == [1, 2]
        with pytest.raises(ValueError, match="ambiguous"):
            cfg.get_device("alice")
        assert cfg.get_device("alice:hwp")["serial"] == "SN-HWP"
        assert cfg.get_device("alice/qwp")["serial"] == "SN-QWP"

        cfg.save()
        reloaded = ConfigManager.resolve(cfg_file)
        assert len(reloaded.get_devices_by_group("alice")) == 2


def test_configured_basis_angles_are_not_overwritten_by_waveplate_type(tmp_path):
    import yaml

    cfg_file = tmp_path / "polmeas_config.yaml"
    configured_hwp_bases = {
        "H": 11.25,
        "D": 33.75,
        "A": 78.75,
        "R": 12.5,
    }
    expected_hwp_bases = {
        **configured_hwp_bases,
        "V": 0.0,
        "L": 0.0,
    }
    configured_qwp_bases = {
        "H": 3.0,
        "V": 48.0,
        "D": 25.5,
        "A": 70.5,
        "R": 24.21,
        "L": 114.21,
    }
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "devices": [
                    {
                        "id": 1,
                        "name": "alice_hwp",
                        "optical_path": "alice",
                        "serial": "HWP-1",
                        "waveplate": "hwp",
                        "calibration": {"theta_0": 10.0},
                        "bases": configured_hwp_bases,
                    },
                    {
                        "id": 2,
                        "name": "alice_qwp",
                        "optical_path": "alice",
                        "serial": "QWP-1",
                        "waveplate": "qwp",
                        "calibration": {"theta_0": 69.21},
                        "bases": configured_qwp_bases,
                    },
                ],
                "calibration_results": {
                    "HWP-1": {
                        "theta_0": 10.0,
                        "bases": configured_hwp_bases,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager.resolve(cfg_file)

    assert cfg.get_device("HWP-1")["bases"] == expected_hwp_bases
    assert cfg.get_device("QWP-1")["bases"] == configured_qwp_bases
    assert cfg.calibration_results["HWP-1"]["bases"] == expected_hwp_bases

    cfg.save()
    reloaded = ConfigManager.resolve(cfg_file)

    assert reloaded.get_device("HWP-1")["bases"] == expected_hwp_bases
    assert reloaded.get_device("QWP-1")["bases"] == configured_qwp_bases


def test_config_wizard_prompts_experiment_and_keeps_three_motors(monkeypatch, tmp_path):
    motors = [
        MotorDeviceInfo("COM3", "APT USB", "k10cr1", "55119234"),
        MotorDeviceInfo("27255044", "KDC101", "kdc101", "27255044"),
        MotorDeviceInfo("27255094", "KDC101", "kdc101", "27255094"),
    ]
    answers = iter([
        "Bell test", "Alice",
        "", "",
        "alice", "basis", "hwp", "547",
        "alice", "basis", "qwp", "547",
        "bob", "basis", "qwp", "547",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        "qtools.pmeas.commands.config._auto_scan_tdc",
        lambda: {"backend": "exp_s15_tdc1", "port": "COM17"},
    )
    monkeypatch.setattr(
        "qtools.pmeas.commands.config._auto_scan_powermeter",
        lambda: {"backend": "", "port": ""},
    )
    monkeypatch.setattr(
        "qtools.motor.backends.motor.list_motors",
        lambda: motors,
    )

    cfg_file = tmp_path / "polmeas_config.yaml"
    args = argparse.Namespace(config=str(cfg_file), date=None, sub=None)
    cmd_config(args)

    cfg = ConfigManager.resolve(cfg_file)
    assert cfg.get("exp") == "Bell test"
    assert cfg.get("author") == "Alice"
    assert cfg.get("detectors.tdc") == {
        "backend": "exp_s15_tdc1",
        "port": "COM17",
    }
    assert len(cfg.get_all_devices()) == 3
    assert [dev["id"] for dev in cfg.get_all_devices()] == [1, 2, 3]
    assert len(cfg.get_devices_by_group("alice")) == 2
    assert {dev["name"] for dev in cfg.get_all_devices()} == {
        "alice_547_basis_hwp",
        "alice_547_basis_qwp",
        "bob_547_basis_qwp",
    }
    hwp = cfg.get_device("alice:hwp")
    qwp = cfg.get_device("alice:qwp")
    assert all(value == 0.0 for value in hwp["bases"].values())
    assert all(value == 0.0 for value in qwp["bases"].values())


def test_scan_detectors_uses_public_tdc_discovery(monkeypatch, tmp_path):
    cfg = ConfigManager.resolve(tmp_path / "polmeas_config.yaml")
    monkeypatch.setattr(
        "qtools.tdc.list_tdc",
        lambda method="all", timeout=1.0: [
            SimpleNamespace(backend_name="exp_s15_tdc1", device_path="COM17")
        ],
    )
    monkeypatch.setattr(
        "qtools.powermeter.cli.auto_detect_connected_device",
        lambda: ("", ""),
    )

    detectors = cfg.scan_detectors(save=False)

    assert detectors["tdc"] == {
        "backend": "exp_s15_tdc1",
        "port": "COM17",
    }

def test_original_numeric_id_config_round_trips_unchanged(tmp_path):
    import yaml

    cfg_file = tmp_path / "polmeas_config.yaml"
    original = {
        "version": 1,
        "exp": "legacy",
        "devices": [
            {
                "id": 1,
                "name": "alice_1560_basis_hwp",
                "optical_path": "alice",
                "serial": "55119234",
                "role": "basis",
                "waveplate": "hwp",
            },
            {
                "id": 2,
                "name": "bob_1560_basis_hwp",
                "optical_path": "bob",
                "serial": "55105664",
                "role": "basis",
                "waveplate": "hwp",
            },
        ],
        "detectors": {
            "tdc": {"backend": "exp_s15_tdc1", "port": "COM7"},
            "powermeter": {"backend": "s15", "port": "COM5"},
        },
        "calibration_results": {"55105664": {"id": "2"}},
    }
    cfg_file.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    cfg = ConfigManager.resolve(cfg_file)
    assert [dev["id"] for dev in cfg.get_all_devices()] == [1, 2]
    cfg.save()

    saved = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert [dev["id"] for dev in saved["devices"]] == [1, 2]
    assert saved["calibration_results"]["55105664"]["id"] == "2"

def test_target_angles_include_all_basis_labels():
    from qtools.pmeas.analysis.jones import compute_target_angles

    hwp = compute_target_angles(10.0, "hwp")
    assert set(hwp) == {"H", "V", "D", "A", "R", "L"}
    assert hwp["H"] == 10.0
    assert hwp["R"] == 0.0
    assert hwp["L"] == 0.0

    qwp = compute_target_angles(10.0, "qwp")
    assert set(qwp) == {"H", "V", "D", "A", "R", "L"}
    assert all(qwp[key] == 0.0 for key in ("H", "V", "D", "A"))
    assert qwp["R"] == -35.0
    assert qwp["L"] == 55.0

def test_motor_status_lists_all_devices_with_bases_and_angles(monkeypatch, tmp_path, capsys):
    from qtools.pmeas.cli import _print_motor_status

    cfg_file = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_file)
    cfg._cfg["devices"] = []
    cfg.upsert_device(
        key="27255044", name="alice_547_basis_hwp", optical_path="alice",
        serial="27255044", port="27255044", backend="kdc101", waveplate="hwp",
    )
    cfg.upsert_device(
        key="55119234", name="bob_1550_basis_hwp", optical_path="bob",
        serial="55119234", port="COM3", backend="k10cr1", waveplate="hwp",
    )
    cfg.upsert_device(
        key="27255094", name="alice_547_basis_qwp", optical_path="alice",
        serial="27255094", port="27255094", backend="kdc101", waveplate="qwp",
    )
    cfg.get_device("alice_547_basis_qwp")["bases"].update({"R": -45.0, "L": 45.0})
    cfg.save()

    class FakeMotor:
        def __init__(self):
            self.is_connected = False

        def connect(self):
            self.is_connected = True
            return True

        def disconnect(self):
            self.is_connected = False

        def get_position(self):
            return 12.3

    class FakeManager:
        def __init__(self, _cfg):
            self.items = []
            for dev in _cfg.get_all_devices():
                self.items.append(
                    {
                        "id": dev["id"],
                        "name": dev["name"],
                        "optical_path": dev["optical_path"],
                        "role": dev.get("role", ""),
                        "serial": dev.get("serial", ""),
                        "port": dev.get("port", ""),
                        "backend": dev.get("backend", ""),
                        "is_connected": True,
                        "motor": FakeMotor(),
                    }
                )

        def list_motors(self):
            return {"connected": self.items, "not_connected": []}

    monkeypatch.setattr("qtools.pmeas.motor_manager.MotorManager", FakeManager)

    _print_motor_status(str(cfg_file))
    output = capsys.readouterr().out

    for text in (
        "alice_547_basis_hwp",
        "bob_1550_basis_hwp",
        "alice_547_basis_qwp",
        "R=-45.0000",
        "L=45.0000",
        "current angle: 12.3000°",
    ):
        assert text in output


def test_both_status_entrypoints_use_full_motor_status(monkeypatch, tmp_path):
    from qtools.pmeas import cli

    calls = []
    monkeypatch.setattr(cli, "_print_motor_status", lambda path: calls.append(path))
    cfg_file = tmp_path / "polmeas_config.yaml"

    cli.main(["status", "--config", str(cfg_file)])
    cli.main(["motor", "status", "--config", str(cfg_file)])
    cli.main(["motor", "list", "--config", str(cfg_file)])

    assert calls == [str(cfg_file), str(cfg_file), str(cfg_file)]

def test_pmeas_motor_move_numeric_id_uses_configured_backend(monkeypatch, tmp_path):
    from qtools.pmeas import cli

    cfg_file = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_file)
    cfg._cfg["devices"] = []
    cfg.upsert_device(
        key="COM3", name="bob_hwp", optical_path="bob",
        serial="55119234", port="COM3", backend="k10cr1", waveplate="hwp",
    )
    cfg.upsert_device(
        key="27255044", name="alice_hwp", optical_path="alice",
        serial="27255044", port="27255044", backend="kdc101", waveplate="hwp",
    )
    cfg.upsert_device(
        key="27255094", name="alice_qwp", optical_path="alice",
        serial="27255094", port="27255094", backend="kdc101", waveplate="qwp",
    )
    cfg.get_device("2")["bases"]["H"] = 102.38
    cfg.get_device("3")["bases"]["R"] = 24.21
    cfg.save()
    monkeypatch.setenv("MOTOR_CONFIG", str(cfg_file))

    calls = []
    monkeypatch.setitem(cli._SM_DISPATCH, "move", lambda args: calls.append(args))

    cli._motor_main(["move", "1", "to", "10"])
    cli._motor_main(["move", "2", "to", "30"])
    cli._motor_main(["move", "3", "to", "45"])
    cli._motor_main(["move", "2", "to", "H"])
    cli._motor_main(["move", "3", "to", "R"])

    assert [(args.target, args.backend, args.angle) for args in calls] == [
        ("1", "k10cr1", "10"),
        ("2", "kdc101", "30"),
        ("3", "kdc101", "45"),
        ("2", "kdc101", "102.38"),
        ("3", "kdc101", "24.21"),
    ]

def test_home_all_motors_homes_every_connected_device(monkeypatch, tmp_path, capsys):
    from qtools.pmeas.cli import _home_all_motors

    cfg_file = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_file)
    cfg._cfg["devices"] = []
    for serial, name, backend in (
        ("55119234", "bob_hwp", "k10cr1"),
        ("27255044", "alice_hwp", "kdc101"),
        ("27255094", "alice_qwp", "kdc101"),
    ):
        cfg.upsert_device(
            key=serial, name=name, optical_path=name.split("_")[0],
            serial=serial, port=serial, backend=backend,
        )
    cfg.save()

    homed = []

    class FakeMotor:
        def __init__(self, serial):
            self.serial = serial
            self.is_connected = False

        def connect(self):
            self.is_connected = True
            return True

        def disconnect(self):
            self.is_connected = False

        def home(self):
            homed.append(self.serial)

        def get_position(self):
            return 0.0

    class FakeManager:
        def __init__(self, _cfg):
            self.items = [
                {
                    "id": dev["id"],
                    "name": dev["name"],
                    "motor": FakeMotor(str(dev["serial"])),
                }
                for dev in _cfg.get_all_devices()
            ]

        def list_motors(self):
            return {"connected": self.items, "not_connected": []}

    monkeypatch.setattr("qtools.pmeas.motor_manager.MotorManager", FakeManager)

    _home_all_motors(str(cfg_file))

    assert homed == ["55119234", "27255044", "27255094"]
    output = capsys.readouterr().out
    assert "Home All Motors" in output
    assert output.count(" done (0.0000°)") == 3


def test_motor_home_without_device_dispatches_home_all(monkeypatch, tmp_path):
    from qtools.pmeas import cli

    calls = []
    motor_calls = []
    monkeypatch.setattr(cli, "_home_all_motors", lambda path: calls.append(path))
    monkeypatch.setattr(cli, "_motor_main", lambda argv: motor_calls.append(argv))
    cfg_file = tmp_path / "polmeas_config.yaml"

    cli.main(["motor", "home", "--config", str(cfg_file)])
    cli.main(["motor", "home", "2", "--config", str(cfg_file)])

    assert calls == [str(cfg_file)]
    assert motor_calls == [["home", "2"]]
