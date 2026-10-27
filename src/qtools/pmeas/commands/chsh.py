"""CHSH command handler."""

from __future__ import annotations

import argparse
import json

from qtools.pmeas.api import MeasController
from qtools.pmeas.commands.utils import _parse_channel, _resolve_motor_pair


def cmd_chsh(args: argparse.Namespace) -> None:
    """Dispatch for `chsh --optimize`, `chsh --live`, or full characterization."""
    channel = getattr(args, "channel", None)
    duration = getattr(args, "duration", 1.0) or 1.0
    samples = getattr(args, "samples", None) or getattr(args, "repetitions", 5) or 5
    subtract_accidentals = getattr(args, "subtract_accidentals", True)
    save_plot = getattr(args, "plot", True)
    bases = ["H", "V", "D", "A"]
    corr_start = 0.0
    corr_end = 180.0
    corr_step = 5.0
    bell_start = 0.0
    bell_end = 90.0
    bell_step = 3.0
    interval = 60.0
    threshold = 2.5
    filename = "drift_history.npz"
    start_step = 4.0
    tol = 0.1

    with MeasController(config_path=args.config) as ctrl:
        stage_a, stage_b, name_a, name_b = _resolve_motor_pair(args, motor_mgr=ctrl.motor_mgr)
        serial_a = str(getattr(stage_a, "serial", "") or "")
        serial_b = str(getattr(stage_b, "serial", "") or "")
        if serial_a:
            ctrl.cfg.register_device(serial=serial_a, name=name_a, port=stage_a.port, role="hwp", optical_path="alice")
            ctrl.motor_mgr.register_existing_motor("alice", stage_a)
        if serial_b:
            ctrl.cfg.register_device(serial=serial_b, name=name_b, port=stage_b.port, role="hwp", optical_path="bob")
            ctrl.motor_mgr.register_existing_motor("bob", stage_b)
        ctrl.cfg.save()

        if args.optimize:
            s_a = str(getattr(ctrl.motor_mgr.get_motor("alice"), "serial", "") or "")
            s_b = str(getattr(ctrl.motor_mgr.get_motor("bob"), "serial", "") or "")
            ctrl.optimize_basis(
                serial_a=s_a,
                serial_b=s_b,
                duration=duration,
                repetitions=samples,
                channel=channel,
                start_step=start_step,
                tol=tol,
            )
            if args.best:
                print("[INFO] --best: full basis-angle optimization (not yet implemented)")
        elif args.live:
            s_a = str(getattr(ctrl.motor_mgr.get_motor("alice"), "serial", "") or "")
            s_b = str(getattr(ctrl.motor_mgr.get_motor("bob"), "serial", "") or "")
            ctrl.live_correction(
                serial_a=s_a,
                serial_b=s_b,
                interval=interval,
                threshold=threshold,
                duration=duration,
                repetitions=samples,
                channel=channel,
                filename=filename,
            )
        else:
            ctrl.scan_coincidence(
                bases=bases,
                start_angle=corr_start,
                end_angle=corr_end,
                step_angle=corr_step,
                duration=duration,
                repetitions=samples,
                subtract_accidentals=subtract_accidentals,
                channel=channel,
                save_plot=save_plot,
            )
            ctrl.scan_bell(
                start_offset=bell_start,
                end_offset=bell_end,
                step_offset=bell_step,
                duration=duration,
                repetitions=samples,
                subtract_accidentals=subtract_accidentals,
                channel=channel,
                save_plot=save_plot,
            )
