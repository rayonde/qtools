#!/usr/bin/env python3
"""CLI for Thorlabs K10CR1 stepper and KDC101 DC-servo rotation stages.

Motor-control commands only.  For polarization measurement and waveplate
calibration see the ``qtools.pmeas`` package.

Device targeting
----------------
Every command that operates on a motor accepts an optional positional
*device* argument — an index (1, 2, …), a configured name (``alice``),
a serial port (``COM3``, ``/dev/ttyUSB0``), or a serial-number substring.
When omitted and only one device is connected, it is auto-detected.

Syntax examples
    motor move 1 to 90          move device 1 to 90°
    motor move alice to 45      move device "alice" to 45°
    motor move to 90            auto-detect, move to 90°
    motor status alice          query device "alice"
    motor position 1            query device 1
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

from qtools.motor.connection import get_motor
from qtools.motor.backends.motor import MotorBackend, list_devices
from qtools.motor.config import MotorConfigManager


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers & Device resolution
# ═══════════════════════════════════════════════════════════════════════════

def print_device_list(
    show_header: bool = True,
    connected_ports: set[str] | None = None,
    config_mgr: MotorConfigManager | None = None,
    backend: str = "k10cr1",
) -> list[tuple[str, str]]:
    """Scan USB and print connected devices alongside their configured names."""
    if show_header:
        print("\n" + "=" * 60)
        print("Scanning for connected motor devices...")
        print("=" * 60)

    mgr = config_mgr or MotorConfigManager.resolve()
    devices = list_devices(backend)

    if not devices:
        print("  No motor devices found.")
        print("    - Ensure the device is powered on.")
        print("    - Ensure the USB cable is firmly connected.")
    else:
        for i, (port, label) in enumerate(devices, 1):
            m = re.search(r"SN=([a-zA-Z0-9]+)", label)
            sn = re.sub(r"\D", "", m.group(1)) if m else ""
            entry = mgr.get_device(sn) or {} if sn else {}
            name = entry.get("name") or entry.get("id") or "(unconfigured)"
            connected_mark = " [connected]" if connected_ports and port in connected_ports else ""
            print(
                f"  [{i}] Target: {port}  |  SN: {sn or 'N/A'}  |  "
                f"Name: {name}{connected_mark}"
            )

    if show_header:
        print("=" * 60 + "\n")
    return devices

# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _motor_options(args: argparse.Namespace) -> dict[str, object]:
    """Return backend and backend-specific options from parsed CLI args."""
    options: dict[str, object] = {
        "backend": getattr(args, "backend", "k10cr1"),
    }
    for key in (
        "stage_settings",
        "steps_per_rev",
        "gearbox_ratio",
        "pitch",
        "travel_mode",
        "move_timeout",
    ):
        value = getattr(args, key, None)
        if value is not None:
            options[key] = value
    return options


def _open_motor(
    args: argparse.Namespace,
    target: str | int | None = None,
) -> MotorBackend:
    """Open a motor using the backend selected for this CLI invocation."""
    return get_motor(target=target, **_motor_options(args))


def cmd_config(args: argparse.Namespace) -> None:
    """Configure connected devices by prompting for their names."""
    backend = getattr(args, "backend", "k10cr1")
    devices = list_devices(backend)
    if not devices:
        print("\nNo Motor devices detected. Ensure they are powered on and connected.")
        return

    print(f"\nFound {len(devices)} connected device(s). Starting configuration wizard...")
    mgr = MotorConfigManager.resolve()

    for port, label in devices:
        m = re.search(r"SN=([a-zA-Z0-9]+)", label)
        if not m:
            logger.warning("Could not read serial number from device label on %s.", port)
            continue
        serial_str = re.sub(r"\D", "", m.group(1))
        mgr.prompt_device_info(serial_str)

    mgr.save()
    print("\n" + "=" * 60)
    print(f"Configuration wizard completed successfully. Saved to {mgr.config_path}")
    print("=" * 60 + "\n")


def cmd_list(args: argparse.Namespace) -> None:
    """Scan and list connected devices for the selected backend."""
    backend = getattr(args, "backend", "k10cr1")
    _ = print_device_list(show_header=True, backend=backend)


def cmd_status(args: argparse.Namespace) -> None:
    """Connect and query motor status."""
    try:
        with _open_motor(args, target=args.device) as stage:
            print("  [OK] Connected successfully!")
            print(f"       Device Name:   {stage.name or stage.get_stage_name()}")
            print(f"       Serial Number: {stage.serial}")
            print(f"       Current Angle: {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_identify(args: argparse.Namespace) -> None:
    """Blink the device LED."""
    try:
        with _open_motor(args, target=args.device) as stage:
            if hasattr(stage, "identify"):
                stage.identify()
                print(f"  [OK] Blink command sent to: {stage.name or stage.serial}")
    except Exception as exc:
        logger.error("%s", exc)
        sys.exit(1)


def cmd_move_to(args: argparse.Namespace) -> None:
    """Move the motor to an absolute angle."""
    device: str | None = args.target
    angle_str = args.angle

    # Fallback: if angle is None and target looks numeric, treat target as angle
    if angle_str is None and args.target is not None:
        try:
            float(args.target)
            device = None
            angle_str = args.target
        except ValueError:
            pass  # target is a device name, angle_str stays None

    if angle_str is None:
        logger.error("Must specify target angle (e.g. 'motor move to 90').")
        sys.exit(1)

    try:
        angle_val = float(angle_str)
    except ValueError:
        logger.error("Target angle must be a number. Got '%s'", angle_str)
        sys.exit(1)

    try:
        with _open_motor(args, target=device) as stage:
            if args.speed is not None:
                stage.set_velocity(args.speed)
            print(f"       Current Angle: {stage.get_position():.4f}°")
            print(f"       Velocity:      {stage.get_velocity():.2f}°/s")
            print(f"Moving to absolute {angle_val:.4f}°... ", end="", flush=True)
            stage.move_to(angle_val)
            stage.wait_move()
            print("Done.")
            print(f"       New Angle:     {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_move_by(args: argparse.Namespace) -> None:
    """Rotate the motor by a relative displacement."""
    device: str | None = args.target
    angle_str = args.angle

    # Fallback: if angle is None and target looks numeric, treat target as angle
    if angle_str is None and args.target is not None:
        try:
            float(args.target)
            device = None
            angle_str = args.target
        except ValueError:
            pass  # target is a device name, angle_str stays None

    if angle_str is None:
        logger.error("Must specify rotation angle (e.g. 'motor move by 22.5').")
        sys.exit(1)

    try:
        angle_val = float(angle_str)
    except ValueError:
        logger.error("Rotation angle must be a number. Got '%s'", angle_str)
        sys.exit(1)

    try:
        with _open_motor(args, target=device) as stage:
            if args.speed is not None:
                stage.set_velocity(args.speed)
            print(f"       Current Angle: {stage.get_position():.4f}°")
            print(f"       Velocity:      {stage.get_velocity():.2f}°/s")
            print(f"Rotating by {angle_val:+.4f}°... ", end="", flush=True)
            stage.move_by(angle_val)
            stage.wait_move()
            print("Done.")
            print(f"       New Angle:     {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_move(args: argparse.Namespace) -> None:
    """Dispatch the move subcommand to 'to' or 'by' action."""
    if args.move_action == "to":
        cmd_move_to(args)
    elif args.move_action == "by":
        cmd_move_by(args)


def cmd_position(args: argparse.Namespace) -> None:
    """Query current software and physical angle of the motor."""
    try:
        with _open_motor(args, target=args.device) as stage:
            pos = stage.get_position()
            print(f"       Current Angle:  {pos:.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_set_zero(args: argparse.Namespace) -> None:
    """Set the software zero offset."""
    device: str | None = None
    angle_val: float | None = None

    if args.angle is not None:
        device = args.target
        angle_val = float(args.angle)
    elif args.target is not None:
        try:
            angle_val = float(args.target)
        except ValueError:
            device = args.target

    try:
        with _open_motor(args, target=device) as stage:
            stage.set_zero_offset(angle_val)
            print("  [OK] Zero offset set successfully!")
            print(f"       Current Angle: {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_home(args: argparse.Namespace) -> None:
    """Home the motor stage."""
    try:
        with _open_motor(args, target=args.device) as stage:
            print("Homing motor stage...")
            stage.home()
            stage.wait_move()
            print(f"  [OK] Homed. Current angle: {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_zero(args: argparse.Namespace) -> None:
    """Move the motor to the software zero position (0.0°)."""
    try:
        with _open_motor(args, target=args.device) as stage:
            if args.speed is not None:
                stage.set_velocity(args.speed)
            print(f"       Current Angle: {stage.get_position():.4f}°")
            print(f"       Velocity:      {stage.get_velocity():.2f}°/s")
            print("Moving to software zero position (0.0000°)... ", end="", flush=True)
            stage.move_to(0.0)
            stage.wait_move()
            print("Done.")
            print(f"       New Angle:     {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_repl(_args: argparse.Namespace) -> None:
    """Interactive REPL shell for motor control."""
    import shlex

    print("=" * 50)
    print("   Stepper Motor Controller REPL")
    print("=" * 50)
    print("Type 'help' for commands, 'exit' to quit.\n")

    parser = build_parser()

    while True:
        try:
            line = input("stepper> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not line:
            continue

        if line.lower() in ("exit", "quit"):
            print("Exiting.")
            break

        try:
            cmd_args = parser.parse_args(shlex.split(line))
            dispatch = {
                "list":     cmd_list,
                "status":   cmd_status,
                "identify": cmd_identify,
                "move":     cmd_move,
                "position": cmd_position,
                "set-zero": cmd_set_zero,
                "zero":     cmd_zero,
                "home":     cmd_home,
                "config":   cmd_config,
            }
            if cmd_args.command in dispatch:
                dispatch[cmd_args.command](cmd_args)
        except SystemExit:
            # Catch argparse exit on --help or bad args to keep REPL alive
            pass
        except Exception as exc:
            logger.error("%s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# Argument parser
# ═══════════════════════════════════════════════════════════════════════════

def _add_runtime_options(
    parser: argparse.ArgumentParser,
    *,
    backend_default: str | None = None,
) -> None:
    """Add backend selection and backend-specific options to a parser."""
    backend_kwargs: dict[str, object] = {
        "choices": ("k10cr1", "kdc101"),
        "help": "Motor backend (default: k10cr1)",
    }
    if backend_default is None:
        backend_kwargs["default"] = argparse.SUPPRESS
    else:
        backend_kwargs["default"] = backend_default
    parser.add_argument("--backend", **backend_kwargs)

    default = argparse.SUPPRESS if backend_default is None else None
    parser.add_argument(
        "--stage-settings",
        default=default,
        help="Kinesis stage settings name for KDC101 (e.g. PRM1-Z8)",
    )
    parser.add_argument(
        "--steps-per-rev",
        type=float,
        default=default,
        help="KDC101 motor steps per revolution",
    )
    parser.add_argument(
        "--gearbox-ratio",
        type=float,
        default=default,
        help="KDC101 gearbox ratio",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=default,
        help="KDC101 stage pitch",
    )
    parser.add_argument(
        "--travel-mode",
        default=default,
        help="KDC101 travel mode; only rotational/2 is supported",
    )
    parser.add_argument(
        "--move-timeout",
        type=float,
        default=default,
        help="KDC101 move timeout in seconds",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Thorlabs motor CLI (K10CR1 stepper and KDC101 DC servo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_runtime_options(parser, backend_default="k10cr1")
    sub = parser.add_subparsers(title="commands", dest="command", required=True)

    # ------- list ----------------------------------------------------------
    p = sub.add_parser("list", help="List connected devices")
    _add_runtime_options(p)

    # ------- status --------------------------------------------------------
    p = sub.add_parser("status", help="Connect and query motor status")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index (auto-detect if omitted)")

    # ------- identify ------------------------------------------------------
    p = sub.add_parser("identify", help="Blink the device LED")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- move ----------------------------------------------------------
    move_parser = sub.add_parser("move", help="Move the motor stage")
    _add_runtime_options(move_parser)
    move_parser.add_argument("-s", "--speed", type=float, default=None,
                             help="Rotation velocity in °/s")

    move_sub = move_parser.add_subparsers(dest="move_action", required=True)

    # move to
    to_p = move_sub.add_parser("to", help="Move to an absolute angle")
    _add_runtime_options(to_p)
    to_p.add_argument("target", nargs="?", default=None,
                      help="Device name, port, or index (or angle if device omitted)")
    to_p.add_argument("angle", nargs="?", default=None,
                      help="Target absolute angle (degrees)")
    to_p.add_argument("-s", "--speed", type=float, default=None,
                      help="Rotation velocity in °/s")

    # move by
    by_p = move_sub.add_parser("by", help="Rotate by a relative angle")
    _add_runtime_options(by_p)
    by_p.add_argument("target", nargs="?", default=None,
                      help="Device name, port, or index (or angle if device omitted)")
    by_p.add_argument("angle", nargs="?", default=None,
                      help="Relative rotation angle (degrees)")
    by_p.add_argument("-s", "--speed", type=float, default=None,
                      help="Rotation velocity in °/s")

    # ------- position ------------------------------------------------------
    p = sub.add_parser("position", help="Query current software and physical angle")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- set-zero ------------------------------------------------------
    p = sub.add_parser("set-zero", help="Set software zero offset")
    _add_runtime_options(p)
    p.add_argument("target", nargs="?", default=None,
                   help="Device name, port, or index, or the offset angle if device omitted")
    p.add_argument("angle", type=float, nargs="?", default=None,
                   help="Physical offset angle (degrees)")

    # ------- zero ----------------------------------------------------------
    p = sub.add_parser("zero", help="Move the motor stage to software zero (0.0°)")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")
    p.add_argument("-s", "--speed", type=float, default=None,
                   help="Rotation velocity in °/s")

    # ------- home ----------------------------------------------------------
    p = sub.add_parser("home", help="Home the motor stage")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- repl ----------------------------------------------------------
    p = sub.add_parser("repl", help="Start interactive REPL")
    _add_runtime_options(p)
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- config --------------------------------------------------------
    p = sub.add_parser("config", help="Interactive naming and configuration wizard")
    _add_runtime_options(p)

    return parser


def _normalize_move_argv(argv: list[str]) -> list[str]:
    """Support legacy ``move <target> to/by <angle>`` syntax."""
    normalized = list(argv)
    if not normalized or normalized[0] != "move" or len(normalized) < 3:
        return normalized

    tokens = normalized[1:]
    options_with_values = {
        "-s",
        "--speed",
        "--backend",
        "--stage-settings",
        "--steps-per-rev",
        "--gearbox-ratio",
        "--pitch",
        "--travel-mode",
        "--move-timeout",
    }
    first_positional: int | None = None
    action_position: int | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-") and token != "-":
            index += 2 if token in options_with_values else 1
            continue
        if token in ("to", "by"):
            action_position = index
            break
        if first_positional is None:
            first_positional = index
        index += 1
    if (
        first_positional is None
        or action_position is None
        or action_position == first_positional
        or tokens[first_positional] in ("to", "by")
    ):
        return normalized

    target = tokens[first_positional]
    action = tokens[action_position]
    rest = (
        tokens[:first_positional]
        + tokens[first_positional + 1:action_position]
        + tokens[action_position + 1:]
    )
    return ["move", action, target, *rest]


def parse_cli_args(argv: list[str]) -> argparse.Namespace:
    """Build the motor CLI parser and parse ``argv``."""
    return build_parser().parse_args(_normalize_move_argv(argv))


def main() -> None:
    """CLI entry point."""
    args = parse_cli_args(sys.argv[1:])

    dispatch = {
        "list":     cmd_list,
        "status":   cmd_status,
        "identify": cmd_identify,
        "move":     cmd_move,
        "position": cmd_position,
        "set-zero": cmd_set_zero,
        "zero":     cmd_zero,
        "home":     cmd_home,
        "repl":     cmd_repl,
        "config":   cmd_config,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
