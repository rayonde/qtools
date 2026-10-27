"""Calibrate command handlers."""

from __future__ import annotations

import argparse
import logging
import sys

from qtools.pmeas.api import MeasController
from qtools.pmeas.calibration import (
    refit_calibration,
    run_achromatic_calibration,
    save_refit_calibration_config,
)
from qtools.pmeas.config import ConfigManager
from qtools.pmeas.commands.utils import _parse_channel, _resolve_motor

logger = logging.getLogger(__name__)


def _resolve_device_identifier(device: str, args: argparse.Namespace, cfg: ConfigManager | None = None, motor_mgr=None):
    """Resolve a device identifier string to a connected motor.

    *device* can be a port (COM3, /dev/ttyUSB0), id, name, optical_path,
    serial, or 1‑based index.  If *device* matches an optical_path shared
    by multiple devices, the user is prompted to choose.

    Returns ``(stage, device_info)``.
    """
    if cfg is None:
        cfg = ConfigManager.resolve()
    target = str(device).strip()

    # ── Port match: COM3, /dev/ttyUSB0, etc. ──
    if "/" in target or target.upper().startswith("COM"):
        return _resolve_motor(device=None, port=target, motor_mgr=motor_mgr)[0], {}

    # ── Exact match: id, name, serial ──
    info = cfg.get_device(target)
    if info is not None:
        return _resolve_motor(device=None, name=info.get("id") or info.get("name"), motor_mgr=motor_mgr)[0], info

    # ── 1-based numeric index ──
    if target.isdigit():
        return _resolve_motor(device=target, motor_mgr=motor_mgr)[0], {}

    # ── optical_path match ──
    path_matches = cfg.get_devices_by_group(target)
    if len(path_matches) == 1:
        info = path_matches[0]
        return _resolve_motor(device=None, name=info.get("id") or info.get("name"), motor_mgr=motor_mgr)[0], info

    if len(path_matches) > 1:
        print(f"\nMultiple devices share optical_path '{target}'. Choose one:")
        for i, d in enumerate(path_matches, 1):
            print(f"  [{i}] ID: {d.get('id')} ({d.get('name')}, serial={d.get('serial', '?')})")
        while True:
            try:
                choice = input(f"Select (1-{len(path_matches)}): ").strip()
                if choice.isdigit():
                    c = int(choice)
                    if 1 <= c <= len(path_matches):
                        info = path_matches[c - 1]
                        return _resolve_motor(device=None, name=info.get("id") or info.get("name"), motor_mgr=motor_mgr)[0], info
                print(f"Enter 1-{len(path_matches)}.")
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                sys.exit(1)

    # ── USB fallback: auto-detect ──
    return _resolve_motor(motor_mgr=motor_mgr)[0], {}


def _resolve_basis(basis_arg: str | None) -> float:
    """Resolve a measurement analyzer basis to degrees relative to H.

    H is 0 degrees, D is 45 degrees, V is 90 degrees, and A is -45 degrees.
    Numeric input is interpreted as analyzer degrees relative to H.
    Defaults to H (0 degrees).

    Raises ValueError for invalid basis specifications.
    """
    if basis_arg is None:
        return 0.0

    b = basis_arg.strip().upper()
    # Analyzer angles are measured relative to H.
    labels = {"H": 0.0, "D": 45.0, "V": 90.0, "A": -45.0}
    if b in labels:
        return labels[b]
    try:
        return float(b)
    except ValueError:
        raise ValueError(
            f"--basis must be H, V, D, A or an angle in degrees. Got '{basis_arg}'."
        ) from None


def cmd_calibrate(args: argparse.Namespace) -> None:
    cal_mode = args.cal_mode  # required subcommand (hwp/qwp/achromatic)

    refit_path = getattr(args, "refit", None)
    if refit_path:
        if cal_mode == "achromatic":
            logger.error("--refit is supported for hwp/qwp calibration, not achromatic calibration")
            raise SystemExit(1)
        try:
            basis = _resolve_basis(getattr(args, "basis", None))
            export_value = getattr(args, "export", None)
            do_export = not getattr(args, "no_export", False) and export_value is not None
            export_path = export_value or None
            result = refit_calibration(
                refit_path,
                waveplate=cal_mode,
                basis=basis,
                input_pol=(getattr(args, "input", None) or "H").strip().upper(),
                estimated_theta_0=getattr(args, "estimated_theta_0", 0.0),
                background=getattr(args, "background", 20.0),
                wavelength_nm=getattr(args, "wavelength", None),
                unit=getattr(args, "unit", None),
                export=do_export,
                export_path=export_path,
                plot=getattr(args, "plot", True),
                config_label=str(refit_path),
                device_name=getattr(args, "device", None) or "",
            )
            if getattr(args, "save_config", False):
                cfg = ConfigManager.resolve(getattr(args, "config", None))
                device_key = save_refit_calibration_config(
                    result,
                    cfg,
                    waveplate=cal_mode,
                    detector="stored-data",
                )
                print(
                    f"[INFO] Refit calibration saved to {cfg.config_path} "
                    f"for device '{device_key}'"
                )
            logger.info("Calibration refit complete: theta_0 = %.4f°", result["theta_0"])
            return
        except (OSError, ValueError) as exc:
            logger.error("Calibration refit failed: %s", exc)
            raise SystemExit(1) from exc

    channel = getattr(args, "channel", None)
    start_angle = getattr(args, "start", 0.0)
    end_angle = getattr(args, "end", 360.0)
    step_angle = getattr(args, "step", 5.0)

    with MeasController(config_path=args.config) as ctrl:
        detector_type, meas_type = ctrl.get_default_detector(task="calibration")

        # Resolve device from positional arg (or auto-detect)
        stage = None
        target_key = None
        info: dict = {}
        try:
            if args.device:
                stage, info = _resolve_device_identifier(args.device, args, cfg=ctrl.cfg, motor_mgr=ctrl.motor_mgr)
            else:
                stage, info = _resolve_motor(device=None, motor_mgr=ctrl.motor_mgr)[0], {}

            # Resolve wavelength: CLI --wavelength > device config > cal task config > default 1560
            cal_cfg = ctrl.cfg.get("calibration", {}) or {}
            cli_wl = getattr(args, "wavelength", None)
            wavelength_nm = (
                cli_wl
                or info.get("wavelength")
                or cal_cfg.get("wavelength_nm")
                or cal_cfg.get("wavelength")
                or 1560.0
            )

            try:
                basis = _resolve_basis(args.basis)
            except ValueError as exc:
                logger.error("%s", exc)
                sys.exit(1)
            input_pol = (args.input or "H").strip().upper()

            # Register device in config if relevant
            serial = str(getattr(stage, "serial", "") or "")
            target_key = getattr(args, "id", None) or getattr(args, "name", None) or info.get("id") or info.get("name") or "stage"
            if serial and target_key:
                role = info.get("role") if info else ""
                ctrl.cfg.register_device(
                    serial=serial,
                    name=target_key,
                    port=getattr(stage, "port", ""),
                    role=role,
                )
                ctrl.cfg.save()
            ctrl.motor_mgr.register_existing_motor(target_key, stage)

            duration = getattr(args, "duration", 1.0)
            repetitions = getattr(args, "samples", 5)

            # with-block: connects on enter, homes motor, disconnects on exit
            with stage:
                # Home motor before calibration — ensures encoder position is known
                stage.home()
                logger.info("Motor is homed")
                logger.info("Home position at %.2f ° (relative to software zero)", stage.get_position())

                if cal_mode == "achromatic":
                    role = getattr(args, "role", "hwp")
                    # --no-export → skip; default / --export / --export FILE → export
                    if getattr(args, "no_export", False):
                        do_export = False
                        export_path = None
                    else:
                        do_export = True
                        export_val = getattr(args, "export", None)
                        # --export FILE (non-empty string) → custom path; --export "" or default → None
                        export_path = export_val if export_val else None
                    run_achromatic_calibration(
                        controller=ctrl,
                        target=target_key,
                        role=role,
                        channel=_parse_channel(channel),
                        meas_type=meas_type,
                        duration=duration,
                        repetitions=repetitions,
                        start_angle=start_angle,
                        end_angle=end_angle,
                        step_angle=step_angle,
                        detector_type=detector_type,
                        wavelength_nm=cli_wl,  # None unless --wavelength given
                        basis=basis,
                        input_pol=input_pol,
                        estimated_theta_0=getattr(args, "estimated_theta_0", 0.0),
                        background=getattr(args, "background", 20.0),
                        export=do_export,
                        export_path=export_path,
                        plot=getattr(args, "plot", True),
                        unit=getattr(args, "unit", None),
                    )
                else:
                    dev_name = (info.get("name") if info else None) or target_key
                    if dev_name == "stage":
                        # Fallback to config name for this device
                        cfg_dev = ctrl.cfg.get_device(target_key)
                        dev_name = str(cfg_dev.get("name") or cfg_dev.get("id") or "") if cfg_dev else ""
                        if not dev_name or dev_name == "stage":
                            dev_name = ""
                    # --no-export → skip; default / --export / --export FILE → export
                    if getattr(args, "no_export", False):
                        do_export = False
                        export_path = None
                    else:
                        do_export = True
                        export_val = getattr(args, "export", None)
                        # --export FILE (non-empty string) → custom path; --export "" or default → None
                        export_path = export_val if export_val else None
                    res = ctrl.calibrate(
                        waveplate=cal_mode,
                        motor_target=target_key,
                        channel=_parse_channel(channel),
                        meas_type=meas_type,
                        duration=duration,
                        repetitions=repetitions,
                        start_angle=start_angle,
                        end_angle=end_angle,
                        step_angle=step_angle,
                        wavelength_nm=wavelength_nm,
                        detector=detector_type,
                        basis=basis,
                        input_pol=input_pol,
                        estimated_theta_0=getattr(args, "estimated_theta_0", 0.0),
                        background=getattr(args, "background", 20.0),
                        plot=getattr(args, "plot", True),
                        device_name=dev_name,
                        unit=getattr(args, "unit", None),
                        export=do_export,
                        export_path=export_path,
                    )
                    theta_0 = res.get("theta_0")
                    if theta_0 is not None and stage is not None:
                        logger.info("Calibration complete: theta_0 = %.4f° (motor zero_offset NOT modified)", theta_0)
        except KeyboardInterrupt:
            print("\n[INFO] Calibration interrupted by user (Ctrl+C).")
            sys.exit(130)
