"""Unified Time-to-Digital Converter (TDC) Command Line Interface. Supports S15, CIQTEK TDC1610, IDQ, and Simulator backends."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

import kochen.logging
import kochen.scriptutil
import numpy as np

from qtools.tdc.connection import get_backend, display_devices, discover_all
from qtools.tdc.data import save_ts_binary, save_hdf5
from qtools.tdc.backends.base import _find_coincidence_peak, _peak_width_bins
from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.measurement import TDC


def dummy_style(text, *args, **kwargs):
    return str(text)


try:
    from kochen.recipe import ansi as _ansi
except Exception:  # pragma: no cover - color helpers are optional
    _ansi = None


def get_style(enable):
    """Return the ANSI colorizing ``style()`` when enabled on a terminal.

    Falls back to :func:`dummy_style` when colors are disabled, stdout/stderr
    are not attached to a terminal (pipes, files, test captures), or the color
    helpers are unavailable.  Like :func:`dummy_style`, the returned function
    coerces *text* to ``str`` so callers may pass numbers.
    """
    if not enable or _ansi is None:
        return dummy_style
    try:
        if not (sys.stdout.isatty() or sys.stderr.isatty()):
            return dummy_style
    except Exception:
        return dummy_style

    _base = _ansi.style

    def style(text, *args, **kwargs):
        return _base(str(text), *args, **kwargs)

    return style


style = dummy_style


def len_ansi(text):
    """Visible length of *text*, ignoring ANSI color escapes."""
    return _ansi.len_ansi(text) if _ansi is not None else len(str(text))


def strip_ansi(text):
    """Strip ANSI color escapes from *text* (used for file exports)."""
    return _ansi.strip_ansi(text) if _ansi is not None else str(text)


_BANNER_ART = (
    "   ████████╗  ██████╗  ██████╗",
    "   ╚══██╔══╝  ██╔══██╗  ██╔════╝",
    "      ██║     ██║  ██║  ██║",
    "      ██║     ██║  ██║  ██║",
    "      ██║     ╚██████╔╝  ╚██████╗",
    "      ╚═╝      ╚═════╝   ╚═════╝",
    "   Time-to-Digital Converter (TDC) CLI",
)


def _build_banner() -> str:
    """Render the framed, colored TDC banner shown above the help text."""
    style_fn = get_style(True)
    width = max(len(line) for line in _BANNER_ART)
    bar = "═" * (width + 2)
    out = [style_fn("╔" + bar + "╗", fg="cyan")]
    for i, line in enumerate(_BANNER_ART):
        body = line.ljust(width)
        if i < len(_BANNER_ART) - 1:
            body = style_fn(body, fg="cyan", style="bright")
        else:
            body = style_fn(body, fg="yellow")
        out.append(style_fn("║ ", fg="cyan") + body + style_fn(" ║", fg="cyan"))
    out.append(style_fn("╚" + bar + "╝", fg="cyan"))
    return "\n".join(out)


logger = logging.getLogger(__name__)

INT_MIN = np.iinfo(np.int64).min  # indicates invalid value

COMMANDS = {}


def _collect_as_command(alias=None):
    def collector(f):
        nonlocal alias
        if alias is None:
            alias = f.__name__
        COMMANDS[alias] = f
        return f
    return collector


def print_fixedwidth(*values, width=8, out=None, pbar=None, end="\n"):
    row = []
    for value in values:
        if value == INT_MIN:
            row.append(" " * width)
        else:
            value = str(value)
            slen = max(0, width - len_ansi(value))
            row.append(" " * slen + value)
    line = "  ".join(row)

    if pbar:
        pbar.set_description(line)
    else:
        print(line, end=end)
    if out:
        line = "  ".join(
            [
                f"{strip_ansi(str(value)) if value != INT_MIN else ' ': >{width}s}"
                for value in values
            ]
        )
        with open(out, "a") as f:
            f.write(line + "\n")


def _make_auto_path(prefix: str, ext: str) -> str:
    """Create a default file path inside data/ with timestamp."""
    os.makedirs("data", exist_ok=True)
    now_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join("data", f"{now_str}_{prefix}{ext}")


def _insert_sample_index(path: str, idx: int) -> str:
    """Insert a zero-padded sample index before the file extension.

    Example: ``"data/file.ts"`` with ``idx=3`` → ``"data/file_0003.ts"``.
    """
    base, ext = os.path.splitext(path)
    return f"{base}_{idx:04d}{ext}"


def _resolve_export_path(
    arg_value,
    prefix: str,
    valid_exts: tuple,
    default_ext: str,
):
    """Resolve a --export/--raw path from argparse optional argument."""
    if arg_value is None:
        return None
    os.makedirs("data", exist_ok=True)
    if arg_value == "DEFAULT":
        return _make_auto_path(prefix, default_ext)
    path = arg_value
    _, ext = os.path.splitext(path)
    if ext.lower() not in valid_exts:
        path += default_ext
    return path


# ─── REPL commands ───

@_collect_as_command("singles")
def monitor_singles(args):
    """Prints out singles statistics continuously."""
    i = 0
    max_iter = args.samples  # None = infinite
    iteration = 0

    # Resolve channel filter and labels
    channels = args.channel
    if channels:
        ch_labels = [f"CH{ch}" for ch in channels]
    else:
        ch_labels = [f"CH{ch+1}" for ch in range(4)]

    # Resolve export and raw paths
    export_path = None
    if args.export is not None:
        if args.samples is None:
            print("Warning: --export in singles mode requires --samples (-s), ignoring export.",
                  file=sys.stderr)
        else:
            export_path = _resolve_export_path(args.export, "singles_export", (".csv",), ".csv")
            import csv
            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["TIME", "INTTIME"] + ch_labels + ["TOTAL"])

    # Resolve raw path (actual saving happens per-sample in the loop)
    raw_path = None
    if args.raw is not None:
        raw_path = _resolve_export_path(args.raw, "singles_raw", (".ts", ".h5", ".hdf5"), ".ts")

    while True:
        inttime, rates = args.api.measure_rates(duration=args.time)[0]

        # Save raw timestamps for this sample
        if raw_path is not None:
            sample_path = _insert_sample_index(raw_path, iteration)
            try:
                ts_res = args.api.backend.get_timestamps(args.time)
                _, ext = os.path.splitext(sample_path)
                if ext.lower() in (".h5", ".hdf5"):
                    save_hdf5(sample_path, ts_res.timestamps, ts_res.channels, ts_res.resolution_ps)
                else:
                    save_ts_binary(sample_path, ts_res.timestamps, ts_res.channels, ts_res.resolution_ps)
                print(f"Raw timestamps saved to: {sample_path}")
            except Exception as e:
                print(f"Error saving raw timestamps: {e}", file=sys.stderr)

        if channels:
            selected_idx = [ch - 1 for ch in channels if 1 <= ch <= args.api.backend.channel_count]
            rates_display = [rates[idx] for idx in selected_idx]
        else:
            rates_display = list(rates)

        if i == 0:
            i = 10
            headers = ["TIME", "INTTIME"] + ch_labels + ["TOTAL"]
            print_fixedwidth(*headers)
        i -= 1

        print_fixedwidth(
            style(dt.datetime.now().strftime("%H%M%S"), style="dim"),
            f"{inttime:.2f}",
            *list(map(int, rates_display)),
            style(int(sum(rates_display)), style="bright"),
        )

        # Write CSV row
        if export_path:
            with open(export_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    dt.datetime.now().strftime("%H%M%S"),
                    f"{inttime:.2f}",
                ] + [int(r) for r in rates_display] + [int(sum(rates_display))])

        iteration += 1
        if max_iter is not None and iteration >= max_iter:
            break


@_collect_as_command("pairs")
def monitor_pairs(args):
    """Measure and display one two-channel g² histogram."""
    import os

    if (args.ws is None) != (args.we is None):
        raise ValueError("--window-start and --window-stop must be supplied together")

    if args.hardware:
        return _monitor_pairs_hardware(args)

    # Resolve export and raw paths
    export_path = _resolve_export_path(args.export, "pairs_export", (".csv", ".npz"), ".csv")
    raw_path = _resolve_export_path(args.raw, "pairs_raw", (".ts", ".h5", ".hdf5"), ".ts")

    result = args.api.measure_pairs(
        duration=args.time,
        ch_start=args.ch_start,
        ch_stop=args.ch_stop,
        bins=args.bins,
        window_start=args.ws,
        window_stop=args.we,
        delay=args.delay,
        bin_offset=args.bin_offset,
    )
    hist = np.asarray(result["histogram"])
    bin_edges = np.asarray(result.get("bin_edges", np.arange(len(hist) + 1)))

    print(f"Integration time: {result['integration_time']:.3f} s")
    print(f"Histogram bins: {len(hist)}")
    if hist.size:
        peak = int(np.argmax(hist))
        print(f"Peak bin: {peak}, count: {int(hist[peak])}")

    if export_path:
        try:
            _, ext = os.path.splitext(export_path)
            if ext.lower() == ".npz":
                np.savez_compressed(export_path, histogram=hist, bin_edges=bin_edges)
            else:
                import csv
                with open(export_path, "w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["bin", "count"])
                    writer.writerows((int(index), int(count)) for index, count in enumerate(hist))
            print(f"Histogram exported to: {export_path}")
        except Exception as exc:
            print(f"Error exporting histogram: {exc}", file=sys.stderr)

    if raw_path:
        try:
            timestamps = args.api.backend.get_timestamps(args.time)
            _, ext = os.path.splitext(raw_path)
            if ext.lower() in (".h5", ".hdf5"):
                save_hdf5(raw_path, timestamps.timestamps, timestamps.channels, timestamps.resolution_ps)
            else:
                save_ts_binary(raw_path, timestamps.timestamps, timestamps.channels, timestamps.resolution_ps)
            print(f"Raw timestamps saved to: {raw_path}")
        except Exception as exc:
            print(f"Error saving raw timestamps: {exc}", file=sys.stderr)

    if args.plot:
        try:
            import matplotlib.pyplot as plt

            plt.step(bin_edges[:-1], hist, where="post")
            plt.xlabel("bin")
            plt.ylabel("counts")
            plt.title(f"g² Ch{args.ch_start}-Ch{args.ch_stop}")
            plt.tight_layout()
            plt.show()
        except ImportError:
            print("Matplotlib is not installed. Run 'pip install matplotlib' to enable plotting.")

    return result


def _monitor_pairs_hardware(args):
    """Hardware counter path for the pairs command (fixed coincidence gate)."""
    if args.delay != 0:
        raise ValueError("--hardware does not support --delay/--stop_delay")
    if args.ws is not None or args.we is not None:
        raise ValueError("--hardware uses the fixed coincidence gate; --ws/--we are not supported")
    result = args.api.measure_coincidence(
        duration=args.time,
        ch_start=args.ch_start,
        ch_stop=args.ch_stop,
        method="hardware",
    )
    print(f"Integration time: {result.integration_time:.3f} s")
    print(f"Coincidence pairs (hardware): {result.count}")
    print(f"Channel {args.ch_start} rate: {result.channel1_rate:.1f} cps")
    print(f"Channel {args.ch_stop} rate: {result.channel2_rate:.1f} cps")
    return result


def _singles_ratio(singles1, singles2):
    """Return the SINGLES1/SINGLES2 ratio, using NaN for a zero divisor."""
    return float(singles1) / float(singles2) if singles2 else float("nan")


def _coincidence_rates(result):
    """Return the display rates and efficiencies from a pairs result."""
    integration_time = float(result["integration_time"])
    return (
        float(result["net_pair_rate"]),
        float(result["acc_pair_rate"]),
        float(result["start_rate"]),
        float(result["stop_rate"]),
        float(result["eff_start"]),
        float(result["eff_stop"]),
        float(result["eff_avg"]),
        integration_time,
    )


def _resolve_coincidence_window(args):
    """Return the coincidence bin window, resolving --auto if requested."""
    if args.auto:
        if args.ws is not None or args.we is not None:
            raise ValueError("--auto cannot be combined with --window-start/--window-stop")
        return _auto_detect_window(args)
    if args.ws is None or args.we is None:
        raise ValueError("coincidences requires --window-start and --window-stop (or use --auto)")
    return args.ws, args.we


def _auto_detect_window(args):
    """Probe a g2 histogram, detect the single highest coincidence peak, and
    size the coincidence window to the measured peak width. Prints the chosen
    window (in bin units) and returns it for ``measure_pairs``."""
    delay_ns = args.delay * args.api.backend.resolution_ps / 1e3
    g2res = args.api.measure_g2(
        duration=args.time,
        ch_start=args.ch_start,
        ch_stop=args.ch_stop,
        ch_stop_delay=delay_ns,
        bins=500,
        unit="ns",
    )
    hist = np.asarray(g2res.histogram, dtype=float)
    if hist.size == 0 or float(np.max(hist, initial=0.0)) <= 0:
        raise ValueError("Cannot detect a coincidence peak in an empty histogram")
    peak = _find_coincidence_peak(hist)
    if peak is None:
        raise ValueError("Cannot detect a coincidence peak in the histogram")
    fwhm = _peak_width_bins(hist, peak)
    half = max((fwhm + 1) // 2, 1)  # FWHM/2 rounded up, at least 1 bin per side
    ws = max(peak - half, 0)
    we = min(peak + half, hist.size - 1)
    res_ns = g2res.resolution_ps / 1e3
    print(
        f"Auto-detected coincidence window: window_start={ws}, window_stop={we} "
        f"(peak bin {peak}, FWHM {fwhm} bins, {res_ns:g} ns/bin)"
    )
    return ws, we


def _monitor_coincidence_hardware(args):
    """Hardware counter path for the coincidences command (real-time stream)."""
    if getattr(args, "plot", False) and args.samples is None:
        raise ValueError("--plot requires --samples")
    if args.auto:
        raise ValueError("--auto requires software analysis; --hardware provides no histogram")
    if args.ws is not None or args.we is not None:
        raise ValueError("--hardware uses the fixed coincidence gate; --ws/--we are not supported")
    if args.delay != 0:
        raise ValueError("--hardware does not support --delay/--stop_delay")
    if args.samples is not None and args.samples <= 0:
        raise ValueError("--samples must be positive")

    export_path = None
    if args.export is not None:
        if args.samples is None:
            print(
                "Warning: --export in coincidences mode requires --samples (-s), ignoring export.",
                file=sys.stderr,
            )
        else:
            export_path = _resolve_export_path(args.export, "coincidences_export", (".csv",), ".csv")

    writer = None
    stream = None
    if export_path:
        import csv

        stream = open(export_path, "w", newline="", encoding="utf-8", buffering=1)
        writer = csv.writer(stream)
        writer.writerow(["TIME", "INTTIME", "PAIRS", "SINGLES1", "SINGLES2", "S1/S2"])
        stream.flush()

    results = []
    iteration = 0
    try:
        while args.samples is None or iteration < args.samples:
            result = args.api.measure_coincidence(
                duration=args.time,
                ch_start=args.ch_start,
                ch_stop=args.ch_stop,
                method="hardware",
            )
            timestamp = dt.datetime.now().strftime("%H%M%S")
            if iteration % 10 == 0:
                print_fixedwidth("TIME", "ITIME", "PAIRS", "SINGLES1", "SINGLES2", "S1/S2")
            ratio = _singles_ratio(result.channel1_rate, result.channel2_rate)
            print_fixedwidth(
                timestamp,
                f"{result.integration_time:.2f}",
                style(f"{float(result.count):.1f}", fg="green"),
                f"{result.channel1_rate:.1f}",
                f"{result.channel2_rate:.1f}",
                f"{ratio:.3f}",
            )
            if writer:
                writer.writerow([
                    timestamp, f"{result.integration_time:.2f}", f"{result.count:.6f}",
                    f"{result.channel1_rate:.6f}", f"{result.channel2_rate:.6f}",
                    f"{ratio:.3f}",
                ])
                stream.flush()
            results.append(result)
            iteration += 1
    finally:
        if stream:
            stream.close()
    if getattr(args, "plot", False):
        _plot_coincidence_samples(args, results)
    return results


def _plot_coincidence_samples(args, results):
    """Plot pairs and singles for each recorded coincidence sample."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Matplotlib is not installed. Run 'pip install matplotlib' to enable plotting.")
        return

    sample_numbers = np.arange(1, len(results) + 1)
    if getattr(args, "hardware", False):
        pairs = [float(result.count) for result in results]
        pairs_ylabel = "pair count"
    else:
        pairs = [float(result["net_pair_rate"]) for result in results]
        pairs_ylabel = "net pair rate (cps)"
    singles_start = [
        float(result.channel1_rate) if getattr(args, "hardware", False)
        else float(result["start_rate"])
        for result in results
    ]
    singles_stop = [
        float(result.channel2_rate) if getattr(args, "hardware", False)
        else float(result["stop_rate"])
        for result in results
    ]

    fig, (ax_pairs, ax_singles) = plt.subplots(
        2, 1, sharex=True, figsize=(7.2, 6.0),
    )

    ax_pairs.plot(sample_numbers, pairs, marker="o", linewidth=1.8)
    ax_pairs.set_ylabel(pairs_ylabel)
    ax_pairs.set_title(f"Pairs: Ch{args.ch_start}-Ch{args.ch_stop}")

    ch_start = args.ch_start
    ch_stop = args.ch_stop
    ax_singles.plot(
        sample_numbers, singles_start, marker="o", linewidth=1.8,
        label=f"Ch{ch_start}",
    )
    ax_singles.plot(
        sample_numbers, singles_stop, marker="o", linewidth=1.8,
        label=f"Ch{ch_stop}",
    )
    ax_singles.set_xlabel("sample")
    ax_singles.set_ylabel("singles rate (cps)")
    ax_singles.set_title(f"Singles: Ch{ch_start}, Ch{ch_stop}")
    ax_singles.legend()

    fig.tight_layout()
    plt.show()


def _monitor_coincidence_stats(args):
    """Print coincidence statistics for an explicit or auto-detected bin window."""
    if args.hardware:
        return _monitor_coincidence_hardware(args)

    if getattr(args, "plot", False) and args.samples is None:
        raise ValueError("--plot requires --samples")

    ws, we = _resolve_coincidence_window(args)

    if args.samples is not None and args.samples <= 0:
        raise ValueError("--samples must be positive")

    export_path = None
    if args.export is not None:
        if args.samples is None:
            print(
                "Warning: --export in coincidences mode requires --samples (-s), ignoring export.",
                file=sys.stderr,
            )
        else:
            export_path = _resolve_export_path(args.export, "coincidences_export", (".csv",), ".csv")

    writer = None
    stream = None
    if export_path:
        import csv

        stream = open(export_path, "w", newline="", encoding="utf-8", buffering=1)
        writer = csv.writer(stream)
        writer.writerow([
            "TIME", "INTTIME", "PAIRS", "ACC", "SINGLES1", "SINGLES2",
            "S1/S2", "EFF1", "EFF2", "EFF_AVG",
        ])
        stream.flush()

    results = []
    iteration = 0
    try:
        while args.samples is None or iteration < args.samples:
            result = args.api.measure_pairs(
                duration=args.time,
                ch_start=args.ch_start,
                ch_stop=args.ch_stop,
                window_start=ws,
                window_stop=we,
                delay=args.delay,
            )
            pairs, acc, s1, s2, e1, e2, eavg, inttime = _coincidence_rates(result)
            ratio = _singles_ratio(s1, s2)
            timestamp = dt.datetime.now().strftime("%H%M%S")
            if iteration % 10 == 0:
                print_fixedwidth(
                    "TIME", "ITIME", "PAIRS", "ACC", "SINGLES1", "SINGLES2",
                    "S1/S2", "EFF1", "EFF2", "EFF_AVG",
                )
            print_fixedwidth(
                timestamp,
                f"{inttime:.2f}",
                style(f"{pairs:.1f}", fg="green"),
                f"{acc:.1f}",
                f"{s1:.1f}",
                f"{s2:.1f}",
                f"{ratio:.3f}",
                style(f"{e1 * 100.0:.2f}", fg="blue"),
                style(f"{e2 * 100.0:.2f}", fg="blue"),
                f"{eavg * 100.0:.2f}",
            )
            if writer:
                writer.writerow([
                    timestamp, f"{inttime:.2f}", f"{pairs:.6f}", f"{acc:.6f}",
                    f"{s1:.6f}", f"{s2:.6f}", f"{ratio:.3f}",
                    f"{e1:.6f}", f"{e2:.6f}", f"{eavg:.6f}",
                ])
                stream.flush()
            results.append(result)
            iteration += 1
    finally:
        if stream:
            stream.close()
    if getattr(args, "plot", False):
        _plot_coincidence_samples(args, results)
    return results


@_collect_as_command("coincidences")
def monitor_coincidences(args):
    """Measure coincidence rates inside an explicit window."""
    return _monitor_coincidence_stats(args)

@_collect_as_command("service")
def run_service(args):
    """Run an IPC server service to allow querying measurement results."""
    from kochen.ipcutil import Server

    # Clamp integration time to --max if specified
    effective_time = args.time
    if args.max is not None:
        effective_time = min(args.time, args.max)

    def singles():
        inttime, counts = args.api.measure_singles(duration=effective_time)[0]
        return (float(inttime), *tuple(map(float, counts)))

    def pairs():
        ws = args.ws
        we = args.we
        kwargs = {
            "duration": effective_time,
            "ch_start": args.ch_start,
            "ch_stop": args.ch_stop,
            "delay": args.delay,
        }
        if (ws is None) != (we is None):
            raise ValueError("--window-start and --window-stop must be supplied together")
        if ws is not None:
            kwargs.update(window_start=ws, window_stop=we)
        res = args.api.measure_pairs(**kwargs)
        # Report rates, integration time, and efficiencies, mirroring the
        # legacy tuple ordering: (inttime, pairs, acc, s1, s2, e1, e2, eavg).
        return (
            float(res["integration_time"]),
            float(res["net_pair_rate"]),
            float(res["acc_pair_rate"]),
            float(res["start_rate"]),
            float(res["stop_rate"]),
            float(res["eff_start"]),
            float(res["eff_stop"]),
            float(res["eff_avg"]),
        )

    s = Server(singles, pairs, address=args.ip, port=args.port, secret=args.secret)
    s.run()


@_collect_as_command("list")
def run_discovery(args):
    """Run cross-platform hardware auto-discovery."""
    devices = discover_all(method=args.method, timeout=args.timeout)
    display_devices(devices)


# ─── Argument Parser ───

def make_parser(help_verbosity: int = 1):
    adv = kochen.scriptutil.get_help_descriptor(help_verbosity >= 2)
    parser, default_config = kochen.scriptutil.generate_default_parser_config(
        __doc__, display_config=help_verbosity >= 2
    )
    parser.formatter_class = argparse.RawTextHelpFormatter
    parser.description = _build_banner() + "\n" + parser.description

    pgroup = parser.add_argument_group("global options")
    pgroup.add_argument(
        "-h", "--help", action="count", default=0,
        help="Show this help message, with incremental verbosity, e.g. -hh",
    )
    pgroup.add_argument(
        "-v", "--verbosity", action="count", default=0,
        help=adv("Specify debug verbosity, e.g. -vv"),
    )
    pgroup.add_argument(
        "-b", "--backend", metavar="", default=DEFAULT_TDC1_BACKEND,
        choices=[DEFAULT_TDC1_BACKEND, "s15_tdc2", "tdc1610", "idq"],
        help=f"TDC hardware backend to use (default: '{DEFAULT_TDC1_BACKEND}')",
    )
    pgroup.add_argument(
        "-U", "--device", metavar="", default=None,
        help="Path to device identifier or serial port (default: auto)",
    )
    pgroup.add_argument(
        "-t", "--time", metavar="", type=float, default=1.0,
        help="Integration time in seconds (default: 1.0)",
    )
    pgroup.add_argument(
        "repl", nargs="?", metavar="command", choices=list(COMMANDS.keys()),
        default=argparse.SUPPRESS, help=argparse.SUPPRESS,
    )

    pgroup = parser.add_argument_group("device connection options (advanced)")
    pgroup.add_argument(
        "-S", "--readevents", metavar="", default="/usr/bin/readevents7",
        help=adv("Path to readevents binary"),
    )
    pgroup.add_argument(
        "-O", "--tmpfile", metavar="", default="/tmp/quick_timestamp",
        help=adv("Path to temporary timestamp file"),
    )
    pgroup.add_argument(
        "--threshvolt", metavar="", type=float, default=0.6,
        help="Pulse trigger level in Volts (default: 0.6)",
    )
    pgroup.add_argument(
        "-f", "--fast", action="store_true",
        help="Enable fast event readout mode.",
    )

    pgroup = parser.add_argument_group("data export & raw options")
    pgroup.add_argument(
        "-e", "--export", nargs="?", const="DEFAULT", default=None, metavar="FILE",
        help="Export measurement data (.csv/.npz, default: data/<prefix>_<date>.csv)",
    )
    pgroup.add_argument(
        "-r", "--raw", nargs="?", const="DEFAULT", default=None, metavar="FILE",
        help="Export raw timestamps (.ts/.h5, default: data/<prefix>_<date>.ts)",
    )

    pgroup = parser.add_argument_group("[singles] options")
    pgroup.add_argument(
        "-s", "--samples", metavar="NUM", type=int, default=None,
        help="Sample NUM times then exit (default: continuous)",
    )
    pgroup.add_argument(
        "-c", "--channel", nargs="+", type=int, default=None,
        help="Select channels to display (1-based, default: all)",
    )
    pairs_group = parser.add_argument_group("[pairs] options")
    pairs_group.add_argument(
        "--bins", metavar="", type=int, default=500,
        help="Number of coincidence time bins (default: 500)",
    )
    pairs_group.add_argument(
        "--plot", action="store_true",
        help="Plot measurement data using matplotlib (coincidences requires --samples)",
    )
    pairs_group.add_argument(
        "--bin_offset", metavar="", type=int, default=0,
        help="Start of correlation window in bins (bin_offset passed to get_g2; default: 0)",
    )

    pgroup = parser.add_argument_group("[coincidences] options")
    pgroup.add_argument(
        "--ch_start", "--start", metavar="", type=int, default=1,
        help="Reference start channel (1-based, default: 1)",
    )
    pgroup.add_argument(
        "--ch_stop", "--stop", metavar="", type=int, default=4,
        help="Target stop channel (1-based, default: 4)",
    )
    pgroup.add_argument(
        "--ws", "--wstart", "--window-start", metavar="", type=int, default=None,
        help="Coincidence time window start boundary, in bins (default: None)",
    )
    pgroup.add_argument(
        "--we", "--wstop", "--window-stop", metavar="", type=int, default=None,
        help="Coincidence time window stop boundary, in bins (default: None)",
    )
    pgroup.add_argument(
        "--delay", "--stop_delay", metavar="", type=int, default=0,
        help="Time delay in bins to apply to ch_stop (default: 0)",
    )
    pgroup.add_argument(
        "--auto", action="store_true",
        help="Auto-detect the g2 coincidence peak and choose --ws/--we (coincidences)",
    )
    pgroup.add_argument(
        "--hardware", action="store_true",
        help="Use the hardware coincidence counter (fixed gate) instead of software analysis",
    )

    pgroup = parser.add_argument_group("[service] options")
    pgroup.add_argument(
        "--max", metavar="", type=float, default=None,
        help="Max integration time per request, in seconds",
    )
    pgroup.add_argument(
        "--ip", metavar="", default="0.0.0.0",
        help=adv("IP address for service mode"),
    )
    pgroup.add_argument(
        "--port", metavar="", type=int, default=4440,
        help=adv("Port number for service mode"),
    )
    pgroup.add_argument(
        "--secret", metavar="",
        help=adv("Symmetric secret for authentication"),
    )

    pgroup = parser.add_argument_group("[list] options")
    pgroup.add_argument(
        "--method", choices=["usb", "ethernet", "all"], default="all",
        help="Scanning method: 'usb', 'ethernet', or 'all' (default: 'all')",
    )
    pgroup.add_argument(
        "--timeout", type=float, default=1.0,
        help="Timeout in seconds for Ethernet network discovery scan (default: 1.0)",
    )

    # Show the options shared with coincidences under [pairs] as well. argparse
    # registers each option string once; appending the same actions to a second
    # help group duplicates them in the help output only (parsing is unchanged).
    pairs_group = next(g for g in parser._action_groups if g.title == "[pairs] options")
    shared_group = next(
        g for g in parser._action_groups if g.title == "[coincidences] options"
    )
    pairs_group._group_actions[:0] = [
        action for action in shared_group._group_actions
        if action.dest in ("ch_start", "ch_stop", "delay", "hardware", "plot")
    ]
    shared_group._group_actions.append(
        next(action for action in pairs_group._group_actions if action.dest == "plot")
    )

    return parser


def _validate_command_args(parser, args, argv):
    """Reject options that belong to a different REPL command."""
    if getattr(args, "repl", None) == "coincidences" and any(
        token == "--bins" or token.startswith("--bins=") for token in argv
    ):
        parser.error("--bins is only supported by the pairs command")
    if getattr(args, "repl", None) == "coincidences" and any(
        token == "--bin_offset" or token.startswith("--bin_offset=") for token in argv
    ):
        parser.error("--bin_offset is only supported by the pairs command")
    if getattr(args, "repl", None) == "pairs" and any(
        token == "--auto" or token.startswith("--auto=") for token in argv
    ):
        parser.error("--auto is only supported by the coincidences command")


def main():
    global style

    # Ensure UTF-8 output on Windows (GBK terminals can't render the box-drawing banner)
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = make_parser()
    args = kochen.scriptutil.parse_args_or_help(parser, parser_func=make_parser)
    _validate_command_args(parser, args, sys.argv[1:])
    kochen.logging.set_default_handlers(logger, file=None)
    kochen.logging.set_logging_level(logger, args.verbosity)

    if getattr(args, "repl", None) is None:
        parser.print_usage()
        print(f"Specify which command to run: {list(COMMANDS.keys())}")
        sys.exit(1)

    style = get_style(True)

    # Initialize Hardware Backend
    backend_name = args.backend
    if getattr(args, "repl", None) == "list":
        return COMMANDS[getattr(args, "repl", None)](args)

    try:
        backend_cls = get_backend(backend_name)
        backend = backend_cls()

        conn_kwargs = {
            "readevents": args.readevents,
            "tmpfile": args.tmpfile,
            "threshold": args.threshvolt,
            "fast": args.fast,
        }
        if args.device is None:
            try:
                discovered = backend_cls.discover_devices()
                if discovered:
                    args.device = discovered[0].device_path
                    print(style(f"Auto-discovered and selected device: {args.device}", fg="green"))
                else:
                    print(style(f"No devices auto-discovered for backend '{backend_name}'. Using default/None.", fg="yellow"))
            except Exception as e:
                logger.warning("Error during device auto-discovery: %s", e)

        backend.connect(device_path=args.device, **conn_kwargs)
        args.api = TDC(backend)

        try:
            return COMMANDS[getattr(args, "repl", None)](args)
        finally:
            backend.disconnect()

    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception("Error executing program:")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
