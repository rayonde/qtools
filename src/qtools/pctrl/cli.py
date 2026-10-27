"""
cli.py
------
Command Line Interface (CLI) entry point and parser definitions
for the Polarization Controller package.
"""

from __future__ import annotations

import argparse
import sys

from qtools.pctrl import utils
from qtools.pctrl.loops import run_loops

BANNER = r"""
 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ██████╗  ██████╗████████╗██████╗ ██╗                       ║
 ║   ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██║                       ║
 ║   ██████╔╝██║        ██║   ██████╔╝██║                       ║
 ║   ██╔═══╝ ██║        ██║   ██╔══██╗██║                       ║
 ║   ██║     ╚██████╗   ██║   ██║  ██║███████╗                  ║
 ║   ╚═╝      ╚═════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝                  ║
 ║                                                              ║
 ║   Polarization Controller (PCTRL) Launcher & Engine          ║
 ╚══════════════════════════════════════════════════════════════╝

These are common pctrl commands used in various situations:
"""

# Desired order of subcommands in the `pctrl --help` output.  argparse lists
# subcommands in registration order, so we rebuild the subparsers structures
# after building to present them in this categorized order.
_SUBCOMMAND_ORDER = [
    "list", "status", "init", "loops", "repl",
    "device", "limit", "threshold", "set-id", "set-home",
    "home", "get", "set", "torque",
    "calibrate", "optimize",
]


def _reorder_subparsers(parser: argparse.ArgumentParser,
                        order: list[str]) -> None:
    """Reorder the subcommand display in the argparse help.

    *order* lists subparser names (primary names).  Any subcommand not listed
    keeps its relative position at the end.  Alias names are untouched.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        names = [n for n in order if n in action._name_parser_map]
        names += [n for n in action._name_parser_map if n not in names]
        action._name_parser_map = {n: action._name_parser_map[n] for n in names}
        by_name = {ca.dest: ca for ca in action._choices_actions}
        action._choices_actions = [by_name[n] for n in names if n in by_name]
        action.metavar = "{" + ",".join(names) + "}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pctrl",
        allow_abbrev=False,
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pctrl repl            Force CLI interactive REPL console
  pctrl init            Initialize config file and channel setups (can pair with --full-scan)
  pctrl set qwp_1 45    Set qwp_1 to 45 degrees
  pctrl set -e qwp_1 2048  Set qwp_1 to raw encoder position 2048 (STS: 0-4095, SCS: 0-1023)
  pctrl set -o qwp_1 47  Overshoot two-step: overshoot then approach (backlash compensation)
  pctrl threshold all 2    Set deadband to 2 encoder counts for all servos
  pctrl threshold qwp_1    Read current deadband of qwp_1 (read-only)
        """,
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # loops subcommand
    loops_parser = subparsers.add_parser(
        "loops",
        allow_abbrev=False,
        help="Calculate required fiber loops for QWP and HWP retardations",
    )
    loops_parser.add_argument(
        "--wavelength", "-w",
        type=float,
        required=True,
        help="Wavelength in nm"
    )
    loops_parser.add_argument(
        "--diameter", "-d",
        type=float,
        default=18.0,
        help="Loop/disk diameter in mm (default: 18.0)"
    )
    loops_parser.add_argument(
        "-cladding", "--cladding",
        type=float,
        default=900.0,
        help="Cladding/jacket diameter in um (default: 900)"
    )


    # repl subcommand
    subparsers.add_parser(
        "repl",
        allow_abbrev=False,
        help="Force REPL interactive console",
    )

    # init subcommand
    init_parser = subparsers.add_parser(
        "init",
        allow_abbrev=False,
        help="Initialize setup and configure channels (interactive setup)",
    )
    init_parser.add_argument(
        "--full-scan", "--full",
        dest="full_scan",
        action="store_true",
        help="Perform a full scan of all 253 IDs during initialization",
    )
    init_parser.add_argument(
        "--redo",
        action="store_true",
        help="Force re-initialization even if configuration already exists",
    )

    # status subcommand
    status_parser = subparsers.add_parser(
        "status",
        allow_abbrev=False,
        help="Display communication settings and servo status table",
    )
    status_parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target servo name, ID, or port (e.g. COM3 or /dev/ttyUSB0)",
    )

    # list subcommand
    list_parser = subparsers.add_parser(
        "list",
        allow_abbrev=False,
        help="Scan the configured port and list all discovered online servos",
    )
    list_parser.add_argument(
        "--full-scan", "--full",
        dest="full_scan",
        action="store_true",
        help="Perform a full scan of all 253 IDs",
    )

    # home / reset / zero / middle subcommand — move servos to configured middle positions
    reset_parser = subparsers.add_parser(
        "home",
        aliases=["reset", "zero", "middle"],
        allow_abbrev=False,
        help="Move servos to their configured middle positions",
    )
    reset_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target: servo name, ID, channel key (e.g. alice1550), channel path, or 'all' (default: 'all')",
    )

    # set subcommand
    set_parser = subparsers.add_parser(
        "set",
        allow_abbrev=False,
        help="Set physical or waveplate angle for target (use --encode for raw encoder position)",
    )
    set_parser.add_argument(
        "target",
        help="Servo name, ID, channel key (e.g. alice1550), or channel path (required)",
    )
    set_parser.add_argument(
        "angle",
        nargs="?",
        default=None,
        help="Angle in degrees, or raw encoder position when --encode is used (can be a comma-separated list)",
    )
    set_parser.add_argument(
        "-s", "--speed",
        type=float,
        default=None,
        help="Speed limit in degrees/second for servo movements (default: 10.0 deg/s)",
    )
    set_parser.add_argument(
        "--encode", "-e",
        action="store_true",
        help="Treat angle value as raw encoder position (0-4095 for STS, 0-1023 for SCS)",
    )
    set_parser.add_argument(
        "--overshoot", "-o",
        action="store_true",
        help="Two-step positioning: if |target-current| < 30 counts, overshoot by 150 then approach target (backlash compensation)",
    )

    # get subcommand
    get_parser = subparsers.add_parser(
        "get",
        allow_abbrev=False,
        help="Query physical and waveplate angles",
    )
    get_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target servo name, ID, channel key (e.g. alice1550), channel path, or 'all' (default: 'all')",
    )

    # torque subcommand
    torque_parser = subparsers.add_parser(
        "torque",
        allow_abbrev=False,
        help="Control motor torque locks",
    )
    torque_parser.add_argument(
        "state",
        choices=["on", "off", "enable", "disable", "lock", "release"],
        help="Torque state: 'on' / 'off' / 'lock' / 'release'",
    )
    torque_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target servo name, ID, or 'all' (default: 'all')",
    )

    # set-id subcommand
    set_id_parser = subparsers.add_parser(
        "set-id",
        aliases=["set_id"],
        allow_abbrev=False,
        help="Change a servo's ID on the bus",
    )
    set_id_parser.add_argument(
        "ids",
        type=int,
        nargs="+",
        help="Specify 'new_id' (if single servo connected) or 'old_id new_id'",
    )

    # calibrate subcommand
    cal_parser = subparsers.add_parser(
        "calibrate",
        aliases=["cal"],
        allow_abbrev=False,
        help="Run waveplate calibration sweep",
    )
    cal_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target: servo name, ID, channel key (e.g. alice1550), channel path, or 'all' (default: 'all')",
    )
    cal_parser.add_argument(
        "--plot",
        action="store_true",
        help="Plot and save calibration fit, verification, and Bloch sphere figures",
    )
    cal_parser.add_argument(
        "--basis",
        choices=["h", "v", "d", "a"],
        required=True,
        help="Specify the measurement polarization basis: h, v, d, or a (required)",
    )
    cal_parser.add_argument(
        "--channel",
        type=_parse_channels,
        default=None,
        help="TDC detector channel(s), 1-based, comma-separated (e.g. --channel 2). Default: from config or channel 1.",
    )
    cal_parser.add_argument(
        "--time",
        type=float,
        default=None,
        help="TDC read/integration time in seconds per sweep step (overrides the fast/normal default; e.g. --time 5).",
    )
    cal_parser.add_argument(
        "--fast",
        action="store_true",
        help="Run high-speed calibration (larger step size, lower integration time)",
    )

    # optimize subcommand
    opt_parser = subparsers.add_parser(
        "optimize",
        aliases=["opt"],
        allow_abbrev=False,
        help="Optimize waveplate angles to maximize/minimize TDC singles on a channel",
    )
    opt_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target: channel key (e.g. alice1550), channel path, servo name, ID or 'all' (default: 'all')",
    )
    opt_parser.add_argument(
        "--measure",
        choices=["singles", "pairs"],
        default="singles",
        help="Measurement type to optimize (default: singles)",
    )
    opt_parser.add_argument(
        "--maxiter",
        type=int,
        default=30,
        help="Maximum iterations for the optimizer (default: 30)",
    )
    direction_group = opt_parser.add_mutually_exclusive_group()
    direction_group.add_argument(
        "--minimize",
        action="store_true",
        help="Minimize the metric instead of maximizing it (default: False)",
    )
    direction_group.add_argument(
        "--maximize",
        action="store_true",
        help="Maximize the metric (default behavior)",
    )
    opt_parser.add_argument(
        "--save-config", "--save",
        dest="save_config",
        action="store_true",
        help="Save the optimized physical angles back to the config file (default: False)",
    )
    opt_parser.add_argument(
        "--save-process",
        dest="save_process",
        nargs="?",
        const=True,
        default=None,
        help="Save optimization process history (angles, values) to CSV/JSON/YAML file (default: optimize_process_<YYYYMMDD_HHMMSS>.csv if specified without path)",
    )
    opt_parser.add_argument(
        "--step-size",
        type=float,
        default=15.0,
        help="Initial simplex step size in degrees (default: 15.0)",
    )
    opt_parser.add_argument(
        "--settle-time",
        type=float,
        default=0.1,
        help="Settle time in seconds after servos stop moving (default: 0.1)",
    )
    opt_parser.add_argument(
        "--channel",
        type=_parse_channels,
        default=None,
        help="TDC detector channel(s), 1-based, comma-separated (e.g. --channel 2). Default: from config or channel 1.",
    )
    opt_parser.add_argument(
        "--time",
        "--duration",
        dest="time",
        type=float,
        default=None,
        help="TDC read/integration time in seconds per sample (overrides the default 0.2s; e.g. --time 2 or --duration 2).",
    )
    opt_parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of readings averaged per evaluation (default: 1; increase only if needed)",
    )
    opt_parser.add_argument(
        "--ch_start",
        type=int,
        default=None,
        help="Pairs reference start channel, 1-based (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--ch_stop",
        type=int,
        default=None,
        help="Pairs target stop channel, 1-based (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--delay",
        type=int,
        default=None,
        help="Pairs stop-channel delay in bins (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--ws",
        type=int,
        default=None,
        help="Pairs coincidence window start in bins (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--we",
        type=int,
        default=None,
        help="Pairs coincidence window stop in bins (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--threshvolt",
        type=float,
        default=None,
        help="TDC threshold voltage in volts (required with --measure pairs)",
    )
    opt_parser.add_argument(
        "--tol",
        type=float,
        default=1.0,
        help="Nelder-Mead angle convergence tolerance in degrees (default: 1.0)",
    )
    opt_parser.add_argument(
        "--plot",
        action="store_true",
        help="Plot and save the optimization convergence history (metric value and servo angles vs evaluation)",
    )

    # device subcommand
    device_parser = subparsers.add_parser(
        "device",
        allow_abbrev=False,
        help="Connect or scan auxiliary devices (TDC, Powermeter)",
    )
    device_parser.add_argument(
        "device_type",
        choices=["tdc", "powermeter"],
        help="Device type to search/connect: 'tdc' or 'powermeter'",
    )
    device_parser.add_argument(
        "device_args",
        nargs="*",
        help="Optional connection arguments, e.g. port/address and backend",
    )

    # set-home / set-zero / set-middle subcommand — force current position as middle
    set_zero_parser = subparsers.add_parser(
        "set-home",
        aliases=["set-zero", "set_zero", "set-middle", "set_middle"],
        allow_abbrev=False,
        help="Set current angle to zero/middle (force current position as middle)",
    )
    set_zero_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target: servo name, ID, channel key (e.g. alice1550), channel path, or 'all' (default: 'all')",
    )

    # limit subcommand
    limit_parser = subparsers.add_parser(
        "limit",
        allow_abbrev=False,
        help="Set angle limits (software + EEPROM) for target",
    )
    limit_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target servo name, ID, or 'all' (default: 'all')",
    )
    limit_parser.add_argument(
        "min",
        nargs="?",
        type=float,
        default=-90.0,
        help="Minimum angle in degrees (default: -90.0)",
    )
    limit_parser.add_argument(
        "max",
        nargs="?",
        type=float,
        default=90.0,
        help="Maximum angle in degrees (default: 90.0)",
    )

    # threshold subcommand
    threshold_parser = subparsers.add_parser(
        "threshold",
        allow_abbrev=False,
        help="Set servo deadband (CW_DEAD/CCW_DEAD) threshold and persist to EEPROM",
    )
    threshold_parser.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Target: servo name, ID, channel key (e.g. alice1550), channel path, or 'all' (default: 'all')",
    )
    threshold_parser.add_argument(
        "threshold",
        type=int,
        nargs="?",
        default=None,
        help="Deadband threshold value in encoder counts (e.g. 2, range: 0-255). Lower = higher precision.",
    )

    # Global options
    parser.add_argument(
        "--mock",
        "-m",
        action="store_true",
        help="Run commands in mock/simulation mode without physical hardware connected",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Speed limit in degrees/second for servo movements (default: 10.0 deg/s)"
    )
    parser.add_argument(
        "--step",
        type=float,
        default=5.0,
        help="Step size in degrees for calibration sweep (default: 5.0)"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="pctrl_config.yaml",
        metavar="PATH",
        help="Config file path (default: pctrl_config.yaml)",
    )
    parser.add_argument(
        "--port",
        "-p",
        default=None,
        metavar="PORT",
        help="Specify serial port (e.g. COM3 or /dev/ttyUSB0)",
    )
    parser.add_argument(
        "--baud",
        "-b",
        default=1_000_000,
        type=int,
        metavar="RATE",
        help="Baud rate (default: 1000000)",
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=["scs", "sts"],
        default=None,
        help="Specify servo type: scs or sts (default: read from config or sts)",
    )

    # Present subcommands in the categorized order above.
    _reorder_subparsers(parser, _SUBCOMMAND_ORDER)
    return parser


def _parse_channels(value: str) -> list[int]:
    """Parse a 1-based TDC channel spec like '2' or '1,2' into a list of ints."""
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("channel must be a 1-based channel number")
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid channel spec: {value!r}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

    parser = _build_parser()
    args = parser.parse_args()

    args.config = utils.resolve_config_path(args.config)

    # Dispatch subcommands
    subcmd = getattr(args, "subcommand", None)
    if subcmd == "loops":
        run_loops(args)
        return
    elif subcmd == "repl":
        from qtools.pctrl.repl import run_cli_interactive
        run_cli_interactive(config=args.config, mock=args.mock)
        return
    elif subcmd == "init":
        full_scan = getattr(args, "full_scan", False)
        redo = getattr(args, "redo", False)
        utils.run_init(config=args.config, full_scan=full_scan, redo=redo, mock=args.mock)
        return
    elif subcmd == "status":
        utils.run_status(config=args.config, port=args.port, baud=args.baud, target=args.target, servo_type=args.type, mock=args.mock)
        return
    elif subcmd == "list":
        full_scan = getattr(args, "full_scan", False)
        utils.run_list(config=args.config, port=args.port, baud=args.baud, full_scan=full_scan, servo_type=args.type, mock=args.mock)
        return

    elif subcmd in ("home", "reset", "zero", "middle"):
        utils.run_reset(config=args.config, port=args.port, baud=args.baud, speed_deg_s=args.speed, target=args.target, servo_type=args.type, mock=args.mock)
        return
    elif subcmd == "set":
        if args.angle is not None:
            targets = [t.strip() for t in args.target.split(",") if t.strip()]
            angles = [a.strip() for a in str(args.angle).split(",") if a.strip()]
            if len(targets) > 1:
                if len(angles) == 1:
                    set_parts = [f"{t}:{angles[0]}" for t in targets]
                elif len(angles) == len(targets):
                    set_parts = [f"{t}:{a}" for t, a in zip(targets, angles)]
                else:
                    print("Error: Number of angles must match number of targets or be a single angle.")
                    sys.exit(1)
                set_str = ",".join(set_parts)
            else:
                set_str = f"{args.target}:{args.angle}"
        else:
            set_str = args.target
        utils.run_direct_set(config=args.config, set_str=set_str, speed_deg_s=args.speed, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock, encode=args.encode, accurate=args.overshoot)
        return
    elif subcmd == "get":
        utils.run_direct_get(config=args.config, get_str=args.target, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        return
    elif subcmd == "torque":
        enable_torque = args.state.lower() in ("on", "lock", "enable")
        utils.run_torque_control(config=args.config, enable=enable_torque, port=args.port, baud=args.baud, target=args.target, servo_type=args.type, mock=args.mock)
        return
    elif subcmd in ("set-id", "set_id"):
        utils.run_direct_set_id(config=args.config, ids=args.ids, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        return
    elif subcmd in ("set-home", "set-zero", "set_zero", "set-middle", "set_middle"):
        utils.run_set_middle(config=args.config, target=args.target, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        return
    elif subcmd == "limit":
        utils.run_limit(config=args.config, target=args.target, min_angle=args.min, max_angle=args.max,
                        port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        return
    elif subcmd in ("calibrate", "cal"):
        from qtools.pctrl.calibration import run_calibration
        run_calibration(
            config=args.config,
            target=args.target,
            step_deg=args.step,
            speed_deg_s=args.speed if args.speed is not None else 10.0,
            basis=args.basis,
            fast=args.fast,
            port=args.port,
            mock=args.mock,
            channels=args.channel,
            duration=args.time,
            plot=args.plot,
        )
        return
    elif subcmd in ("optimize", "opt"):
        from qtools.pctrl import PolarizationController

        if args.measure == "pairs":
            missing = [
                name for name in
                ("ch_start", "ch_stop", "delay", "ws", "we", "threshvolt")
                if getattr(args, name) is None
            ]
            if missing:
                parser.error(
                    "--measure pairs requires: "
                    + ", ".join(f"--{name}" for name in missing)
                )

        ctrl = PolarizationController(config_path=args.config, mock=args.mock)

        print(f"Running Nelder-Mead {args.measure} optimization on target: '{args.target}'...")
        optimal_angles = ctrl.optimize(
            target=args.target,
            minimize=args.minimize and not args.maximize,
            method="Nelder-Mead",
            maxiter=args.maxiter,
            tol=args.tol,
            step_size_deg=args.step_size,
            speed_deg_s=args.speed if args.speed is not None else 10.0,
            settle_time=args.settle_time,
            channels=args.channel,
            duration=args.time if args.time is not None else 0.2,
            samples=args.samples,
            measure_type=args.measure,
            ch_start=args.ch_start,
            ch_stop=args.ch_stop,
            delay=args.delay,
            window_start=args.ws,
            window_stop=args.we,
            threshvolt=args.threshvolt,
            save_config=args.save_config,
            save_process=args.save_process,
            plot=args.plot,
        )
        print(f"Optimization successful! Optimal physical angles: {optimal_angles}")
        ctrl.close()
        return
    elif subcmd == "threshold":
        if args.threshold is None:
            utils.run_threshold(config=args.config, threshold=None, target=args.target, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        else:
            utils.run_threshold(config=args.config, threshold=args.threshold, target=args.target, port=args.port, baud=args.baud, servo_type=args.type, mock=args.mock)
        return
    elif subcmd == "device":
        utils.run_device_subcommand(config=args.config, device_type=args.device_type, device_args=args.device_args, mock=args.mock)
        return
    else:
        # Default behavior: print help menu
        parser.print_help()
