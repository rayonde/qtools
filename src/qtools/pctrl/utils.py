#!/usr/bin/env python3
"""
functions.py
------------
CLI-facing command implementations for the Polarization Controller package.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from qtools.pctrl.backends import ServoBackend, COMM_SUCCESS
from qtools.pctrl.servo_manager import (
    ServoManager, servo_encoder_for_angle, write_eeprom_limits,
)
from qtools.pctrl.config import resolve_target, channel_key_string


# ════════════════════════════════════════════════════════════

def _setup_ask(prompt: str, default: str = "") -> str:
    """Read user input with support for default values."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer if answer else default


def _setup_ask_int(prompt: str, default: int, min_val: int = 0, max_val: int = 10000000) -> int:
    while True:
        raw = _setup_ask(prompt, str(default))
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  ⚠️  Please enter an integer between {min_val} and {max_val}.")
        except ValueError:
            print("  ⚠️  Please enter a valid integer.")


def _setup_ask_choice(prompt: str, choices: list[str]) -> str:
    """Prompt user to choose from a list of options (case-insensitive)."""
    choices_upper = [c.upper() for c in choices]
    while True:
        answer = _setup_ask(prompt).upper()
        if answer in choices_upper:
            return answer
        print(f"  ⚠️  Please choose one of the following: {choices}")


def _setup_banner(text: str) -> None:
    print()
    print("─" * 55)
    print(f"  {text}")
    print("─" * 55)


def run_setup(config_path: str = "pctrl_config.yaml", full_scan: bool = False, mock: bool = False) -> None:
    from qtools.pctrl.config import ConfigManager, FlowList
    from qtools.pctrl.servo_manager import find_serial_ports

    print()
    print("═" * 55)
    print("  Feetech Servo Polarization Controller Setup")
    print("═" * 55)
    print("  Press Ctrl+C to abort at any time")
    print()

    cfg = ConfigManager(config_path)
    loaded = cfg.load()
    if loaded:
        print(f"Loaded existing config: {config_path}")
    else:
        print(f"Creating new config at: {config_path}")

    # Step 1: Configure Port and Baudrate
    _setup_banner("Step 1 / 3  —  Configure Communication Settings")
    ports = find_serial_ports() if not mock else []
    default_port = cfg.port if cfg.port else (ports[0] if ports else ("MOCK_PORT" if mock else ""))

    if mock:
        active_port = default_port or "MOCK_PORT"
        print(f"Mock mode: using port {active_port}")
    elif ports:
        print("Detected serial ports:")
        for idx, p in enumerate(ports, 1):
            print(f"  {idx}) {p}")
        port_choice = _setup_ask("Select port by number or enter custom port path", default_port)
        try:
            choice_idx = int(port_choice) - 1
            if 0 <= choice_idx < len(ports):
                active_port = ports[choice_idx]
            else:
                active_port = port_choice
        except ValueError:
            active_port = port_choice
    else:
        active_port = _setup_ask("Enter serial port (e.g. COM3 or /dev/ttyUSB0)", default_port)

    active_baud = cfg.baudrate if cfg.baudrate else 1000000
    
    # Configure servo type
    default_type = cfg.servo_type if cfg.servo_type else "sts"
    active_type = _setup_ask("Enter servo type (scs/sts)", default_type).lower()
    if active_type not in ("scs", "sts"):
        print("Invalid servo type. Defaulting to sts.")
        active_type = "sts"

    cfg.port = active_port
    cfg.baudrate = active_baud
    cfg.servo_type = active_type

    # Step 2: Scan for online servos
    _setup_banner("Step 2 / 3  —  Scan for Online Servos")
    do_full = full_scan
    if not full_scan:
        do_full_input = _setup_ask("Do you want to run a full scan of all 253 IDs? (y/n)", "n").lower()
        do_full = (do_full_input == "y")

    found_ids = []
    try:
        backend = ServoBackend(
            port=active_port,
            baudrate=active_baud,
            servo_type=active_type,
            mock=mock,
        )
        print("Scanning for online servos...")
        found_ids = backend.list_servos(stop_on_empty=not do_full)
        backend.close()
    except Exception as e:
        print(f"Error during scan: {e}")

    if not found_ids:
        print()
        print("  ❌ Error: No online servos found. Check connection and power.")
        sys.exit(1)

    print(f"\nDiscovered online servos: {found_ids}")

    # Clear old channels and configure new ones
    cfg._cfg["channels"] = []

    # Map discovered servos
    _setup_banner("Step 3 / 3  —  Configure Servo Alias and Waveplate Info")
    for idx, sid in enumerate(found_ids, 1):
        print(f"\nConfiguring servo ID {sid} ({idx}/{len(found_ids)}):")
        waveplate = _setup_ask_choice("  Waveplate type (QWP/HWP)", ["QWP", "HWP"])
        order = _setup_ask_int("  Order/slot index (1/2/3)", default=idx if idx <= 3 else 1, min_val=1, max_val=3)
        path = _setup_ask("  Optical path name (e.g. alice, bob)", "alice")
        wavelength = _setup_ask_int("  Wavelength in nm", default=1550, min_val=100, max_val=10000)

        # Add to configuration
        cfg.add_servo(
            path=path,
            wavelength=wavelength,
            waveplate=waveplate,
            order=order,
            servo_id=sid,
        )

        # Retrieve added servo reference to initialize software limits and cal fields
        servo = cfg.find_by_id(sid)
        if servo:
            servo["min_angle"] = -90.0
            servo["max_angle"] = 90.0
            servo["cal_offset_deg"] = 0.0
            servo["cal_scale"] = 1.0
            servo["fast_axis_angle"] = 0.0

    # Review and Save
    _setup_banner("Review and Save Configuration")
    cfg.summary()
    save_choice = _setup_ask("Do you want to save this configuration? (y/n)", "y").lower()
    if save_choice == "y":
        cfg.save()
        print()
        print("🎉 Configuration saved successfully!")
    else:
        print()
        print("Aborted. No changes saved.")


def run_init(config: str, full_scan: bool = False, redo: bool = False, mock: bool = False) -> None:
    """Launch CLI channel setup initialization."""
    from qtools.pctrl.config import ConfigManager
    cfg = ConfigManager(config)
    if not redo and cfg.load() and len(cfg.channels) > 0:
        print(f"Loaded existing config: {config}")
        print(f"Servo Port: {cfg.port} @ {cfg.baudrate} bps")
        print(f"Channels: {len(cfg.channels)}")
        for ch in cfg.channels:
            servos_str = ", ".join([f"{s['name']} (ID {s['servo_id']})" for s in ch["servos"]])
            print(f"  Channel '{ch['path']}' ({ch['wavelength']} nm): {servos_str}")
        print("Configuration already exists. Setup skipped.")
        return
    
    run_setup(config_path=config, full_scan=full_scan, mock=mock)


def _parse_set_item(cfg, item: str) -> dict:
    """Parse a single set fragment like 'name:45', 'name:hwp:22.5', or 'name:plus:10'."""
    parts = item.split(":")
    name = parts[0]

    is_sim = False
    rem_parts = parts[1:]

    if len(rem_parts) >= 1 and rem_parts[0].lower() in ("hwp", "qwp", "plate", "sim"):
        is_sim = True
        rem_parts = rem_parts[1:]

    is_relative = False
    rel_sign = 1.0
    val_str = ""

    if len(rem_parts) == 2:
        rel_type = rem_parts[0].lower()
        if rel_type == "plus":
            is_relative = True
            rel_sign = 1.0
        elif rel_type == "minus":
            is_relative = True
            rel_sign = -1.0
        else:
            raise ValueError(f"Unknown relative command type '{rel_type}'. Expected 'plus' or 'minus'.")
        val_str = rem_parts[1]
    elif len(rem_parts) == 1:
        val_str = rem_parts[0]
        if val_str.startswith("+"):
            is_relative = True
            rel_sign = 1.0
            val_str = val_str[1:]
        # bare "-N" is absolute negative angle, not a relative step
    else:
        raise ValueError(f"Invalid command format for '{item}'.")

    try:
        val = float(val_str)
    except ValueError as e:
        raise ValueError(f"Value '{val_str}' must be a number.") from e

    s = cfg.get_servo(name)
    if not s:
        # Allow numeric servo ID
        if name.isdigit():
            s = cfg.find_by_id(int(name))
    if not s:
        raise ValueError(f"Servo '{name}' not found.")

    return {
        "servo": s,
        "val": val,
        "is_sim": is_sim,
        "is_relative": is_relative,
        "rel_sign": rel_sign,
    }


def _resolve_channel_servos(cfg, target: str) -> list[dict]:
    """Resolve a channel by key, path, servo name, or ID to ordered servos."""
    try:
        resolution = resolve_target(cfg, target)
    except ValueError:
        return []

    servos = []
    for ch in resolution.channels:
        for s in ch["servos"]:
            if resolution.target_servo_name is not None:
                if s["name"] == resolution.target_servo_name:
                    servos.append(s)
            else:
                servos.append(s)
    return sorted(servos, key=lambda s: s["order"])


def _auto_detect_port(active_baud: int, active_type: str, mock: bool = False) -> str:
    """Return the first USB serial port with online servos.

    When ``mock`` is True, returns ``"MOCK_PORT"`` immediately.
    Otherwise delegates to servo_manager.auto_discover.
    Exits via sys.exit(1) if no usable port is found.
    """
    if mock:
        return "MOCK_PORT"

    from qtools.pctrl.servo_manager import auto_discover

    print("No serial port specified or configured. Scanning all USB serial ports...")
    disc = auto_discover(baudrate=active_baud, servo_type=active_type)
    if disc is None:
        print("Error: No online servos found on any USB serial port. Check connection and power.")
        sys.exit(1)
    return disc["port"]


def run_direct_set(config: str, set_str: str, speed_deg_s: float | None = None, ph_sts: Any | None = None, port: str | None = None, baud: int | None = None, servo_type: str | None = None, mock: bool = False, encode: bool = False, accurate: bool = False) -> None:
    """Directly set servo angles from command line.

    When ``encode`` is True, values are treated as raw encoder positions
    (0-4095 for STS, 0-1023 for SCS) instead of degrees.

    When ``accurate`` is True and the target is within 20 encoder counts
    of the current position, the servo first overshoots by 40 counts
    (clamped to limits) then approaches the target — compensating for
    gear backlash on small movements.
    """
    from qtools.pctrl.config import ConfigManager


    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    commands = []
    segments = [seg.strip() for seg in set_str.split(",") if seg.strip()]

    # Support multi-angle channel form: "alice:45,90,45" → map to channel servos by order
    if (
        len(segments) > 1
        and ":" in segments[0]
        and all(":" not in seg for seg in segments[1:])
    ):
        name, first_val = segments[0].split(":", 1)
        angle_tokens = [first_val] + segments[1:]
        # Only treat as multi-angle if remaining tokens are pure numbers (not plus/minus keywords alone)
        def _is_number_token(tok: str) -> bool:
            try:
                float(tok)
                return True
            except ValueError:
                return False

        if all(_is_number_token(t) for t in angle_tokens):
            channel_servos = _resolve_channel_servos(cfg, name)
            if channel_servos and len(channel_servos) == len(angle_tokens):
                for s, tok in zip(channel_servos, angle_tokens):
                    commands.append({
                        "servo": s,
                        "val": float(tok),
                        "is_sim": False,
                        "is_relative": False,
                        "rel_sign": 1.0,
                    })
            elif len(angle_tokens) == 1:
                # fall through to single-item parse below
                segments = [segments[0]]
            else:
                # Try mapping N angles onto a single named servo group by expanding names
                # If name is a servo, multi bare angles without names is invalid
                if not channel_servos:
                    print(
                        f"Error: Multi-angle set '{set_str}' requires channel path "
                        f"with {len(angle_tokens)} servos, or name:angle pairs."
                    )
                    sys.exit(1)
                print(
                    f"Error: Channel '{name}' has {len(channel_servos)} servo(s) "
                    f"but {len(angle_tokens)} angle(s) were provided."
                )
                sys.exit(1)

    if not commands:
        for item in segments:
            try:
                commands.append(_parse_set_item(cfg, item))
            except ValueError as e:
                print(f"Error: {e}")
                sys.exit(1)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)
    speed_val = int(round(speed_deg_s * 4096.0 / 360.0)) if speed_deg_s is not None else 114
    default_acc = 50

    # Determine hardware encoder max based on servo type
    if encode:
        enc_max = 1023 if active_type == "scs" else 4095

    try:
        for cmd in commands:
            s = cmd["servo"]

            # ── Compute target encoder position ──────────────────
            if encode:
                # Raw encoder mode: use value directly as encoder position
                val = int(round(cmd["val"]))
                clamped_enc = max(0, min(enc_max, val))
                lo = 0
                hi = enc_max
                label = f"encoder: {clamped_enc} (raw: {val})"
            else:
                zero = int(s.get("zero_position", 2048))
                dps = float(s.get("deg_per_step", 0.088))
                lo_deg = float(s.get("min_angle", -90.0))
                hi_deg = float(s.get("max_angle", 90.0))

                if cmd["is_relative"]:
                    curr_pos, _, result, _ = ph_sts.ReadPosSpeed(s["servo_id"])
                    if result != COMM_SUCCESS:
                        print(f"Error: Failed to query current position of servo '{s['name']}' (ID: {s['servo_id']}).")
                        sys.exit(1)
                    curr_phys = (curr_pos - zero) * dps
                    if cmd["is_sim"]:
                        scale = s.get("cal_scale", 1.0)
                        if abs(scale) < 1e-5:
                            scale = 1.0
                        offset = s.get("cal_offset_deg", 0.0)
                        curr_sim = scale * curr_phys + offset
                        target_sim = curr_sim + cmd["rel_sign"] * cmd["val"]
                        target_phys = (target_sim - offset) / scale
                    else:
                        target_phys = curr_phys + cmd["rel_sign"] * cmd["val"]
                else:
                    if cmd["is_sim"]:
                        scale = s.get("cal_scale", 1.0)
                        if abs(scale) < 1e-5:
                            scale = 1.0
                        offset = s.get("cal_offset_deg", 0.0)
                        target_phys = (cmd["val"] - offset) / scale
                    else:
                        target_phys = cmd["val"]

                clamped_ang = max(lo_deg, min(hi_deg, target_phys))
                enc = int(round(zero + clamped_ang / dps))
                lo = max(0, int(round(zero + lo_deg / dps)))
                hi = min(4095, int(round(zero + hi_deg / dps)))
                clamped_enc = max(lo, min(hi, enc))
                label = f"{clamped_ang:.2f}° (encoder: {clamped_enc})"

            # ── Overshoot two-step mode (backlash compensation) ──
            if accurate:
                curr, _, result, _ = ph_sts.ReadPosSpeed(s["servo_id"])
                if result == COMM_SUCCESS:
                    diff = abs(clamped_enc - curr)
                    if 0 < diff < 30:
                        # Prefer away from target, fallback toward target
                        to_target = 1 if clamped_enc >= curr else -1
                        for d in (-to_target, to_target):
                            cand = curr + d * 150
                            cand = max(lo, min(hi, cand))
                            if abs(cand - curr) >= 150:
                                overshoot = cand
                                break
                        else:
                            overshoot = clamped_enc  # neither direction has room

                        if overshoot != clamped_enc:
                            ph_sts.move(s["servo_id"], overshoot, speed_val, default_acc)
                            print(f"  {s['name']}: overshoot -> {overshoot} "
                                  f"(diff={diff} < 30, first step)")
                            time.sleep(0.15)

            # ── Final move ───────────────────────────────────────
            ph_sts.move(s["servo_id"], clamped_enc, speed_val, default_acc)
            print(f"Set {s['name']} -> {label} with speed {speed_val} steps/s")
    finally:
        if should_close:
            ph_sts.close()


def run_direct_get(config: str, get_str: str, ph_sts: Any | None = None, port: str | None = None, baud: int | None = None, servo_type: str | None = None, mock: bool = False) -> None:
    """Directly query servo angles from command line."""
    from qtools.pctrl.config import ConfigManager


    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    servos = []
    if get_str.lower() == "all":
        servos = cfg.all_servos()
    else:
        names = [n.strip() for n in get_str.split(",") if n.strip()]
        for name in names:
            s = None
            if name.isdigit():
                s = cfg.find_by_id(int(name))
            if not s:
                s = cfg.get_servo(name)
            if not s:
                print(f"Error: Servo name or ID '{name}' not found.")
                sys.exit(1)
            servos.append(s)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)
    try:
        for s in servos:
            pos, _, result, _ = ph_sts.ReadPosSpeed(s["servo_id"])
            if result == COMM_SUCCESS:
                zero = int(s.get("zero_position", 2048))
                dps = float(s.get("deg_per_step", 0.088))
                deg = (pos - zero) * dps
                scale = float(s.get("cal_scale", 1.0))
                if abs(scale) < 1e-5:
                    scale = 1.0
                offset = float(s.get("cal_offset_deg", 0.0))
                sim_deg = scale * deg + offset
                print(f"{s['name']}: servo_angle = {deg:.2f}°, simulated_plate_angle = {sim_deg:.2f}° (encoder: {pos})")
            else:
                print(f"{s['name']} (ID {s['servo_id']}): Offline")
    finally:
        if should_close:
            ph_sts.close()


def run_status(config: str, port: str | None = None, baud: int | None = None, target: str | None = None, servo_type: str | None = None, mock: bool = False) -> None:
    """Display config key info, connection settings, and servo details in table format."""
    from qtools.pctrl.config import ConfigManager

    cfg = ConfigManager(config)
    loaded = cfg.load()

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if mock and not active_port:
        active_port = "MOCK_PORT"

    # Check if target is a port override
    filter_target = None
    if target:
        target_lower = target.lower()
        if target_lower.startswith("com") or "/dev/" in target_lower or "tty" in target_lower:
            active_port = target
        else:
            filter_target = target

    print("\n" + "=" * 80)
    print("                      POLARIZATION CONTROLLER STATUS")
    print("=" * 80)
    print(f"Config File : {cfg.config_path.resolve() if hasattr(cfg.config_path, 'resolve') else cfg.config_path}")
    if not loaded:
        print("Status      : File not found (using default configuration)")

    print(f"Serial Port : {active_port or '(Not configured)'}")
    print(f"Baud Rate   : {active_baud}")
    if mock:
        print("Mode        : Mock / simulation")
    print("-" * 80)

    # Resolve filter_target to a servo set
    if filter_target:
        servos = _filter_servos(cfg, filter_target)
    else:
        servos = cfg.all_servos()

    # Attempt to connect and fetch current positions
    ph_sts = None
    should_close = False
    if active_port and servos:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            pass

    try:
        _print_channel_status(cfg, servos, ph_sts)
    finally:
        if should_close and ph_sts is not None:
            ph_sts.close()


def _filter_servos(cfg, target: str) -> list[dict]:
    """Return servos matched by target (name, ID, channel key, channel path)."""
    try:
        resolution = resolve_target(cfg, target)
    except ValueError:
        return []

    if not resolution.channels:
        return []

    servos = []
    for ch in resolution.channels:
        for s in ch["servos"]:
            if resolution.target_servo_name is not None:
                if s["name"] == resolution.target_servo_name:
                    servos.append(s)
            else:
                servos.append(s)
    return servos


def _print_channel_status(cfg, servos: list[dict], ph_sts=None) -> None:
    """Print the servo status table in channel-grouped format.

    If *ph_sts* is not None it is used to query live positions; otherwise
    positions are shown as offline.
    """
    # Group servos by channel (path, wavelength) to avoid merging
    # same-path different-wavelength channels.
    channel_map: dict[tuple[str, int], dict] = {}
    for ch in cfg.channels:
        channel_map[(ch["path"].lower(), int(ch["wavelength"]))] = ch

    path_to_servos: dict[tuple[str, int], list[dict]] = {}
    for s in servos:
        for ch in cfg.channels:
            if s in ch["servos"]:
                key = (ch["path"].lower(), int(ch["wavelength"]))
                path_to_servos.setdefault(key, []).append(s)
                break

    if not servos:
        print("No servos configured.")
        return

    print("Servo Channel Table:")
    for (path, wavelength), group_servos in path_to_servos.items():
        ch = channel_map.get((path, wavelength), {})
        tag = f"{ch.get('path', path)}{ch.get('wavelength', wavelength)}nm"
        print(f"\nChannel: {tag} ({ch.get('name', '')})")

        print(f"  {'Servo Name':<24} | {'Group':<8} | {'ID':<3} | "
              f"{'Current':<16} | {'Fast Axis':<9} | "
              f"{'Limits':<26} | {'Zero (Deg/St)':<15}")
        print("  " + "-" * 121)

        for s in group_servos:
            name = s["name"]
            group = s.get("group", path)
            sid = s["servo_id"]
            zero_position = int(s["zero_position"])
            deg_per_step = float(s.get("deg_per_step", 0.088))
            min_angle = float(s.get("min_angle", -90.0))
            max_angle = float(s.get("max_angle", 90.0))
            fast_axis = float(s.get("fast_axis_angle", 0.0))

            min_steps = int(round(zero_position + min_angle / deg_per_step))
            max_steps = int(round(zero_position + max_angle / deg_per_step))
            exact_min = (min_steps - zero_position) * deg_per_step
            exact_max = (max_steps - zero_position) * deg_per_step
            limits_str = f"{exact_min:.3f}({min_steps}), {exact_max:.3f}({max_steps})"

            zero_str = f"0.000 ({zero_position})"
            fast_axis_str = f"{fast_axis:.3f}"

            phys_str = "-"
            if ph_sts:
                try:
                    pos, _, result, _ = ph_sts.ReadPosSpeed(sid)
                except Exception:
                    pos, result = 0, -1
                if result == COMM_SUCCESS:
                    phys_deg = (pos - zero_position) * deg_per_step
                    phys_str = f"{phys_deg:.3f} ({pos})"
                else:
                    phys_str = "Offline"

            print(f"  {name:<24} | {group:<8} | {sid:<3} | "
                  f"{phys_str:<16} | {fast_axis_str:<9} | "
                  f"{limits_str:<26} | {zero_str:<15}")
    print()


def run_reset(config: str, port: str | None = None, baud: int | None = None, speed_deg_s: float | None = None, ph_sts: Any | None = None, target: str = "all", servo_type: str | None = None, mock: bool = False) -> None:
    """Move target servos to their configured zero (middle) positions.

    This moves servos *to* the zero_position — it does NOT change what
    zero_position is.  Use ``run_set_middle`` to redefine the middle.
    """
    from qtools.pctrl.config import ConfigManager
    import sys

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)
    speed_val = int(round(speed_deg_s * 4096.0 / 360.0)) if speed_deg_s is not None else 114
    default_acc = 50

    try:
        resolution = resolve_target(cfg, target)
        print(f"Resetting target '{target}' to middle position...")

        count = 0
        for ch in resolution.channels:
            for s in ch["servos"]:
                if resolution.target_servo_name is not None and s["name"] != resolution.target_servo_name:
                    continue

                zero_pos = s.get("zero_position", 2048)
                ph_sts.move(s["servo_id"], zero_pos, speed_val, default_acc)
                print(f"  Reset {s['name']} (ID {s['servo_id']}) to middle position (encoder: {zero_pos}) with speed {speed_val} steps/s")
                count += 1
        if count == 0:
            print("No matching servos found to reset.")
    finally:
        if should_close:
            ph_sts.close()


def run_limit(config: str, target: str = "all", min_angle: float = -90.0, max_angle: float = 90.0,
              port: str | None = None, baud: int | None = None, ph_sts: Any | None = None,
              servo_type: str | None = None, mock: bool = False) -> None:
    """Set software angle limits for target AND persist them to the servo EEPROM."""
    from qtools.pctrl.config import ConfigManager
    import sys

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud,
                                  servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)

    try:
        resolution = resolve_target(cfg, target)

        count = 0
        for ch in resolution.channels:
            for s in ch["servos"]:
                if resolution.target_servo_name is not None and s["name"] != resolution.target_servo_name:
                    continue
                req_min = servo_encoder_for_angle(s, min_angle)
                req_max = servo_encoder_for_angle(s, max_angle)
                min_pos, max_pos, ok = write_eeprom_limits(ph_sts, s, req_min, req_max)
                if not ok:
                    print(f"  ⚠️  {s['name']}: EEPROM write failed; config updated only")
                elif min_pos != req_min or max_pos != req_max:
                    print(f"  ⚠️  {s['name']}: limits clamp against the physical range "
                          f"-> encoder [{min_pos}, {max_pos}]")
                s["min_angle"] = min_angle
                s["max_angle"] = max_angle
                s["min_position"] = min_pos
                s["max_position"] = max_pos
                print(f"Set limits for '{s['name']}' (ID: {s['servo_id']}): "
                      f"[{min_angle}°, {max_angle}°] encoder [{min_pos}, {max_pos}] (written to EEPROM)")
                count += 1

        if count > 0:
            cfg.save()
            print(f"Saved limits for {count} servos to configuration.")
        else:
            print("No matching servos found to limit.")
    finally:
        if should_close:
            ph_sts.close()


def run_set_middle(config: str, target: str, port: str | None = None, baud: int | None = None, ph_sts: Any | None = None, servo_type: str | None = None, mock: bool = False) -> None:
    """Force setting current position as middle, update zero_position and limits, and save config."""
    from qtools.pctrl.config import ConfigManager
    import sys

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)

    # Identify target servos
    target_servos = []
    if target.lower() == "all":
        target_servos = cfg.all_servos()
    else:
        # Try finding by name
        s = cfg.get_servo(target)
        if s:
            target_servos = [s]
        else:
            # Try finding by ID
            try:
                sid = int(target)
                s = cfg.find_by_id(sid)
                if s:
                    target_servos = [s]
            except ValueError:
                pass
        
        if not target_servos:
            print(f"Error: Target '{target}' not found in configuration as a name or ID.")
            if should_close:
                ph_sts.close()
            sys.exit(1)

    try:
        updated_any = False
        for s in target_servos:
            pos, _, result, _ = ph_sts.ReadPosSpeed(s["servo_id"])
            if result == COMM_SUCCESS:
                print(f"Read current encoder for {s['name']} (ID {s['servo_id']}): {pos}")
                s["zero_position"] = int(pos)
                s["min_angle"] = -90.0
                s["max_angle"] = 90.0
                req_min = servo_encoder_for_angle(s, -90.0)
                req_max = servo_encoder_for_angle(s, 90.0)
                min_pos, max_pos, ok = write_eeprom_limits(ph_sts, s, req_min, req_max)
                s["min_position"] = min_pos
                s["max_position"] = max_pos
                s["phy_zero_angle"] = round(
                    pos * float(s.get("phy_angle_range", 300.0))
                    / float(s.get("phy_position_range", 1023)), 4)
                if not ok:
                    print(f"  ⚠️  {s['name']}: EEPROM write failed; config updated only")
                elif min_pos != req_min or max_pos != req_max:
                    print(f"  ⚠️  {s['name']}: ±90° clamps against the physical range "
                          f"-> encoder [{min_pos}, {max_pos}]")
                print(f"Updated {s['name']}: zero_position = {pos}, min_position = {min_pos}, "
                      f"max_position = {max_pos}, limits = [-90.0°, 90.0°] (written to EEPROM)")
                updated_any = True
            else:
                print(f"Error: Failed to read current position for {s['name']} (ID {s['servo_id']})")

        if updated_any:
            cfg.save()
            print("Successfully updated configuration middle positions, limits, and EEPROM.")
    finally:
        if should_close:
            ph_sts.close()


def run_device_subcommand(config: str, device_type: str, device_args: list[str], mock: bool = False) -> None:
    """Connect/search tdc or powermeter devices and save to config."""
    import sys
    from qtools.pctrl.config import ConfigManager

    mgr = ConfigManager.resolve(config)

    if device_type == "tdc":
        if len(device_args) >= 1:
            active_path = device_args[0]
            if len(device_args) >= 2:
                active_backend = device_args[1]
            else:
                # No backend given — default to the registered TDC1 backend
                # (exp_s15_tdc1 or s15_tdc1), which is what discovery returns.
                try:
                    from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
                    active_backend = DEFAULT_TDC1_BACKEND
                except Exception:
                    active_backend = "exp_s15_tdc1"
        else:
            print("Auto-scanning TDC...")
            try:
                from qtools.tdc.connection import discover_all as tdc_discover_all
                tdc_devices = tdc_discover_all(method="usb", timeout=1.0)
                if not tdc_devices:
                    tdc_devices = tdc_discover_all(method="ethernet", timeout=1.0)
                if tdc_devices:
                    active_path = tdc_devices[0].device_path
                    active_backend = tdc_devices[0].backend_name
                    print(f"Discovered TDC: {active_path} (backend: {active_backend})")
                else:
                    print("Error: No TDC devices discovered on the system.")
                    sys.exit(1)
            except Exception as e:
                print(f"Error during TDC scan: {e}")
                sys.exit(1)

        try:
            print(f"Connecting to TDC '{active_backend}' at {active_path}...")
            from qtools import tdc as _tdc_pkg
            with _tdc_pkg.get_device(active_backend, active_path):
                # Connection established and closed automatically via the
                # context manager (TDC.backend.connect() / disconnect()).
                pass
            # Persist the connection to the main config detectors: section
            # (source of truth), the legacy flat key, and the cal/opt configs.
            from qtools.pctrl.config import CalConfigManager, OptConfigManager
            for mgr2 in (CalConfigManager(), OptConfigManager()):
                mgr2._cfg.setdefault("devices", {}).setdefault("tdc", {})["backend"] = active_backend
                mgr2.set_device_port("tdc", active_path)
                mgr2.save()
            mgr._cfg.setdefault("detectors", {}).setdefault("tdc", {})["backend"] = active_backend
            mgr.set_device_port("tdc", active_path)
            mgr._cfg.setdefault("connection", {})["tdc"] = {
                "device_path": active_path, "backend": active_backend,
            }
            mgr.save()
            print(f"[SUCCESS] Connected and saved TDC settings for port {active_path}.")
        except Exception as e:
            print(f"[ERROR] TDC Connection failed: {e}")
            sys.exit(1)

    elif device_type == "powermeter":
        if len(device_args) >= 1:
            active_addr = device_args[0]
            active_backend = device_args[1] if len(device_args) >= 2 else None
        else:
            print("Auto-discovering Powermeter...")
            try:
                from qtools.powermeter.cli import auto_detect_connected_device
                active_addr, active_backend = auto_detect_connected_device()
                if active_addr:
                    print(f"Discovered Powermeter: {active_addr} (backend: {active_backend})")
                else:
                    print("Error: No Powermeter devices discovered on the system.")
                    sys.exit(1)
            except Exception as e:
                print(f"Error during auto-discovery: {e}")
                sys.exit(1)

        try:
            print(f"Connecting to Powermeter '{active_backend}' at {active_addr}...")
            from qtools import powermeter as _pm
            device = _pm.get_device(active_backend or "mock", active_addr)
            device.connect()
            device.disconnect()
            from qtools.pctrl.config import CalConfigManager, OptConfigManager
            for mgr2 in (CalConfigManager(), OptConfigManager()):
                mgr2._cfg.setdefault("devices", {}).setdefault("powermeter", {})["backend"] = active_backend or "s15"
                mgr2.set_device_port("powermeter", active_addr)
                mgr2.save()
            mgr._cfg.setdefault("detectors", {}).setdefault("powermeter", {})["backend"] = active_backend or "s15"
            mgr.set_device_port("powermeter", active_addr)
            mgr.save()
            print(f"[SUCCESS] Connected and saved Powermeter settings for address {active_addr}.")
        except Exception as e:
            print(f"[ERROR] Powermeter Connection failed: {e}")
            sys.exit(1)






def run_list(config: str, port: str | None = None, baud: int | None = None, full_scan: bool = False, servo_type: str | None = None, mock: bool = False) -> None:
    """Scan the serial port and list all discovered online servos."""
    from qtools.pctrl.config import ConfigManager
    from qtools.pctrl.servo_manager import find_serial_ports
    
    cfg = ConfigManager(config)
    cfg.load()
    
    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if mock and not active_port:
        active_port = "MOCK_PORT"
    
    if not active_port:
        print("No serial port specified or configured. Scanning all USB serial ports...")
        ports = find_serial_ports()
        if not ports:
            print("No USB serial ports detected. Check connections.")
            return
        for p in ports:
            print(f"Scanning port {p} at baudrate {active_baud}...")
            try:
                backend = ServoBackend(port=p, baudrate=active_baud, servo_type=active_type, mock=mock)
                found_ids = backend.list_servos(stop_on_empty=not full_scan)
                backend.close()
            except Exception:
                found_ids = []
                
            if found_ids:
                print(f"  Found online servos on port {p}: {found_ids}")
            else:
                print(f"  No servos found on port {p}.")
    else:
        print(f"Scanning port {active_port} at baudrate {active_baud}...")
        try:
            backend = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            found_ids = backend.list_servos(stop_on_empty=not full_scan)
            backend.close()
        except Exception:
            found_ids = []
            
        if found_ids:
            print(f"Found online servos: {found_ids}")
        else:
            print("No online servos found. Check connection, power, and baudrate.")





def resolve_config_path(config_arg: str) -> str:
    """Resolve config path to a file, scanning directories for any yaml files."""
    import glob
    from pathlib import Path
    path = Path(config_arg)
    if path.is_dir():
        yamls = glob.glob(str(path / "*.yaml")) + glob.glob(str(path / "*.yml"))
        if yamls:
            return yamls[0]
        else:
            return str(path / "pctrl_config.yaml")
    return str(path)


def run_direct_set_id(
    config: str,
    ids: list[int],
    port: str | None = None,
    baud: int | None = None,
    servo_type: str | None = None,
    mock: bool = False,
) -> None:
    """Change a servo ID on the bus: ids is [new_id] or [old_id, new_id]."""
    from qtools.pctrl.config import ConfigManager

    cfg = ConfigManager(config)
    cfg.load()

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    if len(ids) == 1:
        new_id = ids[0]
        old_id = None
    elif len(ids) >= 2:
        old_id, new_id = ids[0], ids[1]
    else:
        print("Error: Provide 'new_id' or 'old_id new_id'.")
        sys.exit(1)

    try:
        backend = ServoBackend(
            port=active_port,
            baudrate=active_baud,
            servo_type=active_type,
            mock=mock,
        )
    except Exception as e:
        print(f"Error: Failed to connect to serial port {active_port}: {e}")
        sys.exit(1)

    try:
        if old_id is None:
            online_ids = backend.list_servos(stop_on_empty=False)
            if not online_ids:
                print("Error: No online servos found. Check connection and power.")
                sys.exit(1)
            if len(online_ids) > 1:
                print(f"Error: Multiple online servos found {online_ids}.")
                print("Specify both old_id and new_id, or connect only one servo.")
                sys.exit(1)
            old_id = online_ids[0]

        print(f"Changing servo ID from {old_id} to {new_id} ...")
        backend.release(old_id)
        success = backend.set_id(new_id=new_id, old_id=old_id)
        if not success:
            print("Error: Failed to change servo ID.")
            sys.exit(1)

        s = cfg.find_by_id(old_id)
        if s is not None:
            cfg.update_servo(s["name"], servo_id=new_id)
            cfg.save()
            print(f"Updated config: servo '{s['name']}' servo_id {old_id} -> {new_id}")
        print(f"Succeeded: servo ID {old_id} -> {new_id}")
    finally:
        backend.close()


def run_torque_control(config: str, enable: bool, port: str | None = None, baud: int | None = None, ph_sts: Any | None = None, target: str = "all", servo_type: str | None = None, mock: bool = False) -> None:
    """Enable (Torque On) or disable (Torque Off) torque locks for configured servos (filtered by target name/ID or 'all')."""
    from qtools.pctrl.config import ConfigManager

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    should_close = False
    if ph_sts is None:
        try:
            ph_sts = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
            should_close = True
        except Exception:
            print(f"Error: Failed to connect to serial port {active_port}")
            sys.exit(1)
    try:
        val = 1 if enable else 0
        status_str = "ON (Torque On / Locked)" if enable else "OFF (Torque Off / Free)"

        print(f"Turning Torque {status_str} for target: '{target}'...")

        resolution = resolve_target(cfg, target)

        count = 0
        for ch in resolution.channels:
            for s in ch["servos"]:
                if resolution.target_servo_name is not None and s["name"] != resolution.target_servo_name:
                    continue
                success = ph_sts.lock(s["servo_id"]) if enable else ph_sts.release(s["servo_id"])
                if success:
                    print(f"  Servo '{s['name']}' (ID: {s['servo_id']}): Success")
                    count += 1
                else:
                    print(f"  Servo '{s['name']}' (ID: {s['servo_id']}): Failed (communication error)")
        print(f"Done. Successfully set torque for {count} servos.")
    finally:
        if should_close:
            ph_sts.close()


def run_threshold(config: str, threshold: int | None, target: str = "all", port: str | None = None, baud: int | None = None, servo_type: str | None = None, mock: bool = False) -> None:
    """Set or read servo deadband (CW_DEAD / CCW_DEAD) threshold.

    When *threshold* is ``None``, reads and displays current values only.
    When *threshold* is an int, writes the new value to EEPROM.
    """
    from qtools.pctrl.config import ConfigManager

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    active_port = port if port else cfg.port
    active_baud = baud if baud else cfg.baudrate
    active_type = servo_type if servo_type else cfg.servo_type
    if not active_port:
        active_port = _auto_detect_port(active_baud, active_type, mock=mock)

    if threshold is not None and (threshold < 0 or threshold > 255):
        print("Error: Threshold must be in range [0, 255].")
        sys.exit(1)

    # Resolve target servos
    resolution = resolve_target(cfg, target)
    all_servos: list[dict] = []
    for ch in resolution.channels:
        for s in ch["servos"]:
            if resolution.target_servo_name is not None and s["name"] != resolution.target_servo_name:
                continue
            all_servos.append(s)

    if not all_servos:
        print(f"No servos matched target '{target}'.")
        sys.exit(1)

    # Connect
    should_close = False
    try:
        backend = ServoBackend(port=active_port, baudrate=active_baud, servo_type=active_type, mock=mock)
        should_close = True
    except Exception:
        print(f"Error: Failed to connect to serial port {active_port}")
        sys.exit(1)

    try:
        for s in all_servos:
            sid = s["servo_id"]
            name = s["name"]

            # Read current deadband
            current = backend.get_deadband(sid)
            if current is None:
                print(f"  {name} (ID {sid}): Failed to read current deadband.\n")
                continue

            print(f"  {name} (ID {sid}): current CW={current['cw']}, CCW={current['ccw']}")

            if threshold is None:
                # Read-only mode
                continue

            # Write new deadband
            ok = backend.set_deadband(sid, cw=threshold)
            if not ok:
                print(f"    Failed to write deadband!\n")
                continue

            # Verify
            verify = backend.get_deadband(sid)
            if verify:
                print(f"    -> updated CW={verify['cw']}, CCW={verify['ccw']}")
            else:
                print(f"    -> written (verification read failed)")
            print()
    finally:
        if should_close:
            backend.close()


# ==============================================================
# End of functions.py helper scripts
# ==============================================================
