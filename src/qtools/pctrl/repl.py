#!/usr/bin/env python3
"""
repl.py — REPL and device management for polarization controller.
"""
from __future__ import annotations

import sys
from qtools.pctrl.utils import (
    run_setup,
    run_direct_set,
    run_direct_get,
    run_reset,
    run_set_middle,
    run_torque_control,
    run_limit,
    run_threshold,
    _print_channel_status,
)
from qtools.pctrl.loops import run_loops
from qtools.pctrl.calibration import run_calibration
from qtools.pctrl.servo_manager import ServoManager
from qtools.pctrl.backends import ServoBackend


def _get_handles(mgr):
    """Return (port_handler, backend) from a connected ServoManager."""
    return mgr.backend.port_handler, mgr.backend


def run_cli_interactive(config: str, mock: bool = False) -> None:
    """Launch the interactive CLI REPL shell."""
    from qtools.pctrl.config import ConfigManager
    from qtools.pctrl.backends import COMM_SUCCESS

    cfg = ConfigManager(config)
    config_exists = cfg.load()
    if not config_exists or len(cfg.channels) == 0:
        print("No channel setup configuration found. Launching setup wizard...")
        run_setup(config_path=config, mock=mock)
        cfg.load()

    print("==================================================")
    print("      Polarization Controller (PCTRL) CLI REPL    ")
    print("==================================================")
    print(f"Config file : {config}")
    print(f"Serial port : {cfg.port or '(Not configured)'} @ {cfg.baudrate} bps")
    print(f"Channels    : {len(cfg.channels)}")
    if mock:
        print("Mode        : Mock / simulation")
    print("Type 'help' for available commands, 'exit' or 'quit' to close.\n")

    mgr = ServoManager(config, mock_mode=mock)

    # Sync auto-discovered port back to our local config reference
    if mgr.cfg.port:
        cfg.port = mgr.cfg.port
        cfg.baudrate = mgr.cfg.baudrate

    # Connect to servo bus (ServoManager already auto-discovered and connected)
    ph = None
    ph_sts = None
    print(f"Connecting to port {cfg.port or 'MOCK_PORT'} ...", end=" ", flush=True)
    try:
        ph, ph_sts = _get_handles(mgr)
        if ph_sts is not None:
            print("OK")
        else:
            print("Failed")
    except Exception as e:
        print(f"Failed ({e})")

    default_speed = 1200
    default_acc = 50

    def execute_status():
        cfg.load()
        print("\nDevice Status:")
        if ph_sts:
            print(f"  Servos:     Connected on port {cfg.port} @ {cfg.baudrate} bps")
        else:
            print("  Servos:     Disconnected")

        # Print Servos Status Table via shared formatter
        _print_channel_status(cfg, servos=cfg.all_servos(), ph_sts=ph_sts)

    execute_status()

    while True:
        try:
            cmd_line = input("pctrl> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            mgr.disconnect()
            break

        if not cmd_line:
            continue

        parts = cmd_line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("exit", "quit"):
            mgr.disconnect()
            break

        try:
            if cmd == "help":
                print("Available commands:")
                print("  status / show / summary  - Show channel configurations, limits, zero points, and online status")
                print("  set <args>               - Move servo (e.g. 'set alice 45', 'set alice:hwp:22.5', 'set alice:plus:10')")
                print("                           - Flags: -e (raw encoder), -o (overshoot two-step for small moves)")
                print("                           - e.g. 'set -e -o qwp_1 2048'")
                print("  get <args>               - Query servo angles (e.g. 'get alice', 'get alice,bob', 'get all')")
                print("  zero / middle / reset   - Move servos to their configured middle positions")
                print("  set_zero / set-middle   - Force current position as middle for target (servo name, ID, or 'all')")
                print("  torque <on|off>          - Enable or disable torque for all servos")
                print("  release / manual         - Disable torque for all servos (free rotation)")
                print("  auto / lock              - Enable torque for all servos (lock position)")
                print("  calibration <target>     - Run calibration sweep for target (servo name, ID, channel key e.g. alice1550, path, or 'all')")
                print("  loops <wl> [dia] [clad]  - Calculate required fiber loops for QWP and HWP")
                print("  scan                     - Scan for online servo IDs on the configured port")
                print("  limit <target> [min max] - Set software angle limits for target")
                print("  threshold <target> [val] - Read/set servo deadband (e.g. 'threshold all 2')")
                print("  set_id <new_id> [old_id] - Change servo ID")
                print("  set_port <port> [baud]   - Update serial port and baudrate, and reconnect")
                print("  init                     - Start the interactive channel setup wizard")
                print("  exit / quit              - Exit the console")

            elif cmd in ("status", "show", "summary"):
                execute_status()

            elif cmd == "scan":
                if not cfg.port and not mock:
                    print("Error: Serial port not configured. Use 'set_port' first.")
                    continue
                scan_port = cfg.port or "MOCK_PORT"
                print(f"Scanning port {scan_port} ...")
                try:
                    backend = ServoBackend(
                        port=scan_port,
                        baudrate=cfg.baudrate,
                        servo_type=cfg.servo_type,
                        mock=mock,
                    )
                    ids = backend.list_servos(stop_on_empty=False)
                    backend.close()
                except Exception as e:
                    print(f"Error scanning port: {e}")
                    ids = []
                print(f"Online servo ID list: {ids}")

            elif cmd == "set_port":
                if not args:
                    print("Usage: set_port <port> [baud]")
                    continue
                port_name = args[0]
                baud_val = cfg.baudrate
                if len(args) > 1:
                    try:
                        baud_val = int(args[1])
                    except ValueError:
                        print("Error: Baud rate must be an integer.")
                        continue

                # Recreate ServoManager with new port
                cfg.port = port_name
                cfg.baudrate = baud_val
                cfg.save()
                mgr = ServoManager(config, port=port_name, mock_mode=mock)

                print(f"Connecting to port {port_name} ...", end=" ", flush=True)
                try:
                    ph, ph_sts = _get_handles(mgr)
                    print("OK")
                except Exception as e:
                    print(f"Failed ({e})")

            elif cmd == "set":
                if not args:
                    print("Usage:")
                    print("  set <servo_name> <angle>")
                    print("  set <servo_name>:<angle>")
                    print("  set <servo_name>:<hwp/qwp>:<angle>")
                    print("  set <servo_1>:<ang1>,<servo_2>:<ang2>")
                    print("  set -e <servo_name> <encoder_pos>    (raw encoder)")
                    print("  set -o <servo_name> <angle>          (overshoot two-step)")
                    print("  set -e -o <servo_name> <encoder_pos> (both)")
                    continue
                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue

                # Check for --encode / -e and --overshoot / -o flags
                encode_mode = False
                accurate_mode = False
                stripped_args = []
                for a in args:
                    if a in ("-e", "--encode"):
                        encode_mode = True
                    elif a in ("-o", "--overshoot"):
                        accurate_mode = True
                    else:
                        stripped_args.append(a)
                if not stripped_args:
                    print("Usage: set [-e] [-a] <servo_name> <value>")
                    continue

                if len(stripped_args) == 2 and ":" not in stripped_args[0] and ":" not in stripped_args[1]:
                    cmd_str = f"{stripped_args[0]}:{stripped_args[1]}"
                else:
                    cmd_str = " ".join(stripped_args)
                run_direct_set(config, cmd_str, ph_sts=ph_sts, encode=encode_mode, accurate=accurate_mode)

            elif cmd == "get":
                if not args:
                    print("Usage:")
                    print("  get <servo_name>")
                    print("  get <name1>,<name2>,...")
                    print("  get all")
                    continue
                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue
                if args[0].lower() == "all":
                    all_names = [s["name"] for s in cfg.all_servos()]
                    get_str = ",".join(all_names)
                else:
                    get_str = ",".join(args)
                run_direct_get(config, get_str, ph_sts=ph_sts)

            elif cmd in ("reset", "zero", "middle"):
                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue
                run_reset(config, ph_sts=ph_sts)

            elif cmd in ("set_zero", "set-zero", "set_middle", "set-middle"):
                if not args:
                    print("Usage: set_zero <servo_name|servo_id|all>")
                    continue
                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue
                run_set_middle(config, args[0], ph_sts=ph_sts)

            elif cmd in ("torque", "release", "manual", "auto", "lock"):
                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue
                enable = True
                if cmd in ("release", "manual"):
                    enable = False
                elif cmd in ("auto", "lock"):
                    enable = True
                else:
                    if not args:
                        print("Usage: torque <on|off|enable|disable>")
                        continue
                    arg_val = args[0].lower()
                    if arg_val in ("on", "enable", "1"):
                        enable = True
                    elif arg_val in ("off", "disable", "0"):
                        enable = False
                    else:
                        print(f"Error: Invalid torque argument '{args[0]}'. Expected 'on' or 'off'.")
                        continue
                run_torque_control(config, enable=enable, ph_sts=ph_sts)

            elif cmd in ("calibration", "cal"):
                if not args:
                    print("Usage: calibration <servo_name|servo_id|channel_path|all> [step_deg] [speed_deg_s]")
                    continue
                target_str = args[0]
                step_val = 5.0
                if len(args) > 1:
                    try:
                        step_val = float(args[1])
                    except ValueError:
                        print("Error: step_deg must be a number.")
                        continue
                speed_val = 10.0
                if len(args) > 2:
                    try:
                        speed_val = float(args[2])
                    except ValueError:
                        print("Error: speed_deg_s must be a number.")
                        continue
                run_calibration(
                    config=config,
                    target=target_str,
                    step_deg=step_val,
                    speed_deg_s=speed_val,
                    port=cfg.port,
                    mock=mock,
                    servo_mgr=mgr,
                )

            elif cmd == "loops":
                if not args:
                    print("Usage: loops <wavelength> [diameter_mm] [cladding_um]")
                    continue
                try:
                    wl = float(args[0])
                except ValueError:
                    print("Error: Wavelength must be a number.")
                    continue
                d_val = 18.0
                if len(args) > 1:
                    try:
                        d_val = float(args[1])
                    except ValueError:
                        print("Error: Diameter must be a number.")
                        continue
                clad_val = 900.0
                if len(args) > 2:
                    try:
                        clad_val = float(args[2])
                    except ValueError:
                        print("Error: Cladding must be a number.")
                        continue
                class LoopsArgs:
                    def __init__(self, wavelength, diameter, cladding):
                        self.wavelength = wavelength
                        self.diameter = diameter
                        self.cladding = cladding
                run_loops(LoopsArgs(wl, d_val, clad_val))

            elif cmd == "limit":
                if not args:
                    print("Usage: limit <target> [min max]")
                    continue
                target = args[0]
                min_angle = -90.0
                max_angle = 90.0
                if len(args) > 2:
                    try:
                        min_angle = float(args[1])
                        max_angle = float(args[2])
                    except ValueError:
                        print("Error: min/max limits must be numbers.")
                        continue
                run_limit(config, target, min_angle, max_angle, ph_sts=ph_sts)

            elif cmd == "threshold":
                if not args:
                    print("Usage: threshold <target> [value]")
                    print("  Sets CW_DEAD/CCW_DEAD deadband to <value> encoder counts (0-255).")
                    print("  If value is omitted, reads current deadband only.")
                    print("  e.g. threshold all 2   — set all servos to deadband 2")
                    print("       threshold qwp_1   — read qwp_1 deadband")
                    continue
                target = args[0]
                if len(args) > 1:
                    try:
                        thresh_val = int(args[1])
                    except ValueError:
                        print("Error: threshold must be an integer (0-255).")
                        continue
                    if thresh_val < 0 or thresh_val > 255:
                        print("Error: threshold must be in range [0, 255].")
                        continue
                else:
                    thresh_val = None
                run_threshold(config, thresh_val, target=target, servo_type=cfg.servo_type, port=cfg.port, baud=cfg.baudrate, mock=mock)

            elif cmd == "set_id":
                if not args:
                    print("Usage: set_id <new_id> [old_id]")
                    continue
                try:
                    new_id = int(args[0])
                except ValueError:
                    print("Error: Target ID must be an integer.")
                    continue
                old_id = None
                if len(args) > 1:
                    try:
                        old_id = int(args[1])
                    except ValueError:
                        print("Error: Old ID must be an integer.")
                        continue

                if ph_sts is None:
                    print("Error: Serial port not connected.")
                    continue

                id_port = cfg.port or "MOCK_PORT"

                if old_id is None:
                    print("Scanning for the single online servo...")
                    try:
                        online_ids = mgr.backend.list_servos(stop_on_empty=False)
                    except Exception as e:
                        print(f"Error scanning port: {e}")
                        online_ids = []
                    if not online_ids:
                        print("Error: No online servos found. Check connection and power.")
                        continue
                    if len(online_ids) > 1:
                        print(f"Error: Multiple online servos found {online_ids}.")
                        print("To prevent conflicts, please connect only ONE servo to the bus when changing IDs.")
                        continue
                    old_id = online_ids[0]

                print(f"Preparing to change servo ID from {old_id} to {new_id} ...")

                success = False
                try:
                    mgr.backend.release(old_id)
                    if mgr.backend.set_id(new_id=new_id, old_id=old_id):
                        success = True
                except Exception as e:
                    print(f"Error changing ID: {e}")

                if success:
                    s = cfg.find_by_id(old_id)
                    if s is not None:
                        cfg.update_servo(s["name"], servo_id=new_id)
                        cfg.save()
                        print(f"Updated config: servo '{s['name']}' servo_id {old_id} -> {new_id}")

                # Reconnect to refresh servo ID list
                print(f"Reconnecting to port {id_port} ...", end=" ", flush=True)
                try:
                    mgr.disconnect()
                    mgr = ServoManager(config, port=cfg.port, mock_mode=mock)
                    ph, ph_sts = _get_handles(mgr)
                    print("OK")
                except Exception:
                    print("Failed")

            elif cmd == "init":
                mgr.disconnect()
                ph = None
                ph_sts = None

                run_setup(config_path=config, mock=mock)
                cfg.load()
                if cfg.port or mock:
                    print(f"Reconnecting to port {cfg.port or 'MOCK_PORT'} ...", end=" ", flush=True)
                    try:
                        mgr = ServoManager(config, port=cfg.port, mock_mode=mock)
                        ph, ph_sts = _get_handles(mgr)
                        print("OK")
                    except Exception:
                        print("Failed")

            else:
                print(f"Unknown command '{cmd}'. Type 'help' for instructions.")

        except SystemExit:
            continue
        except Exception as e:
            print(f"Error executing command: {e}")

    mgr.disconnect()


def run_cli(config: str) -> None:
    """Launch CLI interactive REPL."""
    run_cli_interactive(config)
