"""Interactive REPL shell for polarization measurement motor control."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


class PolmeasRepl:
    """Interactive command-line shell for managing connected rotation stages."""

    def __init__(self, config_path: str = "polmeas_config.yaml"):
        from qtools.pmeas.config import ConfigManager
        self.cfg = ConfigManager.resolve(config_path)

    def run(self) -> None:
        from qtools.pmeas.commands.utils import _resolve_motor

        print("=" * 50)
        print("   Polarization Meas — Motor Control REPL")
        print("=" * 50)
        print("Type 'help' for commands, 'exit' to quit.\n")

        stages: dict[str, object] = {}
        active_port: str | None = None

        polmeas_devices = {
            str(d.get("serial") or ""): d
            for d in self.cfg.get_all_devices()
        }

        try:
            ports = _resolve_motor(allow_multiple=True)
            if ports and ports[0] is not None:
                ports = [str(getattr(s, "port", None) or getattr(s, "_port", "")) for s in ports]
            else:
                ports = []
        except SystemExit:
            ports = []

        if ports:
            if len(ports) == 1:
                print(f"Connecting to single device on {ports[0]}...")
            else:
                print(f"Connecting to {len(ports)} device(s): {ports}")

            for port in ports:
                try:
                    stage = self.mgr.get_motor(port)
                    stages[port] = stage
                    name = stage.get_stage_name()
                    print(f"  [{port}] {name}")
                    if active_port is None:
                        active_port = port
                except Exception as exc:
                    print(f"  [ERROR on {port}] {exc}")

            if stages:
                print(f"\nActive device: [{active_port}] {stages[active_port].get_stage_name()}\n")
            else:
                print("[WARN] Could not connect to any motor.\n")
        else:
            print("[WARN] No motor detected. Use 'connect <port|name|id>' first.\n")

        def _active_stages():
            return list(stages.items())

        def _resolve_target(target: str) -> str:
            devices = list_devices()
            if not devices:
                raise LookupError("No K10CR1 devices detected.")

            sm_config = sm_load_config()

            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(devices):
                    return devices[idx - 1][0]
                raise LookupError(f"Invalid index {idx}. Use 1-{len(devices)}.")

            connected_ports = [d[0] for d in devices]
            if target in connected_ports:
                return target

            if "/" in target or target.upper().startswith("COM"):
                return target

            for d in polmeas_devices.values():
                if d.get("name") == target:
                    for p, label in devices:
                        if d.get("serial", "") in label:
                            return p
                    raise LookupError(f"Device '{target}' is configured but not connected.")

            for sn, info in sm_config.items():
                if info.get("name") == target:
                    for p, label in devices:
                        if sn in label:
                            return p
                    raise LookupError(f"Device '{target}' (SN: {sn}) is configured but not connected.")

            for p, label in devices:
                if target in label:
                    return p

            raise LookupError(f"Target '{target}' does not match any connected device.")

        try:
            while True:
                try:
                    prompt_label = f"pmeas ({active_port})> " if active_port else "pmeas> "
                    line = input(prompt_label).strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting REPL.")
                    break

                if not line:
                    continue

                parts = line.split()
                cmd = parts[0].lower()

                if cmd in ("exit", "quit", "q"):
                    break

                elif cmd == "help":
                    print("\nAvailable REPL commands:")
                    print("  devices               List all connected devices with status and active mark")
                    print("  use <port|name|id>    Switch active device")
                    print("  connect <port|name>   Connect to a new device")
                    print("  disconnect [<port>]   Disconnect device (or active device)")
                    print("  status                Query status of active device")
                    print("  move <angle> [all]    Move active device (or all) to absolute angle")
                    print("  moveby <deg> [all]    Rotate active device (or all) by relative angle")
                    print("  home [all]            Home active device (or all)")
                    print("  zero [all]            Move to zero position (0°)")
                    print("  setzero <deg>         Set zero-offset for active device")
                    print("  speed <deg/s>         Set max velocity for active device")
                    print("  identify              Blink LED on active device")
                    print("  help                  Show this help message")
                    print("  exit / quit           Exit the REPL\n")

                elif cmd == "devices":
                    connected = list_devices()
                    print("\nConnected devices:")
                    for port, stage_obj in _active_stages():
                        active_mark = "  <-- active" if port == active_port else ""
                        print(f"  [{port}] {stage_obj.get_stage_name()}{active_mark}")

                elif cmd == "use":
                    if len(parts) < 2:
                        print("Usage: use <port|name|id>")
                        continue
                    try:
                        resolved_p = _resolve_target(parts[1])
                        if resolved_p in stages:
                            active_port = resolved_p
                            print(f"Switched active device to [{active_port}] {stages[active_port].get_stage_name()}")
                        else:
                            print(f"Device [{resolved_p}] is not connected. Use 'connect {parts[1]}' first.")
                    except LookupError as err:
                        print(f"[ERROR] {err}")

                elif cmd == "connect":
                    if len(parts) < 2:
                        print("Usage: connect <port|name|id>")
                        continue
                    try:
                        resolved_p = _resolve_target(parts[1])
                        if resolved_p in stages:
                            active_port = resolved_p
                            print(f"Already connected to [{resolved_p}]. Set as active.")
                        else:
                            stage = self.mgr.get_motor(resolved_p)
                            stages[resolved_p] = stage
                            active_port = resolved_p
                            print(f"[OK] Connected [{resolved_p}] {stage.get_stage_name()} (active)")
                    except Exception as exc:
                        print(f"[ERROR] Failed to connect: {exc}")

                elif cmd == "disconnect":
                    tgt = parts[1] if len(parts) > 1 else active_port
                    if not tgt or tgt not in stages:
                        print(f"No device to disconnect.")
                        continue
                    try:
                        stages[tgt].disconnect()
                        del stages[tgt]
                        print(f"[OK] Disconnected [{tgt}].")
                        if active_port == tgt:
                            active_port = list(stages.keys())[0] if stages else None
                            if active_port:
                                print(f"Active device is now [{active_port}].")
                    except Exception as exc:
                        print(f"[ERROR] Disconnect failed: {exc}")

                elif cmd == "status":
                    if not active_port or active_port not in stages:
                        print("No active device. Use 'connect <port|name>' first.")
                        continue
                    st = stages[active_port]
                    pos = st.get_position()
                    raw = st._motor.angle if st._motor else 0.0
                    print(f"Device:         [{active_port}] {st.get_stage_name()}")
                    print(f"Serial:         {st.serial}")
                    print(f"Current Angle:  {pos:.4f}° (Physical: {raw:.4f}°, Zero Offset: {st.zero_offset:.4f}°)")
                    print(f"Velocity:       {st.get_velocity():.2f}°/s")

                elif cmd in ("move", "moveto", "goto"):
                    if len(parts) < 2:
                        print("Usage: move <angle> [all]")
                        continue
                    try:
                        ang = float(parts[1])
                    except ValueError:
                        print("[ERROR] Angle must be a number.")
                        continue

                    do_all = len(parts) > 2 and parts[2].lower() == "all"
                    target_stages = _active_stages() if do_all else ([(active_port, stages[active_port])] if active_port and active_port in stages else [])
                    if not target_stages:
                        print("No active device.")
                        continue

                    for p, st in target_stages:
                        print(f"Moving [{p}] to {ang:.4f}° ... ", end="", flush=True)
                        st.move_to(ang)
                        st.wait_move()
                        print(f"Done ({st.get_position():.4f}°)")

                elif cmd == "moveby":
                    if len(parts) < 2:
                        print("Usage: moveby <degrees> [all]")
                        continue
                    try:
                        deg = float(parts[1])
                    except ValueError:
                        print("[ERROR] Degrees must be a number.")
                        continue

                    do_all = len(parts) > 2 and parts[2].lower() == "all"
                    target_stages = _active_stages() if do_all else ([(active_port, stages[active_port])] if active_port and active_port in stages else [])
                    if not target_stages:
                        print("No active device.")
                        continue

                    for p, st in target_stages:
                        print(f"Rotating [{p}] by {deg:+.4f}° ... ", end="", flush=True)
                        st.move_by(deg)
                        st.wait_move()
                        print(f"Done ({st.get_position():.4f}°)")

                elif cmd == "home":
                    do_all = len(parts) > 1 and parts[1].lower() == "all"
                    target_stages = _active_stages() if do_all else ([(active_port, stages[active_port])] if active_port and active_port in stages else [])
                    if not target_stages:
                        print("No active device.")
                        continue

                    for p, st in target_stages:
                        print(f"Homing [{p}] ... ", end="", flush=True)
                        st.home()
                        print(f"Done ({st.get_position():.4f}°)")

                elif cmd == "zero":
                    do_all = len(parts) > 1 and parts[1].lower() == "all"
                    target_stages = _active_stages() if do_all else ([(active_port, stages[active_port])] if active_port and active_port in stages else [])
                    if not target_stages:
                        print("No active device.")
                        continue

                    for p, st in target_stages:
                        print(f"Moving [{p}] to zero (0°) ... ", end="", flush=True)
                        st.move_to(0.0)
                        st.wait_move()
                        print(f"Done ({st.get_position():.4f}°)")

                elif cmd == "setzero":
                    if len(parts) < 2:
                        print("Usage: setzero <offset_deg>")
                        continue
                    try:
                        off = float(parts[1])
                    except ValueError:
                        print("[ERROR] Offset must be a number.")
                        continue
                    if not active_port or active_port not in stages:
                        print("No active device.")
                        continue
                    st = stages[active_port]
                    st.set_zero_offset(off)
                    print(f"[OK] Set zero offset on [{active_port}] to {off:.4f}°. Current angle: {st.get_position():.4f}°")

                elif cmd in ("speed", "velocity"):
                    if len(parts) < 2:
                        print("Usage: speed <deg_per_sec>")
                        continue
                    try:
                        vel = float(parts[1])
                    except ValueError:
                        print("[ERROR] Velocity must be a number.")
                        continue
                    if not active_port or active_port not in stages:
                        print("No active device.")
                        continue
                    st = stages[active_port]
                    st.set_velocity(vel)
                    print(f"[OK] Set velocity on [{active_port}] to {vel:.2f}°/s")

                elif cmd == "identify":
                    if not active_port or active_port not in stages:
                        print("No active device.")
                        continue
                    st = stages[active_port]
                    st._motor.identify()
                    print(f"[OK] Blink command sent to [{active_port}].")

                else:
                    print(f"Unknown command '{cmd}'. Type 'help' for available commands.")

        finally:
            print("\nCleaning up REPL motor connections...")
            for port, stage_obj in stages.items():
                try:
                    stage_obj.disconnect()
                except Exception:
                    pass
            disconnect_all()
            print("REPL session ended.")
