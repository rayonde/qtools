import argparse
from unittest.mock import MagicMock, patch

from qtools.pmeas.cli import _add_common_scan_args
from qtools.pmeas.commands.scan import cmd_scan


def _build_pairs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    _add_common_scan_args(
        parser,
        is_coincidence=True,
        export_default=True,
    )
    return parser


def test_scan_pairs_defaults_are_enabled() -> None:
    args = _build_pairs_parser().parse_args([])

    assert args.export is True
    assert args.plot is True


def test_scan_pairs_can_disable_defaults() -> None:
    args = _build_pairs_parser().parse_args(["--no-export", "--no-plot"])

    assert args.no_export is True
    assert args.plot is False


def test_scan_pairs_export_accepts_custom_path() -> None:
    args = _build_pairs_parser().parse_args(["--export", "custom_scan.csv"])

    assert args.export == "custom_scan.csv"


def test_cmd_scan_pairs_forwards_default_export_and_plot() -> None:
    stage_a = MagicMock()
    stage_a.serial = "A"
    stage_a.port = ""
    stage_b = MagicMock()
    stage_b.serial = "B"
    stage_b.port = ""

    ctrl = MagicMock()
    ctrl.motor_mgr = MagicMock()
    ctrl.cfg = MagicMock()
    context_manager = MagicMock()
    context_manager.__enter__.return_value = ctrl
    context_manager.__exit__.return_value = False

    args = argparse.Namespace(
        config=None,
        scan_action="pairs",
        channel=None,
        duration=None,
        samples=None,
        subtract_accidentals=True,
        step=None,
        start=None,
        end=None,
        fix="alice",
        sweep="bob",
        fix_label=None,
        sweep_label=None,
        basis=None,
        no_export=False,
        export=True,
        plot=True,
        unit=None,
    )

    with patch("qtools.pmeas.commands.scan.MeasController", return_value=context_manager):
        with patch(
            "qtools.pmeas.commands.scan._resolve_motor_pair",
            return_value=(stage_a, stage_b, "alice", "bob"),
        ):
            cmd_scan(args)

    _, kwargs = ctrl.scan_coincidence.call_args
    assert kwargs["export"] is True
    assert kwargs["save_plot"] is True


def test_cmd_scan_pairs_no_export_disables_export() -> None:
    stage_a = MagicMock()
    stage_a.serial = "A"
    stage_a.port = ""
    stage_b = MagicMock()
    stage_b.serial = "B"
    stage_b.port = ""

    ctrl = MagicMock()
    ctrl.motor_mgr = MagicMock()
    ctrl.cfg = MagicMock()
    context_manager = MagicMock()
    context_manager.__enter__.return_value = ctrl
    context_manager.__exit__.return_value = False

    args = argparse.Namespace(
        config=None,
        scan_action="pairs",
        channel=None,
        duration=None,
        samples=None,
        subtract_accidentals=True,
        step=5.0,
        start=0.0,
        end=180.0,
        fix="alice",
        sweep="bob",
        fix_label=None,
        sweep_label=None,
        basis=None,
        no_export=True,
        export=True,
        plot=True,
        unit=None,
    )

    with patch("qtools.pmeas.commands.scan.MeasController", return_value=context_manager):
        with patch(
            "qtools.pmeas.commands.scan._resolve_motor_pair",
            return_value=(stage_a, stage_b, "alice", "bob"),
        ):
            cmd_scan(args)

    _, kwargs = ctrl.scan_coincidence.call_args
    assert kwargs["export"] is False
