from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qtools.motor.backends.motor import MotorDeviceInfo
from qtools.pmeas.config import ConfigManager
from qtools.pmeas.motor_manager import MotorManager


def test_serial_only_kdc101_is_available(monkeypatch, tmp_path: Path) -> None:
    import qtools.pmeas.motor_manager as motor_manager

    monkeypatch.setattr(
        motor_manager,
        "list_motors",
        lambda: [MotorDeviceInfo("27255044", "KDC101 (SN=27255044)", "kdc101", "27255044")],
    )
    monkeypatch.setattr(motor_manager, "_check_availability", lambda _port: False)
    monkeypatch.setattr(
        motor_manager,
        "sm_get_motor",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    cfg = ConfigManager.resolve(tmp_path / "polmeas_config.yaml")
    cfg.upsert_device(
        key="27255044",
        id="alice",
        name="alice1550_basis_hwp",
        optical_path="alice",
        port="",
        serial="27255044",
        backend="kdc101",
    )

    manager = MotorManager(cfg)
    motor = manager.get_motor("alice")

    assert motor.target == "27255044"
    assert motor.backend == "kdc101"

def test_motor_manager_selects_multiple_stages_on_one_side(monkeypatch, tmp_path: Path) -> None:
    import qtools.pmeas.motor_manager as motor_manager

    monkeypatch.setattr(
        motor_manager,
        "list_motors",
        lambda: [
            MotorDeviceInfo("SN-HWP", "KDC101", "kdc101", "SN-HWP"),
            MotorDeviceInfo("SN-QWP", "KDC101", "kdc101", "SN-QWP"),
        ],
    )
    monkeypatch.setattr(motor_manager, "_check_availability", lambda _port: False)
    monkeypatch.setattr(
        motor_manager,
        "sm_get_motor",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    cfg = ConfigManager.resolve(tmp_path / "polmeas_config.yaml")
    cfg.upsert_device(
        key="SN-HWP",
        id="SN-HWP",
        name="alice_547_basis_hwp",
        optical_path="alice",
        serial="SN-HWP",
        role="basis",
        waveplate="hwp",
        backend="kdc101",
    )
    cfg.upsert_device(
        key="SN-QWP",
        id="SN-QWP",
        name="alice_547_basis_qwp",
        optical_path="alice",
        serial="SN-QWP",
        role="basis",
        waveplate="qwp",
        backend="kdc101",
    )

    manager = MotorManager(cfg)
    assert manager.get_motor("alice:hwp").target == "SN-HWP"
    assert manager.get_motor("alice:qwp").target == "SN-QWP"
    with pytest.raises(ValueError, match="ambiguous"):
        manager.get_motor("alice")
