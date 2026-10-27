import argparse
import os
import shutil
import sys
import time
from typing import Dict, Any

from qtools.powermeter.connection import get_device, auto_detect_connected_device, list_available_backends
from qtools.powermeter.measurement import read, measure_power, compute_statistics, export, format_power
from qtools.powermeter.backends.thorlabs import ThorlabsPowerMeter
from qtools.powermeter.backends.lbtek import LBTekPowerMeter
from qtools.powermeter.backends.s15 import S15PowerMeter


def auto_detect_connected_device() -> tuple:
    """Scan and find the first connected S15, Thorlabs, or LBTEK device."""
    # 1. Search S15 devices
    s15_ports = S15PowerMeter.list_devices()
    if s15_ports:
        return s15_ports[0], "s15"

    # 2. Search Thorlabs VISA devices
    thor_devices = ThorlabsPowerMeter.list_devices()
    if thor_devices:
        return thor_devices[0], "thorlabs"

    # 3. Search LBTEK devices (filtering by description/manufacturer keywords)
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            desc = (p.description or "").lower()
            mfg = (p.manufacturer or "").lower()
            if "lbtek" in desc or "lbtek" in mfg:
                return p.device, "lbtek"
    except Exception:
        pass

    return None, None

def resolve_device(address: str, backend: str) -> tuple:
    """Helper to resolve device address and backend. Triggers auto-detection if address is missing."""
    if not address:
        if backend == "mock":
            address = "MOCK0"
        else:
            detected_addr, detected_backend = auto_detect_connected_device()
            if detected_addr:
                address = detected_addr
                if not backend:
                    backend = detected_backend
                print(f"Auto-detected device at {address} ({backend})")
            else:
                raise ConnectionError(
                    "Error: No power meter device found.\n"
                    "Make sure your device is connected, or specify '-b mock' to run in simulation."
                )

    if not backend:
        backend = "s15"  # default for user-specified serial addresses

    return address, backend

def configure_device_range(device: Any, range_val: float) -> None:
    """Configure device range; 0 or None enables auto-ranging."""
    try:
        device.set_range(range_val if range_val is not None else 0)
    except NotImplementedError:
        pass

def resolve_output_and_format(args: argparse.Namespace) -> tuple:
    """Determine output format and target filename with appropriate extension."""
    fmt = getattr(args, "format", None)
    output_file = getattr(args, "output", None)

    if output_file:
        if not fmt:
            fmt = "npz"

        # Map formats to expected file extensions
        ext_map = {
            "json": ".json",
            "csv": ".csv",
            "npz": ".npz",
            "txt": ".txt"
        }
        target_ext = ext_map.get(fmt, ".npz")

        # Split name and extension, append target_ext if it doesn't match
        base_name, ext = os.path.splitext(output_file)
        if ext.lower() != target_ext:
            output_file = base_name + target_ext
    else:
        if not fmt:
            fmt = "table"

    return fmt, output_file

def handle_read(args: argparse.Namespace) -> None:
    """Perform a single power measurement, or statistical average if duration is given."""
    address, backend = resolve_device(args.address, args.backend)
        
    try:
        device = get_device(backend, address)
        with device:
            if args.wavelength is not None:
                device.set_wavelength(args.wavelength)

            # Configure range (defaults to auto-ranging if range is None)
            configure_device_range(device, args.range)

            duration = getattr(args, "duration", None)
            if duration is not None:
                # Calculate average and standard deviation over duration
                samples = getattr(args, "samples", 10)

                print(f"Reading average power over {duration}s with {samples} samples...")

                mean_val, std_val = measure_power(
                    device=device,
                    duration=duration,
                    samples=samples,
                    callback=None
                )
                
                print("-" * 50)
                print(f"Average Power: {format_power(mean_val)} ({mean_val:.8e} W)")
                print(f"Std Deviation: {format_power(std_val)} ({std_val:.8e} W)")
            else:
                # Single reading
                power = device.get_power()
                print(f"Power: {format_power(power)} ({power:.8e} W)")
                
    except Exception as e:
        print(f"Error executing read: {e}", file=sys.stderr)
        sys.exit(1)

def handle_measure(args: argparse.Namespace) -> None:
    """Perform statistical measurements over a duration."""
    address, backend = resolve_device(args.address, args.backend)
    fmt, output_file = resolve_output_and_format(args)
        
    try:
        device = get_device(backend, address)
        with device:
            if args.wavelength is not None:
                device.set_wavelength(args.wavelength)

            # Configure range (defaults to auto-ranging if range is None)
            configure_device_range(device, args.range)
            
            # Setup optional live dot progress callback
            callback = None
            if fmt == "table" and not output_file:
                print(f"Measuring for {args.duration}s with {args.samples} samples...")
                print("Sampling progress: [", end="", flush=True)
                
                def progress_cb(power_val: float, elapsed: float):
                    print(".", end="", flush=True)
                callback = progress_cb

            trace = read(
                device=device,
                duration=args.duration,
                samples=args.samples,
                callback=callback
            )

            if callback:
                print("] Done!\n")

            stats = compute_statistics(trace)
            export(
                trace=trace,
                stats=stats,
                fmt=fmt,
                output_file=output_file,
                info=device.get_info(),
                backend=backend,
                address=address,
            )
                
    except Exception as e:
        print(f"Error executing measurement: {e}", file=sys.stderr)
        sys.exit(1)

def _live_read_telemetry(device: Any) -> tuple:
    """Read voltage/range from values cached by the last get_power() call.

    Falls back to direct queries only when the backend does not expose the
    cache. Avoids extra serial round-trips that desync the bus under auto-range.
    """
    volt = getattr(device, "last_voltage", None)
    if volt is None:
        volt = getattr(device, "smoothed_voltage", None)
    r_idx = getattr(device, "last_range", None)
    if r_idx is None and hasattr(device, "get_range"):
        try:
            r_idx = device.get_range()
        except Exception:
            r_idx = None
    if volt is None and hasattr(device, "get_voltage"):
        try:
            volt = device.get_voltage()
        except Exception:
            volt = None
    return volt, r_idx


def _live_render_line(
    power: float,
    volt: Any,
    r_idx: Any,
    *,
    n_avg: int | None = None,
) -> None:
    """Render one live-mode status line to stdout (overwrites current line)."""
    formatted = format_power(power)

    try:
        columns = shutil.get_terminal_size((80, 20)).columns
    except Exception:
        columns = 80

    parts = []
    if volt is not None:
        parts.append(f"V: {float(volt):.4f} V")
    if r_idx is not None:
        parts.append(f"Range: {r_idx}")
    if n_avg is not None:
        parts.append(f"N: {n_avg}")
    extra_info = (" | " + " | ".join(parts)) if parts else ""

    prefix = "Power: "
    suffix = f"{formatted:<12}{extra_info}"

    # 4 columns: "[", "]", a space, and a buffer column
    available_space = columns - len(prefix) - len(suffix) - 4
    bar_str = ""
    if available_space >= 5:
        bar_width = available_space
        if volt is not None:
            ratio = max(0.0, min(1.0, float(volt) / 2.5))
        else:
            ratio = 0.0
        num_hashes = int(round(ratio * bar_width))
        bar_str = "[" + "#" * num_hashes + "-" * (bar_width - num_hashes) + "] "

    print(f"\r\033[K{prefix}{bar_str}{suffix}", end="", flush=True)


def handle_live(args: argparse.Namespace) -> None:
    """Start real-time tracking display in terminal or launch GUI."""

    address, backend = resolve_device(args.address, args.backend)

    try:
        device = get_device(backend, address)
        with device:
            if args.wavelength is not None:
                device.set_wavelength(args.wavelength)

            # Configure range (defaults to auto-ranging if range is None)
            range_val = getattr(args, "range", None)
            configure_device_range(device, range_val)

            sampling_rate = getattr(args, "sampling_rate", 2.0)
            if sampling_rate <= 0:
                raise ValueError("--sampling-rate must be greater than 0.")
            sleep_time = 1.0 / sampling_rate
            average = bool(getattr(args, "average", False))

            print(f"Starting real-time power display from {backend} at {address}...")
            print(
                f"Wavelength: {args.wavelength} nm | "
                f"Auto-range: {'ON' if range_val is None else 'OFF'}"
            )
            if average:
                print(
                    f"Sample Rate: {sampling_rate:g} Hz | "
                    f"Display: 1 Hz average (mean of samples in each 1 s window)"
                )
            else:
                print(f"Update Rate: {sampling_rate:g} Hz")
            print("Press Ctrl+C to stop.\n")

            try:
                if average:
                    # Accumulate samples for 1 s, then display the mean once.
                    # sampling-rate controls how densely we sample inside each window.
                    while True:
                        window_start = time.monotonic()
                        samples: list[float] = []
                        volt_sum = 0.0
                        volt_count = 0
                        last_r_idx = None

                        while True:
                            sample_t0 = time.monotonic()
                            samples.append(device.get_power())

                            volt, r_idx = _live_read_telemetry(device)
                            if volt is not None:
                                volt_sum += float(volt)
                                volt_count += 1
                            if r_idx is not None:
                                last_r_idx = r_idx

                            elapsed = time.monotonic() - window_start
                            if elapsed >= 1.0:
                                break

                            remaining_in_window = 1.0 - elapsed
                            sleep_for = min(sleep_time, remaining_in_window)
                            # Compensate for the time spent reading the sample.
                            spent = time.monotonic() - sample_t0
                            sleep_for -= spent
                            if sleep_for > 0:
                                time.sleep(sleep_for)

                        mean_power = sum(samples) / len(samples)
                        mean_volt = (volt_sum / volt_count) if volt_count else None
                        _live_render_line(
                            mean_power,
                            mean_volt,
                            last_r_idx,
                            n_avg=len(samples),
                        )
                else:
                    while True:
                        power = device.get_power()
                        volt, r_idx = _live_read_telemetry(device)
                        _live_render_line(power, volt, r_idx)
                        time.sleep(sleep_time)
            except KeyboardInterrupt:
                print("\nStopped real-time tracking.")

    except Exception as e:
        print(f"Device error: {e}", file=sys.stderr)
        sys.exit(1)

def main() -> None:
    # 1. Create a parent parser to hold common arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("-a", "--address", help="Device address (e.g. COM port). Auto-detects if omitted.")
    parent_parser.add_argument("-b", "--backend", choices=list_available_backends(), help="Specify backend.")
    parent_parser.add_argument("-w", "--wavelength", type=float, default=780.0, help="Wavelength in nm (default: 780.0)")
    parent_parser.add_argument("-r", "--range", type=float, help="Power range (defaults to auto-ranging).")

    # 2. Main parser inherits from parent
    parser = argparse.ArgumentParser(
        parents=[parent_parser],
        description="Unified Power Meter Command Line Interface. Supports S15, Thorlabs, LBTEK, and Mock backends."
    )
    # Extra top-level parameters for default live mode fallback
    parser.add_argument("--sampling-rate", type=float, default=2.0, help="Sample / update rate in Hz for live mode (default: 2.0).")
    parser.add_argument(
        "--average",
        action="store_true",
        help="In live mode, sample at --sampling-rate and refresh the display once per second with the mean of that window.",
    )

    # 3. Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Subcommands (Optional)")

    # Subcommand: read
    read_parser = subparsers.add_parser("read", parents=[parent_parser], help="Get a single instantaneous power reading")
    read_parser.add_argument("-d", "--duration", type=float, help="Duration in seconds. If specified, calculates average and standard deviation.")
    read_parser.add_argument("-n", "--samples", type=int, default=10, help="Number of sample points (default: 10).")

    # Subcommand: measure
    measure_parser = subparsers.add_parser("measure", parents=[parent_parser], help="Sample power over time and calculate error statistics")
    measure_parser.add_argument("-f", "--format", choices=["csv", "npz", "txt", "json"], help="Output format.")
    measure_parser.add_argument("-o", "--output", help="Optional file path to save formatted output.")
    measure_parser.add_argument("-d", "--duration", type=float, default=1.0, help="Duration in seconds.")
    measure_parser.add_argument("-n", "--samples", type=int, default=10, help="Number of sample points (default: 10).")

    # Subcommand: live
    live_parser = subparsers.add_parser("live", parents=[parent_parser], help="Display real-time power tracking in terminal")
    live_parser.add_argument("--sampling-rate", type=float, default=2.0, help="Sample / update rate in Hz (default: 2.0).")
    live_parser.add_argument(
        "--average",
        action="store_true",
        help="Sample at --sampling-rate and refresh the display once per second with the mean of that window.",
    )

    # Subcommand: gui
    subparsers.add_parser("gui", help="Launch the graphical user interface")

    args = parser.parse_args()
    
    # Route execution
    if args.command == "gui":
        try:
            from qtools.powermeter.gui import run_gui
            run_gui()
        except ImportError as e:
            print(f"Error launching GUI: {e}\nEnsure tkinter and matplotlib are installed.", file=sys.stderr)
            sys.exit(1)
    elif args.command == "read":
        handle_read(args)
    elif args.command == "measure":
        handle_measure(args)
    elif args.command == "live":
        handle_live(args)
    else:
        # Fallback to live mode using top-level options by default
        handle_live(args)

if __name__ == "__main__":
    main()
