from __future__ import annotations

from pathlib import Path

import pytest

from qtools.motor.backends.k10cr1.stage import K10CR1Backend
from qtools.motor.backends.kdc101.stage import KDC101Backend
from qtools.motor.backends.motor import list_motors
from qtools.motor.config import MotorConfigManager


def test_list_motors_scans_all_backends(monkeypatch) -> None:
    monkeypatch.setattr(
        K10CR1Backend,
        "list_devices",
        staticmethod(lambda: [("COM3", "APT USB (SN=55119234A)")]),
    )
    monkeypatch.setattr(
        KDC101Backend,
        "list_devices",
        staticmethod(
            lambda: [
                ("27255044", "KDC101 (SN=27255044)"),
                ("27255094", "KDC101 (SN=27255094)"),
            ]
        ),
    )

    motors = list_motors()

    assert [(motor.backend, motor.serial, motor.target) for motor in motors] == [
        ("k10cr1", "55119234", "COM3"),
        ("kdc101", "27255044", "27255044"),
        ("kdc101", "27255094", "27255094"),
    ]


def test_list_motors_can_be_restricted_to_multiple_backends(monkeypatch) -> None:
    monkeypatch.setattr(
        K10CR1Backend,
        "list_devices",
        staticmethod(lambda: [("COM3", "APT USB (SN=55119234A)")]),
    )
    monkeypatch.setattr(
        KDC101Backend,
        "list_devices",
        staticmethod(lambda: [("27255044", "KDC101 (SN=27255044)")]),
    )

    kdc_only = list_motors("kdc101")
    selected = list_motors(["kdc101", "k10cr1"])

    assert [(motor.backend, motor.target) for motor in kdc_only] == [
        ("kdc101", "27255044")
    ]
    assert [(motor.backend, motor.target) for motor in selected] == [
        ("kdc101", "27255044"),
        ("k10cr1", "COM3"),
    ]


def test_config_wizard_persists_backend_metadata(monkeypatch, tmp_path: Path) -> None:
    answers = iter(["alice", "1550", "basis", "hwp"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    manager = MotorConfigManager(tmp_path / "polmeas_config.yaml")
    manager.load_or_create()

    manager.prompt_device_info(
        "27255044",
        backend="kdc101",
        stage_settings="PRM1-Z8",
        travel_mode=2,
    )

    entry = manager.get_device("27255044")
    assert entry is not None
    assert entry["backend"] == "kdc101"
    assert entry["stage_settings"] == "PRM1-Z8"
    assert entry["travel_mode"] == 2


def test_config_wizard_keeps_multiple_devices_on_one_optical_path(
    monkeypatch, tmp_path: Path
) -> None:
    answers = iter(
        [
            "alice", "547", "basis", "hwp",
            "alice", "547", "basis", "qwp",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    manager = MotorConfigManager(tmp_path / "polmeas_config.yaml")
    manager.load_or_create()

    manager.prompt_device_info("SN-HWP", backend="kdc101")
    manager.prompt_device_info("SN-QWP", backend="kdc101")

    assert len(manager.get_all_devices()) == 2
    assert [dev["id"] for dev in manager.get_all_devices()] == [1, 2]
    with pytest.raises(ValueError, match="matches multiple motors"):
        manager.get_device("alice")
    assert manager.get_device("alice:hwp")["serial"] == "SN-HWP"
    assert manager.get_device("alice:qwp")["serial"] == "SN-QWP"
