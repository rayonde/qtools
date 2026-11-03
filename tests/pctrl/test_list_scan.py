from __future__ import annotations

import pytest

from qtools.pctrl import utils


class _FakeConfig:
    instances = []

    def __init__(self, path):
        self.config_path = path
        self.port = ""
        self.baudrate = 1_000_000
        self.servo_type = "sts"
        self.loaded = False
        self.saved = False
        self.__class__.instances.append(self)

    def load(self):
        self.loaded = True

    def save(self):
        self.saved = True


def test_run_list_reports_port_errors_and_saves_found_port(monkeypatch, capsys):
    _FakeConfig.instances.clear()
    monkeypatch.setattr("qtools.pctrl.config.ConfigManager", _FakeConfig)
    monkeypatch.setattr(
        "qtools.pctrl.servo_manager.find_serial_ports",
        lambda: ["COM4", "COM17", "COM10"],
    )

    attempted = []

    class FakeBackend:
        def __init__(self, *, port, baudrate, servo_type, mock):
            self.port = port
            attempted.append(port)
            if port == "COM4":
                raise PermissionError("port is busy")

        def list_servos(self, stop_on_empty=True):
            return [1, 2, 3]

        def close(self):
            pass

    monkeypatch.setattr(utils, "ServoBackend", FakeBackend)
    monkeypatch.setattr(utils, "_known_non_servo_ports", lambda _cfg: {"COM17"})

    utils.run_list("pctrl_config.yaml", full_scan=True)

    cfg = _FakeConfig.instances[0]
    assert cfg.loaded
    assert cfg.port == "COM10"
    assert cfg.saved
    output = capsys.readouterr().out
    assert "ERROR opening/scanning COM4" in output
    assert "port is busy" in output
    assert "Found online servos: [1, 2, 3]" in output
    assert attempted == ["COM4", "COM10"]
