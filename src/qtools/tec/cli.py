"""Command-line temperature logger for SenseFuture TEC devices."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path
from typing import Sequence

from qtools.tec.controller import TEC
from qtools.tec.exceptions import TECError


def _positive_float(value: str) -> float:
    """Parse a strictly positive floating-point CLI argument."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the ``tec`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="tec",
        description="Record SenseFuture TEC setpoint and measured temperature.",
    )
    parser.add_argument(
        "--device",
        default="",
        help="serial device path; omit to discover a connected TEC automatically",
    )
    parser.add_argument(
        "--logfile",
        default="tec.log",
        help="append records to this file (default: tec.log)",
    )
    parser.add_argument(
        "--interval",
        type=_positive_float,
        default=1.0,
        help="seconds between samples (default: 1)",
    )
    parser.add_argument(
        "--channel",
        type=int,
        choices=(1, 2),
        default=1,
        help="TEC channel to record (default: 1)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the in-memory mock device instead of serial hardware",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="record one sample and exit",
    )
    return parser


def _now() -> dt.datetime:
    """Return the current local time as a timezone-aware datetime."""
    return dt.datetime.now().astimezone()


def _write_record(
    logfile: str | Path,
    set_temp: float,
    temp: float,
    *,
    ch_prefix: str = "TC1:",
    timestamp: dt.datetime | None = None,
) -> None:
    """Append one sample using CSV or the legacy tab-separated format."""
    path = Path(logfile)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or _now()

    if path.suffix.lower() == ".csv":
        with path.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(
                [timestamp.isoformat(timespec="seconds"), set_temp, temp, ch_prefix]
            )
        return

    legacy_timestamp = timestamp.strftime("%Y%m%d_%H%M%S")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{legacy_timestamp}\tsettemp\t{set_temp}\t{ch_prefix}\n")
        stream.write(f"{legacy_timestamp}\ttemp\t{temp}\t{ch_prefix}\n")


def record_temperature(
    device: TEC,
    logfile: str | Path,
    interval: float = 1.0,
    *,
    once: bool = False,
) -> None:
    """Record ``device.settemp`` and ``device.temp`` until interrupted."""
    print(f"Recording {device.ch_prefix} to {logfile}; press Ctrl-C to stop.")
    try:
        while True:
            timestamp = _now()
            set_temp = device.settemp
            temp = device.temp
            _write_record(
                logfile,
                set_temp,
                temp,
                ch_prefix=device.ch_prefix,
                timestamp=timestamp,
            )
            print(
                f"{timestamp.strftime('%H:%M:%S')}  "
                f"set={set_temp:.4f}°C  temp={temp:.4f}°C"
            )

            if once:
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``tec`` command."""
    args = build_parser().parse_args(argv)
    try:
        with TEC(
            device=args.device,
            channel=args.channel,
            is_mock=args.mock,
            logfile=None,
        ) as device:
            record_temperature(
                device,
                args.logfile,
                interval=args.interval,
                once=args.once,
            )
    except (TECError, OSError, ValueError) as exc:
        print(f"tec: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
