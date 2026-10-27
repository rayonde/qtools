#!/usr/bin/env python3
"""CLI for Thorlabs K10CR1 stepper motor rotation stages.

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
) -> list[tuple[str, str]]:
    """Scan USB and print connected devices alongside their configured names."""
    if show_header:
        print("\n" + "=" * 60)
        print("Scanning for connected motor devices...")
        print("=" * 60)

    mgr = config_mgr or MotorConfigManager.resolve()
    devices = list_devices()

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
            print(f"  [{i}] Port:  {port}  |  SN: {sn or 'N/A'}  |  Name: {name}{connected_mark}")

    if show_header:
        print("=" * 60 + "\n")
    return devices

# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def cmd_config(_args: argparse.Namespace) -> None:
    """Configure connected K10CR1 devices by prompting for their names."""
    devices = list_devices()
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


def cmd_list(_args: argparse.Namespace) -> None:
    """Scan and list connected Thorlabs K10CR1 devices."""
    _ = print_device_list(show_header=True)


def cmd_status(args: argparse.Namespace) -> None:
    """Connect and query motor status."""
    try:
        with get_motor(target=args.device) as stage:
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
        with get_motor(target=args.device) as stage:
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
        with get_motor(target=device) as stage:
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
        with get_motor(target=device) as stage:
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
        with get_motor(target=args.device) as stage:
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
        with get_motor(target=device) as stage:
            stage.set_zero_offset(angle_val)
            print("  [OK] Zero offset set successfully!")
            print(f"       Current Angle: {stage.get_position():.4f}°")
    except Exception as exc:
        logger.error(" %s", exc)
        sys.exit(1)


def cmd_home(args: argparse.Namespace) -> None:
    """Home the motor stage."""
    try:
        with get_motor(target=args.device) as stage:
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
        with get_motor(target=args.device) as stage:
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

def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Thorlabs K10CR1 Stepper Motor CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(title="commands", dest="command", required=True)

    # ------- list ----------------------------------------------------------
    sub.add_parser("list", help="List connected K10CR1 devices")

    # ------- status --------------------------------------------------------
    p = sub.add_parser("status", help="Connect and query motor status")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index (auto-detect if omitted)")

    # ------- identify ------------------------------------------------------
    p = sub.add_parser("identify", help="Blink the device LED")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- move ----------------------------------------------------------
    move_parser = sub.add_parser("move", help="Move the motor stage")
    move_parser.add_argument("-s", "--speed", type=float, default=None,
                             help="Rotation velocity in °/s")

    move_sub = move_parser.add_subparsers(dest="move_action", required=True)

    # move to
    to_p = move_sub.add_parser("to", help="Move to an absolute angle")
    to_p.add_argument("target", nargs="?", default=None,
                      help="Device name, port, or index (or angle if device omitted)")
    to_p.add_argument("angle", nargs="?", default=None,
                      help="Target absolute angle (degrees)")
    to_p.add_argument("-s", "--speed", type=float, default=None,
                      help="Rotation velocity in °/s")

    # move by
    by_p = move_sub.add_parser("by", help="Rotate by a relative angle")
    by_p.add_argument("target", nargs="?", default=None,
                      help="Device name, port, or index (or angle if device omitted)")
    by_p.add_argument("angle", nargs="?", default=None,
                      help="Relative rotation angle (degrees)")
    by_p.add_argument("-s", "--speed", type=float, default=None,
                      help="Rotation velocity in °/s")

    # ------- position ------------------------------------------------------
    p = sub.add_parser("position", help="Query current software and physical angle")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- set-zero ------------------------------------------------------
    p = sub.add_parser("set-zero", help="Set software zero offset")
    p.add_argument("target", nargs="?", default=None,
                   help="Device name, port, or index, or the offset angle if device omitted")
    p.add_argument("angle", type=float, nargs="?", default=None,
                   help="Physical offset angle (degrees)")

    # ------- zero ----------------------------------------------------------
    p = sub.add_parser("zero", help="Move the motor stage to software zero (0.0°)")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")
    p.add_argument("-s", "--speed", type=float, default=None,
                   help="Rotation velocity in °/s")

    # ------- home ----------------------------------------------------------
    p = sub.add_parser("home", help="Home the motor stage")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- repl ----------------------------------------------------------
    p = sub.add_parser("repl", help="Start interactive REPL")
    p.add_argument("device", nargs="?", default=None,
                   help="Device name, port, or index")

    # ------- config --------------------------------------------------------
    sub.add_parser("config", help="Interactive naming and configuration wizard")

    return parser


def _normalize_move_argv(argv: list[str]) -> list[str]:
    """Support legacy ``move <target> to/by <angle>`` syntax."""
    normalized = list(argv)
    if not normalized or normalized[0] != "move" or len(normalized) < 3:
        return normalized

    tokens = normalized[1:]
    first_positional = next(
        (i for i, token in enumerate(tokens) if not token.startswith("-") or token == "-"),
        None,
    )
    action_position = next(
        (i for i, token in enumerate(tokens) if token in ("to", "by")),
        None,
    )
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
