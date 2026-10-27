import json
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from qtools.powermeter.backends.powermeter import PowerMeter


def read(
    device: PowerMeter,
    duration: float = 1.0,
    samples: int = 10,
    callback: Optional[Callable[[float, float], None]] = None,
) -> List[Tuple[float, float]]:
    """Sample power over *duration* and return raw (elapsed_time, power) pairs.

    This is the low-level sampling function — use it when you need the full
    time series for export (CSV, NPZ) or custom analysis.

    Args:
        device: Connected power meter instance.
        duration: Measurement duration in seconds.
        samples: Number of sample points to acquire.
        callback: Optional ``callback(power_val, elapsed_time)`` fired after
            each successful reading.

    Returns:
        List of ``(elapsed_seconds, power_watts)`` tuples.
    """
    if duration <= 0:
        raise ValueError("Duration must be greater than 0.")
    if samples <= 0:
        raise ValueError("Samples must be greater than 0.")

    trace: List[Tuple[float, float]] = []
    start_time = time.time()
    interval = duration / samples

    for i in range(samples):
        step_start = time.time()

        try:
            power = device.get_power()
        except Exception as e:
            raise RuntimeError(f"Error reading power at sample index {i}: {e}")

        elapsed = time.time() - start_time
        trace.append((elapsed, power))

        if callback:
            callback(power, elapsed)

        # Respect the target sample interval
        step_elapsed = time.time() - step_start
        sleep_time = interval - step_elapsed
        if sleep_time > 0 and (time.time() - start_time) < duration:
            time.sleep(sleep_time)

    return trace


def measure_power(
    device: PowerMeter,
    duration: float = 1.0,
    samples: int = 10,
    callback: Optional[Callable[[float, float], None]] = None,
) -> Tuple[float, float]:
    """Sample power and return ``(mean, std_dev)``.

    Convenience wrapper around :func:`read`.  Use this when you only
    need the summary statistics — e.g. for alignment optimisation.

    Args:
        device: Connected power meter instance.
        duration: Measurement duration in seconds.
        samples: Number of sample points to acquire.
        callback: Optional ``callback(power_val, elapsed_time)`` fired after
            each successful reading.

    Returns:
        Tuple of ``(mean_power_watts, std_deviation_watts)``.
    """
    trace = read(device, duration, samples, callback)
    powers = [p for _, p in trace]
    
    return _mean_std(powers)


def compute_statistics(
    trace: List[Tuple[float, float]],
    duration: Optional[float] = None,
) -> Dict[str, float]:
    """Compute descriptive statistics from a raw power trace.

    Args:
        trace: Raw ``(elapsed_time, power)`` pairs from :func:`read`.
        duration: Total measurement duration.  If ``None``, derived from the
            last sample's timestamp.

    Returns:
        Dict with keys: ``mean``, ``std_dev``,
        ``rel_std_dev_pct``, ``min``, ``max``, ``count``,
        ``duration``.
    """
    powers = [p for _, p in trace]
    n = len(powers)

    if duration is None:
        duration = trace[-1][0] if trace else 0.0

    if n == 0:
        return {
            "mean": 0.0, "std_dev": 0.0,
            "rel_std_dev_pct": 0.0, "min": 0.0, "max": 0.0,
            "count": 0, "duration": duration,
        }

    mean, std_dev = _mean_std(powers)
    rel_std_dev_pct = (std_dev / mean * 100.0) if mean != 0 else 0.0

    return {
        "mean": mean,
        "std_dev": std_dev,
        "rel_std_dev_pct": rel_std_dev_pct,
        "min": min(powers),
        "max": max(powers),
        "count": n,
        "duration": duration,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mean_std(values: List[float]) -> Tuple[float, float]:
    """Return (mean, sample_std_dev) for a list of values."""
    if not values:
        return 0.0, 0.0
    arr = np.asarray(values, dtype=float)
    if len(values) < 2:
        return float(arr.mean()), 0.0
    return float(arr.mean()), float(arr.std(ddof=1))


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_power(value: float) -> str:
    """Format a power value in engineering notation."""
    if value >= 1.0:
        return f"{value:.6f} W"
    elif value >= 1e-3:
        return f"{value * 1e3:.4f} mW"
    elif value >= 1e-6:
        return f"{value * 1e6:.4f} uW"
    elif value >= 1e-9:
        return f"{value * 1e9:.4f} nW"
    elif value >= 1e-12:
        return f"{value * 1e12:.4f} pW"
    else:
        return f"{value:.6e} W"


def export(
    trace: List[Tuple[float, float]],
    stats: Dict[str, float],
    fmt: str,
    output_file: Optional[str] = None,
    *,
    info: str = "N/A",
    backend: str = "N/A",
    address: str = "N/A",
) -> None:
    """Export a measurement trace and statistics to a file or stdout.

    Args:
        trace: Raw ``(elapsed_time, power)`` pairs from :func:`read`.
        stats: Statistics dict from :func:`compute_statistics`.
        fmt: Output format — ``"csv"``, ``"npz"``, ``"txt"``, ``"json"``,
            or ``"table"``.
        output_file: File path to write to.  Prints to stdout if ``None``.
        info: Device identity string.
        backend: Backend name.
        address: Device address.
    """
    if fmt == "npz":
        if not output_file:
            raise ValueError("NPZ format requires --output / -o.")
        try:
            import numpy as np
        except ImportError:
            raise ImportError("The 'numpy' library is required for NPZ export.")
        try:
            times = [s[0] for s in trace]
            powers = [s[1] for s in trace]
            np.savez_compressed(output_file, times=np.array(times), powers=np.array(powers))
            print(f"Saved NPZ to {output_file}")
        except Exception as e:
            print(f"Error saving NPZ file: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if fmt == "csv":
        lines = ["Time(s),Power(W)"]
        for s in trace:
            lines.append(f"{s[0]:.6f},{s[1]:.8e}")
        content = "\n".join(lines) + "\n"
    elif fmt == "txt":
        content = "\n".join(f"{s[1]:.8e}" for s in trace) + "\n"
    elif fmt == "json":
        out = {
            "backend": backend,
            "address": address,
            "mean_w": stats["mean"],
            "std_dev_w": stats["std_dev"],
            "variance_w2": stats["std_dev"] ** 2,
            "rel_std_dev_pct": stats["rel_std_dev_pct"],
            "min_w": stats["min"],
            "max_w": stats["max"],
            "ptp_w": stats["max"] - stats["min"],
            "count": stats["count"],
            "duration_s": stats["duration"],
        }
        content = json.dumps(out, indent=2) + "\n"
    else:  # "table"
        content = (
            f"Device Info:          {info}\n"
            f"Backend:              {backend}\n"
            f"Address:              {address}\n"
            f"Total Samples:        {stats['count']}\n"
            f"Actual Duration:      {stats['duration']:.3f} s\n"
            f"{'-' * 50}\n"
            f"Average (Mean) Power: {format_power(stats['mean'])} ({stats['mean']:.8e} W)\n"
            f"Std Deviation (SD):   {format_power(stats['std_dev'])} ({stats['std_dev']:.8e} W)\n"
            f"Variance (Var):      {stats['std_dev'] ** 2:.8e} W²\n"
            f"Relative SD / Error:  {stats['rel_std_dev_pct']:.4f} %\n"
            f"Peak-to-Peak (PTP):   {format_power(stats['max'] - stats['min'])}\n"
            f"Min Power:            {format_power(stats['min'])}\n"
            f"Max Power:            {format_power(stats['max'])}\n"
        )

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Saved to {output_file}")
    else:
        print(content)
