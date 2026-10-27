"""Main Command Line Interface (CLI) dispatcher for qtools.pmeas."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

from qtools.motor.cli import parse_cli_args as _sm_parse_args

# CMD_DISPATCH maps qtools.motor CLI command strings → handler functions
# (qtools.motor.cli has cmd_* functions but no "main" entrypoint)
from qtools.motor.cli import (
    cmd_config as _sm_config,
    cmd_list   as _sm_list,
    cmd_status as _sm_status,
    cmd_identify as _sm_identify,
    cmd_move_to  as _sm_move_to,
    cmd_move_by  as _sm_move_by,
    cmd_move     as _sm_move,
    cmd_position as _sm_position,
    cmd_set_zero as _sm_set_zero,
    cmd_home     as _sm_home,
    cmd_zero     as _sm_zero,
    cmd_repl     as _sm_repl,
)
_SM_DISPATCH = {
    "config":   _sm_config,
    "list":     _sm_list,
    "status":   _sm_status,
    "identify": _sm_identify,
    "move_to":  _sm_move_to,
    "move_by":  _sm_move_by,
    "move":     _sm_move,
    "position": _sm_position,
    "set_zero": _sm_set_zero,
    "home":     _sm_home,
    "zero":     _sm_zero,
    "repl":     _sm_repl,
}


_BASIS_LABELS = {"H", "V", "D", "A"}


def _is_basis_label(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().upper() in _BASIS_LABELS


def _resolve_move_basis_angle(target: str | None, angle: str) -> str:
    """Resolve a basis label to the configured motor angle for ``target``."""
    from qtools.pmeas.config import ConfigManager
    from qtools.pmeas.entanglement import _get_basis_angle

    try:
        cfg = ConfigManager.resolve(os.environ.get("MOTOR_CONFIG"))
        return str(_get_basis_angle(cfg, target, angle))
    except Exception:
        return angle


def _resolve_move_basis_args(args: argparse.Namespace) -> None:
    """Translate H/V/D/A move angles before delegating to qtools.motor."""
    if getattr(args, "command", None) != "move":
        return

    target = getattr(args, "target", None)
    angle = getattr(args, "angle", None)
    if angle is None and _is_basis_label(target):
        angle = target
        target = None

    if _is_basis_label(angle):
        args.angle = _resolve_move_basis_angle(target, angle)
        args.target = target


def _motor_main(argv: list[str]) -> None:
    """Delegate to qtools.motor CLI using its build_parser / cmd_* functions."""
    args = _sm_parse_args(argv)
    _resolve_move_basis_args(args)
    handler = _SM_DISPATCH.get(args.command)
    if handler is None:
        raise SystemExit(f"unknown qtools.motor command: {args.command}")
    handler(args)

from qtools.pmeas.commands.calibrate import cmd_calibrate
from qtools.pmeas.commands.chsh import cmd_chsh
from qtools.pmeas.commands.config import cmd_config
from qtools.pmeas.commands.scan import cmd_scan
from qtools.pmeas.commands.utils import _add_device_pair_args, _parse_channel


BANNER = r"""
 ╔═════════════════════════════════════════════════════════════════╗
 ║                                                                 ║
 ║  ██████╗  ██████╗ ██╗     ███╗   ███╗███████╗ █████╗ ███████╗   ║
 ║  ██╔══██╗██╔═══██╗██║     ████╗ ████║██╔════╝██╔══██╗██╔════╝   ║
 ║  ██████╔╝██║   ██║██║     ██╔████╔██║█████╗  ███████║███████╗   ║
 ║  ██╔═══╝ ██║   ██║██║     ██║╚██╔╝██║██╔══╝  ██╔══██║╚════██║   ║
 ║  ██║     ╚██████╔╝███████╗██║ ╚═╝ ██║███████╗██║  ██║███████║   ║
 ║  ╚═╝      ╚═════╝ ╚══════╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝   ║
 ║                                                                 ║
 ║   Polarization Measurement (PMEAS) Launcher & Engine          ║
 ╚═════════════════════════════════════════════════════════════════╝

"""


def _add_scan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start", type=float, default=0.0, help="Start angle (default: 0°)")
    p.add_argument("--end", type=float, default=360.0, help="End angle (default: 360°)")
    p.add_argument("--step", type=float, default=5.0, help="Step angle (default: 5°)")
    p.add_argument("--duration", type=float, default=1.0, help="Integration time per point (s)")
    p.add_argument("--samples", type=int, default=5, help="Number of repetitions per angle (default: 5)")



def _add_common_scan_args(
    p: argparse.ArgumentParser,
    is_coincidence: bool = True,
    export_default: bool | str | None = None,
) -> None:
    _add_scan_args(p)
    _add_device_pair_args(p, suppress=True)
    p.add_argument("--fix", default="alice", help="Device to fix (default: alice)")
    p.add_argument("--sweep", default="bob", help="Device to sweep (default: bob)")
    p.add_argument("--fix-label", default=None, help="Display label for fixed device")
    p.add_argument("--sweep-label", default=None, help="Display label for swept device")
    p.add_argument("--channel", type=_parse_channel, default=None, help="Detector channel(s), e.g. 1 or 1,2")
    if is_coincidence:
        p.add_argument("--subtract-accidentals", action="store_true", default=True, help="Subtract accidentals [default]")
        p.add_argument("--no-subtract-accidentals", action="store_false", dest="subtract_accidentals", help="Do not subtract accidentals")
        p.add_argument("--delay", type=int, default=None, help="Coincidence stop-channel delay in bins (default: config 'delay_bin'; 2 ns/bin for S15)")
        p.add_argument("--wstart", type=int, default=None, help="Coincidence window start in bins (use with --wstop)")
        p.add_argument("--wstop", type=int, default=None, help="Coincidence window stop in bins (use with --wstart)")
    p.add_argument("--raw", action="store_true", help="Save raw TDC timestamps (future feature)")
    p.add_argument("--no-export", action="store_true", help="Skip CSV export")
    p.add_argument("-e", "--export", nargs="?", const="", default=export_default, metavar="FILE",
                   help="Export measurement data to CSV (optional FILE for custom path)" + (" [default]" if export_default else ""))
    p.add_argument("--plot", action="store_true", default=True, help="Save plots [default]")
    p.add_argument("--no-plot", action="store_false", dest="plot", help="Skip saving plots")
    p.add_argument("--unit", default=None, choices=["W", "mW", "uW", "nW", "pW"],
                   help="Lock power unit for all scan points (default: auto-select from first measurement)")


def _add_chsh_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--duration", type=float, default=1.0, help="Integration time per point (s)")
    p.add_argument("--samples", type=int, default=5, help="Number of repetitions per measurement (default: 5)")
    _add_device_pair_args(p, suppress=True)
    p.add_argument("--channel", type=_parse_channel, default=None, help="Detector channel(s), e.g. 1,2")
    p.add_argument("--subtract-accidentals", action="store_true", default=True, help="Subtract accidentals [default]")
    p.add_argument("--no-subtract-accidentals", action="store_false", dest="subtract_accidentals", help="Do not subtract accidentals")
    p.add_argument("--plot", action="store_true", default=True, help="Save plots [default]")


def _add_calibrate_args(p: argparse.ArgumentParser, include_device: bool = True) -> None:
    if include_device:
        p.add_argument("device", nargs="?", default=None,
                       help="Device identifier: id, name, optical_path, port")
    p.add_argument("--basis", "-b", default=None,
                   help="Measurement analyzer basis: H, V, D, A or angle in degrees (default: H)")
    p.add_argument("--input", "-i", default="H",
                   help="Input light state: H, V, D, A (default: H)")
    _add_scan_args(p)
    p.add_argument("--wavelength", "-w", type=float, default=None,
                   help="Operating wavelength in nm (default: from device config, or calibration config, or 1560)")
    p.add_argument("--channel", type=_parse_channel, default=None, help="Detector channel")
    p.add_argument("--plot", action="store_true", default=True, help="Save calibration plot [default]")
    p.add_argument("--raw", action="store_true", help="Save raw timestamp data")
    p.add_argument("--refit", metavar="FILE", default=None,
                   help="Re-fit an existing calibration CSV without scanning")
    p.add_argument("--estimated_theta_0", "--estimated-theta-0", dest="estimated_theta_0", type=float, default=0.0,
                   help="Initial theta_0 estimate used by the fit (degrees)")
    p.add_argument("--background", type=float, default=20.0,
                   help="Fixed background subtracted before fitting (data units)")
    p.add_argument("--no-export", action="store_true", help="Skip CSV export")
    p.add_argument("-e", "--export", nargs="?", const="", default=None, metavar="FILE",
                   help="Export calibration data to CSV (optional FILE for custom path)")
    p.add_argument("--save-config", "--save_config", dest="save_config", action="store_true",
                   help="Write refit calibration result into the selected config")
    p.add_argument("--unit", default=None, choices=["W", "mW", "uW", "nW", "pW"],
                   help="Lock power unit for all scan points (default: auto-select from first measurement)")


def main(argv: list[str] | None = None) -> None:
    # Ensure UTF-8 output on Windows (GBK terminals can't render box-drawing chars)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

    raw_argv = list(argv if argv is not None else sys.argv[1:])

    # Set MOTOR_CONFIG so qtools.motor operates on polmeas_config.yaml
    config_path = "polmeas_config.yaml"
    for flag in ("--config", "-c"):
        if flag in raw_argv:
            idx = raw_argv.index(flag)
            if idx + 1 < len(raw_argv) and not raw_argv[idx + 1].startswith("-"):
                config_path = raw_argv[idx + 1]
                break
    os.environ.setdefault("MOTOR_CONFIG", config_path)


    # ── Delegate 'motor', 'list', 'status' directly to qtools.motor CLI ──
    if raw_argv and raw_argv[0] == "motor":
        try:
            _motor_main(raw_argv[1:])
        except KeyboardInterrupt:
            logger.info("Operation interrupted by user (Ctrl+C). Cleaning up...")
            sys.exit(130)
        return

    if raw_argv and raw_argv[0] == "list":
        try:
            from qtools.pmeas.config import ConfigManager
            from qtools.pmeas.motor_manager import MotorManager

            cfg = ConfigManager.resolve(config_path)
            mm = MotorManager(cfg)
            dev_dict = mm.list_devices()

            print("\n" + "=" * 60)
            print("Scanning for connected motor devices...")
            print("=" * 60)

            connected = dev_dict["connected"]
            print("\n [Connected Devices]")
            if not connected:
                print("  No connected motor devices found.")
            else:
                for item in connected:
                    port = item["port"] or "N/A"
                    sn = item["serial"] or "N/A"
                    name = item["name"] or "(unconfigured)"
                    path = item["optical_path"] or "N/A"
                    dev_id = item["id"]
                    print(f"  [{dev_id}] Port:  {port}  |  SN: {sn}  |  Name: {name}  |  Optical Path: {path}")

            not_connected = dev_dict["not_connected"]
            print("\n [Not Connected Devices]")
            if not not_connected:
                print("  No unconnected motor devices found.")
            else:
                for item in not_connected:
                    port = item["port"] or "N/A"
                    sn = item["serial"] or "N/A"
                    name = item["name"] or "(unconfigured)"
                    path = item["optical_path"] or "N/A"
                    dev_id = item["id"]
                    print(f"  [{dev_id}] Port:  {port}  |  SN: {sn}  |  Name: {name}  |  Optical Path: {path}")

            print("=" * 60 + "\n")
            return
        except KeyboardInterrupt:
            logger.info("Operation interrupted by user (Ctrl+C). Cleaning up...")
            sys.exit(130)

    if raw_argv and raw_argv[0] == "status":
        try:
            _motor_main(raw_argv)
        except KeyboardInterrupt:
            logger.info("Operation interrupted by user (Ctrl+C). Cleaning up...")
            sys.exit(130)
        return

    # ── Shared base parser for common options (-c / --config) ──
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument(
        "-c", "--config",
        default=None,
        metavar="CONFIG",
        help="Load a specific config file (default: polmeas_config.yaml)",
    )

    parser = argparse.ArgumentParser(
        prog="pmeas",
        usage="pmeas [-h] {config,motor,list,status,calibrate,scan,chsh} ...",
        description=BANNER,
        parents=[base_parser],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=False)

    # ── config ──
    p = sub.add_parser(
        "config",
        parents=[base_parser],
        help="Manage configuration, registered devices, and calibrations",
        description="Manage configuration, registered devices, and calibrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "sub",
        nargs="?",
        default=None,
        choices=["show", "latest", "init", "archive"],
        help="Action: init (wizard), show (view config), latest (view calibration), archive (backup)",
    )
    p.add_argument(
        "-d", "--date",
        nargs="?",
        const="today",
        default=None,
        help="Load/create dated config file 'polmeas_config_YYYYMMDD.yaml'",
    )

    # ── calibrate ──
    cal_parser = sub.add_parser("calibrate", parents=[base_parser], help="Calibrate a waveplate (hwp / qwp / achromatic)")
    cal_sub = cal_parser.add_subparsers(dest="cal_mode", required=True, help="Calibration type")

    p_hwp = cal_sub.add_parser("hwp", parents=[base_parser], help="Half-wave plate calibration")
    _add_calibrate_args(p_hwp)

    p_qwp = cal_sub.add_parser("qwp", parents=[base_parser], help="Quarter-wave plate calibration")
    _add_calibrate_args(p_qwp)

    p_ach = cal_sub.add_parser("achromatic", parents=[base_parser], help="Multi-wavelength achromatic calibration")
    _add_calibrate_args(p_ach)
    p_ach.add_argument("--role", choices=["hwp", "qwp"], default="hwp",
                       help="Achromatic waveplate type (default: hwp)")

    # ── scan ──
    scan_parser = sub.add_parser("scan", parents=[base_parser], help="Scan measurements (singles / pairs / chsh)")
    scan_sub = scan_parser.add_subparsers(dest="scan_action", required=False)

    ps = scan_sub.add_parser("singles", parents=[base_parser], help="Single detector / power sweep scan")
    _add_common_scan_args(ps, is_coincidence=False)

    pc = scan_sub.add_parser("pairs", parents=[base_parser], help="Coincidence correlation scan: fix one arm, sweep the other")
    pc.add_argument("--basis", default=None, help="Target basis label(s) or numeric angle to fix the --fix device at (e.g. H, V, D, A, or 22.5) [default: all bases (H,V,D,A)]")
    _add_common_scan_args(pc, is_coincidence=True, export_default=True)

    pch = scan_sub.add_parser("chsh", parents=[base_parser], help="CHSH Bell S(beta) scan")
    _add_common_scan_args(pch, is_coincidence=True)

    # Help-only entry: actual 'pmeas motor' execution is delegated to
    # qtools.motor before argparse parsing in main().
    sub.add_parser("motor", help="Control stepper motors (delegated to qtools.motor)")

    # ── chsh ──
    p = sub.add_parser("chsh", parents=[base_parser], help="CHSH Bell inequality: characterize, optimize, monitor")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--optimize", action="store_true", help="Maximise CHSH S")
    mode.add_argument("--live", action="store_true", help="Monitor |S| and re-optimise")
    p.add_argument("--best", action="store_true", help="Adjust all basis angles")
    _add_chsh_args(p)

    args = parser.parse_args(raw_argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "scan" and getattr(args, "scan_action", None) is None and not getattr(args, "config", None):
        scan_parser.print_help()
        sys.exit(0)

    dispatch = {
        "calibrate": cmd_calibrate,
        "scan": cmd_scan,
        "chsh": cmd_chsh,
        "config": cmd_config,
    }

    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        print("\n[INFO] Operation interrupted by user (Ctrl+C). Cleaning up...")
        sys.exit(130)


if __name__ == "__main__":
    main()
