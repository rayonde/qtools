"""Config command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from qtools.motor.cli import cmd_config as sm_cmd_config
from qtools.pmeas.config import ConfigManager


def cmd_config(args: argparse.Namespace) -> None:
    config_path = args.config
    if args.date and not config_path:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d") if args.date == "today" else args.date
        config_path = Path.cwd() / f"polmeas_config_{date_str}.yaml"

    cfg = ConfigManager.resolve(config_path)

    if args.sub is None:
        cfg.load_or_create()
        sm_cmd_config(args)
        cfg.load()
        cfg.summary()
        return

    if args.sub == "archive":
        _cmd_config_archive(cfg, args)
        return

    loaded = cfg.load()

    if not loaded:
        print(f"No config file at '{cfg.config_path}'.")
        print("Run 'pmeas calibrate' first, or 'pmeas config init'.")
        if args.sub == "init":
            _do_config_init(cfg, args)
        return

    if args.sub == "show":
        cfg.summary()
    elif args.sub == "latest":
        cal = cfg.get_calibration("latest")
        if cal:
            print("Latest calibration:")
            _print_calibration(cal)
        else:
            print("No calibrations stored.")
    elif args.sub == "init":
        _do_config_init(cfg, args)


def _cmd_config_archive(cfg: ConfigManager, args: argparse.Namespace) -> None:
    archive_path = cfg.archive()
    print(f"Config archived to: {archive_path}")


def _print_calibration(cal: dict) -> None:
    print(f"  Timestamp:  {cal.get('timestamp', 'N/A')}")
    print(f"  Wavelength: {cal.get('wavelength', cal.get('wavelength_nm', 'N/A'))} nm")
    print(f"  θ₀ offset:  {cal.get('theta_0', cal.get('zero_offset', 0.0)):.4f}°")
    print(f"  Visibility: {cal.get('visibility', 0.0):.4f}")
    print(f"  R²:         {cal.get('r_squared', 0.0):.6f}")
    print("  Bases:")
    bases = cal.get("bases", cal.get("target_angles", {}))
    for state, ang in bases.items():
        print(f"    {state}: {ang:.4f}°")


def _prompt(msg: str, default: str = "") -> str:
    prompt = f"{msg}" + (f" [{default}]: " if default else ": ")
    try:
        val = input(prompt).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(1)


def _prompt_yn(msg: str, default: bool = True) -> bool:
    yn = _prompt(msg, "Y" if default else "N").lower()
    if yn in ("y", "yes"):
        return True
    if yn in ("n", "no"):
        return False
    return default


def _auto_scan_powermeter() -> dict:
    try:
        from qtools.powermeter.cli import auto_detect_connected_device as pm_auto_detect
        addr, backend = pm_auto_detect()
        if addr and backend:
            print(f"    {addr}  —  {backend}")
            return {"backend": backend, "port": addr}
        print("    powermeter  not found")
    except ImportError:
        print("    powermeter  (powermeter package not installed)")
    except Exception as e:
        print(f"    powermeter  scan error: {e}")
    return {"backend": "", "port": ""}


def _auto_scan_tdc() -> dict:
    try:
        from qtools.tdc.connection import discover_all as tdc_discover_all
        tdc_devices = tdc_discover_all(method="usb", timeout=1.0)
        if tdc_devices:
            dev = tdc_devices[0]
            print(f"    {dev.device_path}  —  {dev.backend_name}")
            return {"backend": dev.backend_name or "", "port": dev.device_path or ""}
        tdc_net = tdc_discover_all(method="ethernet", timeout=1.0)
        if tdc_net:
            dev = tdc_net[0]
            print(f"    {dev.device_path}  —  {dev.backend_name}  (network)")
            return {"backend": dev.backend_name or "", "port": dev.device_path or ""}
        print("    tdc         not found")
    except ImportError:
        print("    tdc         (tdc package not installed)")
    except Exception as e:
        print(f"    tdc         scan error: {e}")
    return {"backend": "", "port": ""}


def _do_config_init(cfg: ConfigManager, args: argparse.Namespace) -> None:
    print("\n" + "═" * 60)
    print("  PMEAS Configuration Setup")
    print("═" * 60)

    cfg.load_or_create()

    print("\n── Experiment ──")
    cfg._cfg["exp"] = _prompt("Experiment name", cfg._cfg.get("exp", ""))
    cfg._cfg["author"] = _prompt("Author", cfg._cfg.get("author", ""))

    print("\n── Detectors ──")
    existing = dict(cfg._cfg.get("detectors", {}))

    use_tdc = _prompt_yn("  Use TDC?", bool(existing.get("tdc", {}).get("port")))
    use_pm  = _prompt_yn("  Use Powermeter?", bool(existing.get("powermeter", {}).get("port")))

    # 抑制 fpfind / numpy 的 extended-precision float 警告
    import warnings
    warnings.filterwarnings(
        "ignore",
        message="Extended-precision floats.*",
        category=UserWarning,
    )

    detectors = cfg._cfg.setdefault("detectors", {})

    print("  Scanning for connected detectors...")
    if use_pm:
        detectors["powermeter"] = _auto_scan_powermeter()
    else:
        print("  Powermeter:  skipped (disabled)")
        detectors["powermeter"] = {"backend": "", "port": ""}

    if use_tdc:
        detectors["tdc"] = _auto_scan_tdc()
    else:
        print("  TDC:  skipped (disabled)")
        detectors["tdc"] = {"backend": "", "port": ""}

    print("\n── Scan for motors ──")
    try:
        from qtools.motor.backends.motor import list_devices
        import re as _re
        motors = list_devices()
        if not motors:
            print("  [!] No K10CR1 motors detected. Ensure USB/power.")
            print("  → Run 'pmeas motor config' later to connect devices.")
        else:
            print(f"  Found {len(motors)} device(s) on ports:")
            for port, label in motors:
                print(f"    {port}  —  {label}")

            print(f"\n  Configure each device:")
            for port, label in motors:
                m = _re.search(r"SN=([a-zA-Z0-9]+)", label)
                sn = _re.sub(r"\D", "", m.group(1)) if m else port
                existing = cfg.get_device(sn) or {}
                print(f"\n  --- Device on {port}  (SN={sn}) ---")

                if existing.get("name"):
                    print(f"    Current config: name={existing.get('name', '?')}  "
                          f"path={existing.get('optical_path', '?')}  "
                          f"role={existing.get('role','?')}")
                    if not _prompt_yn("    Reconfigure?", False):
                        continue

                optical_path = _prompt("    Optical path (alice / bob)",
                                       existing.get("optical_path", existing.get("path", "")))
                role = _prompt("    Role (basis / compensation)",
                               existing.get("role", "basis"))
                wp = _prompt("    Waveplate type (hwp / qwp)",
                             existing.get("waveplate", "hwp"))
                wl = int(_prompt("    Wavelength (nm)",
                                 str(existing.get("wavelength", 1550))))
                zero_off = float(existing.get("zero_offset", "0.0") or "0.0")

                name = f"{optical_path}_{wl}_{role}_{wp}"
                cfg.upsert_device(
                    key=sn,
                    id=optical_path,
                    path=optical_path,
                    name=name,
                    port=port,
                    serial=sn,
                    role=role,
                    waveplate=wp,
                    wavelength=wl,
                    zero_offset=zero_off,
                )

    except ImportError:
        print("  (qtools.motor package not available for auto-scanning)")

    cfg.save()
    print("\n" + "═" * 60)
    print("  Configuration saved to:", cfg.config_path)
    print("═" * 60 + "\n")
