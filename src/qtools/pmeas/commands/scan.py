"""Scan command handler."""

from __future__ import annotations

import argparse
import json
import logging
import numpy as np

from qtools.pmeas.api import MeasController
from qtools.pmeas.commands.utils import _parse_channel, _resolve_motor_pair, _resolve_motor

logger = logging.getLogger(__name__)


def cmd_scan(args: argparse.Namespace) -> None:
    """Dispatch for `scan singles`, `scan pairs`, and `scan chsh`."""
    channel = getattr(args, "channel", None)
    duration = getattr(args, "duration", 1.0) or 1.0
    samples = getattr(args, "samples", None) or getattr(args, "repetitions", None) or 5
    subtract_accidentals = getattr(args, "subtract_accidentals", True)

    with MeasController(config_path=args.config) as ctrl:
        if args.scan_action == "singles":
            sweep_name = getattr(args, "sweep", "bob") or "bob"
            ctrl.scan_singles(
                sweep=sweep_name,
                start_angle=args.start,
                end_angle=args.end,
                step_angle=args.step,
                duration=duration,
                repetitions=samples,
                channel=channel,
                save_raw=True,
                save_plot=getattr(args, "plot", True),
                unit=getattr(args, "unit", None),
            )
            return

        stage_a, stage_b, name_a, name_b = _resolve_motor_pair(args, motor_mgr=ctrl.motor_mgr)
        serial_a = str(getattr(stage_a, "serial", "") or "")
        serial_b = str(getattr(stage_b, "serial", "") or "")

        if serial_a:
            ctrl.cfg.register_device(serial=serial_a, name=name_a, port=getattr(stage_a, 'port', ''), role="hwp", optical_path=name_a)
            ctrl.motor_mgr.register_existing_motor(name_a, stage_a)
        if serial_b:
            ctrl.cfg.register_device(serial=serial_b, name=name_b, port=getattr(stage_b, 'port', ''), role="hwp", optical_path=name_b)
            ctrl.motor_mgr.register_existing_motor(name_b, stage_b)
        ctrl.cfg.save()

        if args.scan_action in ("pairs", "coincidence"):
            export = (
                False
                if getattr(args, "no_export", False)
                else getattr(args, "export", "default") or "default"
            )
            ctrl.scan_coincidence(
                fix=getattr(args, "fix", "alice"),
                sweep=getattr(args, "sweep", "bob"),
                fix_label=getattr(args, "fix_label", None),
                sweep_label=getattr(args, "sweep_label", None),
                fix_angles=getattr(args, "basis", None),
                start_angle=args.start, end_angle=args.end, step_angle=args.step,
                duration=duration, repetitions=samples,
                subtract_accidentals=subtract_accidentals,
                channel=channel,
                export=export,
                save_plot=getattr(args, "plot", True),
                delay=getattr(args, "delay", None),
                window_start=getattr(args, "wstart", None),
                window_stop=getattr(args, "wstop", None),
            )
        elif args.scan_action == "chsh":
            ctrl.scan_bell(
                fix=getattr(args, "fix", "alice"),
                sweep=getattr(args, "sweep", "bob"),
                start_offset=args.start, end_offset=args.end, step_offset=args.step,
                duration=duration, repetitions=samples,
                subtract_accidentals=subtract_accidentals,
                channel=channel,
                save_raw=True,
                save_plot=getattr(args, "plot", True),
                delay=getattr(args, "delay", None),
                window_start=getattr(args, "wstart", None),
                window_stop=getattr(args, "wstop", None),
            )
