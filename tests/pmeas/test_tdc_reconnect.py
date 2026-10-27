"""Regression tests for TDC reconnect when the configured port changes."""

from __future__ import annotations

from types import SimpleNamespace

from qtools.pmeas.config import ConfigManager
from qtools.pmeas.meas_manager import MeasManager


class _FakeTDCBackend:
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True


def _new_manager(cfg: ConfigManager) -> MeasManager:
    manager = MeasManager.__new__(MeasManager)
    manager.cfg = cfg
    manager.detectors = {"tdc": None, "powermeter": None}
    return manager


def test_tdc_retries_configured_port_then_rescans_and_saves(
    tmp_path, monkeypatch
) -> None:
    cfg_file = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_file)
    cfg.set_value("detectors.tdc", {"backend": "exp_s15_tdc1", "port": "COM_OLD"})
    cfg.set_value("detectors.powermeter", {"backend": "", "port": ""})
    cfg.save()

    get_device_calls = []

    def fake_get_device(backend: str, port: str):
        if port == "COM_OLD":
            raise ConnectionError("old TDC port is no longer available")
        get_device_calls.append((backend, port))
        return SimpleNamespace(backend=_FakeTDCBackend())

    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [])
    monkeypatch.setattr("qtools.tdc.get_device", fake_get_device)
    monkeypatch.setattr(
        "qtools.powermeter.cli.auto_detect_connected_device",
        lambda: ("", ""),
    )
    monkeypatch.setattr(
        "qtools.tdc.connection.discover_all",
        lambda method="all", timeout=1.0: [
            SimpleNamespace(
                backend_name="exp_s15_tdc1",
                device_path="COM_NEW",
                serial_number="SN123",
                description="New TDC",
            )
        ],
    )

    manager = _new_manager(cfg)
    manager._init_configed_detectors()

    assert get_device_calls == [("exp_s15_tdc1", "COM_NEW")]
    assert manager.detectors["tdc"] is not None
    assert cfg.get("detectors.tdc") == {
        "backend": "exp_s15_tdc1",
        "port": "COM_NEW",
    }


def test_tdc_uses_configured_port_without_rescan(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_file)
    cfg.set_value("detectors.tdc", {"backend": "exp_s15_tdc1", "port": "COM_OLD"})
    cfg.set_value("detectors.powermeter", {"backend": "", "port": ""})
    cfg.save()

    def unexpected_scan(*args, **kwargs):
        raise AssertionError("scan_detectors should not be called")

    monkeypatch.setattr(cfg, "scan_detectors", unexpected_scan)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [])
    monkeypatch.setattr(
        "qtools.tdc.get_device",
        lambda backend, port: SimpleNamespace(backend=_FakeTDCBackend()),
    )

    manager = _new_manager(cfg)
    manager._init_configed_detectors()

    assert manager.detectors["tdc"] is not None
    assert cfg.get("detectors.tdc")["port"] == "COM_OLD"
