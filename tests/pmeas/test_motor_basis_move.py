import argparse

from qtools.pmeas.cli import _resolve_move_basis_args
from qtools.pmeas.config import ConfigManager


def test_move_basis_uses_configured_angle(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager(config_path)
    device = cfg.get_device("1")
    assert device is not None
    device["bases"] = {"H": 1.5, "V": 46.5, "D": 24.0, "A": 69.0}
    cfg.save()
    monkeypatch.setenv("MOTOR_CONFIG", str(config_path))

    args = argparse.Namespace(command="move", move_action="to", target="1", angle="h")

    _resolve_move_basis_args(args)

    assert args.angle == "1.5"
    assert args.target == "1"


def test_move_to_basis_without_target_uses_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOTOR_CONFIG", str(tmp_path / "missing_polmeas_config.yaml"))

    args = argparse.Namespace(command="move", move_action="to", target="d", angle=None)

    _resolve_move_basis_args(args)

    assert args.target is None
    assert args.angle == "22.5"
