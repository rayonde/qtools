from __future__ import annotations

from pathlib import Path

import pytest

from qtools.motor.connection import _parse_device_info
from qtools.motor.backends.kdc101.stage import KDC101Backend
from qtools.motor.backends.motor import get_backend_class
from qtools.motor.config import MotorConfigManager


class FakeThorlabsKDC101:
    instances: list[FakeThorlabsKDC101] = []

    def __init__(self, serial: str, *, blocking: bool = True, move_timeout: float = 120):
        self.serial = serial
        self.blocking = blocking
        self.move_timeout = move_timeout
        self.connected = False
        self.position = 20.0
        self.velocity = 10.0
        self.identified = False
        self.stopped = False
        self.loaded_settings: str | None = None
        self.motor_params: tuple[float, float, float] | None = None
        self.travel_mode = 2
        self.model = "KDC101"
        self.__class__.instances.append(self)

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    def identity(self) -> tuple[str, str]:
        return self.model, self.serial

    def load_settings(self) -> bool:
        return True

    def load_named_settings(self, settings_name: str) -> bool:
        self.loaded_settings = settings_name
        return True

    def set_motor_params(
        self, steps_per_rev: float, gearbox_ratio: float, pitch: float
    ) -> None:
        self.motor_params = (steps_per_rev, gearbox_ratio, pitch)

    def set_travel_mode(self, mode: int) -> None:
        self.travel_mode = mode

    def get_travel_mode(self) -> int:
        return self.travel_mode

    @property
    def is_rotational(self) -> bool:
        return self.travel_mode == 2

    def request_settings(self) -> None:
        return None

    def get_position(self) -> float:
        return self.position

    def get_velocity(self) -> float:
        return self.velocity

    def set_velocity(self, speed: float) -> None:
        self.velocity = speed

    def move_to(self, position: float) -> None:
        self.position = position

    def move_by(self, displacement: float) -> None:
        self.position += displacement

    def home(self) -> None:
        self.position = 0.0

    def wait_move(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    def identify(self) -> None:
        self.identified = True


@pytest.fixture
def fake_low_level(monkeypatch: pytest.MonkeyPatch):
    import qtools.motor.backends.kdc101.kdc101 as low_level

    FakeThorlabsKDC101.instances.clear()
    monkeypatch.setattr(low_level, "ThorlabsKDC101", FakeThorlabsKDC101)
    return FakeThorlabsKDC101


@pytest.fixture
def config_mgr(tmp_path: Path) -> MotorConfigManager:
    manager = MotorConfigManager(tmp_path / "motor_config.yaml")
    manager.load_or_create()
    return manager


def test_kdc101_backend_is_registered() -> None:
    assert get_backend_class("kdc101") is KDC101Backend


def test_kdc101_backend_uses_shared_motor_api(fake_low_level, config_mgr):
    backend = KDC101Backend(
        port="27000001",
        config_mgr=config_mgr,
        stage_settings="PRM1-Z8",
    )

    assert backend.connect()
    low_level = fake_low_level.instances[-1]
    assert low_level.loaded_settings == "PRM1-Z8"
    assert backend.serial == "27000001"

    backend.zero_offset = 10.0
    backend.move_to(45.0)
    assert low_level.position == 55.0
    assert backend.get_position() == pytest.approx(45.0)

    backend.move_by(-15.0)
    assert backend.get_position() == pytest.approx(30.0)

    backend.set_velocity(2.5)
    assert backend.get_velocity() == pytest.approx(2.5)

    backend.identify()
    assert low_level.identified
    backend.stop()
    assert low_level.stopped
    backend.disconnect()
    assert not backend.is_connected


def test_kdc101_backend_rejects_non_rotational_stage(fake_low_level, config_mgr):
    backend = KDC101Backend(port="27000001", config_mgr=config_mgr)
    original_init = fake_low_level.__init__

    def linear_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.travel_mode = 1

    fake_low_level.__init__ = linear_init
    try:
        assert not backend.connect()
    finally:
        fake_low_level.__init__ = original_init


def test_kdc101_zero_offset_is_persisted(fake_low_level, config_mgr):
    backend = KDC101Backend(
        port="27000001",
        config_mgr=config_mgr,
        stage_settings="PRM1-Z8",
    )
    assert backend.connect()
    backend.set_zero_offset(12.5)

    entry = config_mgr.get_device("27000001")
    assert entry is not None
    assert entry["backend"] == "kdc101"
    assert entry["stage_settings"] == "PRM1-Z8"
    assert entry["zero_offset"] == pytest.approx(12.5)


def test_numeric_kdc101_serial_is_not_treated_as_index(
    monkeypatch: pytest.MonkeyPatch,
    config_mgr: MotorConfigManager,
) -> None:
    devices = [
        ("27000001", "KDC101 (SN=27000001)"),
        ("27000002", "KDC101 (SN=27000002)"),
    ]
    monkeypatch.setattr(
        "qtools.motor.connection.list_devices",
        lambda _backend: devices,
    )

    port, _, serial = _parse_device_info(
        target="27000002",
        backend="kdc101",
        config_mgr=config_mgr,
    )

    assert port == "27000002"
    assert serial == ""


def test_integer_target_selects_kdc101_by_index(
    monkeypatch: pytest.MonkeyPatch,
    config_mgr: MotorConfigManager,
) -> None:
    devices = [
        ("27000001", "KDC101 (SN=27000001)"),
        ("27000002", "KDC101 (SN=27000002)"),
    ]
    monkeypatch.setattr(
        "qtools.motor.connection.list_devices",
        lambda _backend: devices,
    )

    port, _, _ = _parse_device_info(
        target=2,
        backend="kdc101",
        config_mgr=config_mgr,
    )

    assert port == "27000002"
