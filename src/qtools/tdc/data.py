"""TDC Experimental Data Representation and Storage.

This module defines the unified data structures returned by all TDC backends,
along with utilities for experimental data storage and persistence.

For high-rate or large-scale acquisitions, raw timestamp data is typically saved using
binary '.ts' files, or compressed and optimized '.h5' (HDF5) files for persistence.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field, fields
from typing import List, Literal, Optional
from urllib.parse import urlsplit

import numpy as np
from numpy.typing import NDArray

# ===========================================================================
# 1. Data Structures (Models)
# ===========================================================================


@dataclass(frozen=True)
class DeviceInfo:
    """Describes a discovered TDC device.

    Attributes:
        backend_name: Backend identifier, e.g. ``"tdc1"``.
        device_path:  Device path or URI, e.g. ``"/dev/ttyUSB0"``,
                      ``"usb://0x1234"``, or ``"tcp://192.0.2.10:5555"``.
        serial_number: Device serial number (if available).
        description:  Human-readable device description.
        transport:    Connection transport, such as ``"serial"``, ``"usb"``,
                      or ``"ethernet"``. This is retained on the discovered
                      device record for connection selection.
        host:         Ethernet host/IP address when applicable.
        port:         Ethernet port when applicable.
        protocol:     Network or vendor protocol label when applicable.
    """

    backend_name: str
    device_path: str
    serial_number: Optional[str] = None
    description: Optional[str] = None
    transport: str = "unknown"
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None

    def __post_init__(self) -> None:
        """Infer Ethernet metadata from a network URI when needed.

        The four original fields remain positional-compatible. New discovery
        code can retain the connection transport explicitly, while legacy
        callers using a ``tcp://``, ``udp://``, or ``eth://`` path are also
        recognized as Ethernet devices.
        """
        path = str(self.device_path)
        parsed = urlsplit(path)
        scheme = parsed.scheme.lower()

        if self.transport == "unknown" and scheme in {
            "tcp",
            "udp",
            "eth",
            "ethernet",
        }:
            object.__setattr__(self, "transport", "ethernet")

        if self.transport != "ethernet":
            return

        host = self.host or parsed.hostname
        port = self.port
        protocol = self.protocol

        if port is None:
            try:
                port = parsed.port
            except ValueError:
                port = None
        if protocol is None and scheme in {"tcp", "udp"}:
            protocol = scheme

        object.__setattr__(self, "host", host)
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "protocol", protocol)

    def __str__(self) -> str:
        parts = [f"[{self.backend_name}] {self.device_path}"]
        if self.serial_number:
            parts.append(f"S/N: {self.serial_number}")
        if self.description:
            parts.append(self.description)
        if self.transport == "ethernet" and self.host:
            endpoint = self.host
            if self.port is not None:
                endpoint = f"{endpoint}:{self.port}"
            if self.protocol:
                endpoint = f"{self.protocol}://{endpoint}"
            if endpoint != self.device_path:
                parts.append(f"Ethernet: {endpoint}")
        return " | ".join(parts)


@dataclass
class SinglesResult:
    """Singles (count-rate) measurement result.

    Returned by ``TDCBackend.get_singles()``.

    Attributes:
        integration_time: Integration time in seconds.
        channel_indices: Indices of the channels for which counts are provided.
        counts:           Raw counts per channel, shape ``(n_channels,)``.
        count_rates:      Count rates per channel in counts/s, shape ``(n_channels,)``.
    """

    integration_time: float
    channels: NDArray[np.uint8]
    counts: NDArray[np.uint64]
    count_rates: NDArray[np.float64]

    # -- convenience helpers ------------------------------------------------

    @property
    def total_counts(self) -> int:
        """Sum of counts across all channels."""
        return int(np.sum(self.counts))

    @property
    def n_channels(self) -> int:
        """Number of channels."""
        return len(self.counts)

    def __repr__(self) -> str:
        rates = ", ".join(f"{r:.1f}" for r in self.count_rates)
        return (
            f"SinglesResult(t={self.integration_time:.3f}s, "
            f"counts={self.counts.tolist()}, rates=[{rates}] cps)"
        )


@dataclass(frozen=True)
class MarkerEvent:
    """A marker and its boundary in the acquired photon stream."""

    mask: int
    photon_index: int
    timestamp_ps: int | None = None
    stream_index: int | None = None


@dataclass
class TimestampResult:
    """Timestamp acquisition result.

    Returned by ``TDCBackend.get_timestamps()``.

    Attributes:
        timestamps:    Absolute timestamps in picoseconds, shape ``(n_events,)``.
        channels:      Channel index for each event, shape ``(n_events,)``.
        resolution_ps: Time resolution in picoseconds per bin.
        total_events:  Total number of recorded events.
        total_time_ns: Effective live collection time in nanoseconds. This is
                       the denominator used for rates and may be the sum of
                       gate-open intervals for gated acquisition.
    """

    timestamps: NDArray[np.int64]
    channels: NDArray[np.uint8]
    resolution_ps: float
    total_events: int = field(init=False)
    total_time_ns: float = 0.0
    markers: list[MarkerEvent] | None = None

    def __post_init__(self) -> None:
        self.total_events = len(self.timestamps)
        if len(self.timestamps) != len(self.channels):
            raise ValueError(
                f"timestamps and channels length mismatch: "
                f"{len(self.timestamps)} vs {len(self.channels)}"
            )

        if self.markers is not None:
            last_photon = 0
            last_stream = -1
            for marker in self.markers:
                if not isinstance(marker, MarkerEvent):
                    raise ValueError("markers must contain MarkerEvent values")
                if not _integer(marker.mask) or marker.mask <= 0:
                    raise ValueError("marker mask must be a positive integer")
                if (
                    not _integer(marker.photon_index)
                    or not last_photon <= marker.photon_index <= self.total_events
                ):
                    raise ValueError(
                        "marker photon_index must be ordered and within the photon array"
                    )
                if marker.timestamp_ps is not None and not _integer(
                    marker.timestamp_ps
                ):
                    raise ValueError("marker timestamp_ps must be an integer or None")
                if marker.stream_index is not None:
                    if (
                        not _integer(marker.stream_index)
                        or marker.stream_index <= last_stream
                    ):
                        raise ValueError("marker stream_index must increase")
                    last_stream = marker.stream_index
                last_photon = marker.photon_index

    @property
    def duration_s(self) -> float:
        """Effective live collection time in seconds."""
        return self.total_time_ns * 1e-9

    @property
    def span_s(self) -> float:
        """Elapsed timestamp span in seconds, independent of live time."""
        if len(self.timestamps) > 1:
            return float(self.timestamps[-1] - self.timestamps[0]) * 1e-12
        return 0.0

    def __repr__(self) -> str:
        return (
            f"TimestampResult(events={self.total_events}, "
            f"resolution_ps={self.resolution_ps:.1f}ps, "
            f"duration={self.duration_s:.6f}s)"
        )


@dataclass(kw_only=True)
class CoincidenceResult:
    """Repeated two-channel correlation and window-count results.

    Channels and settings are fixed across samples. Measurement lists have
    length samples, including a single acquisition. Physical times use unit
    (integer ps by default); integration_time is always seconds.
    """

    mode: Literal["histogram", "window_count"]
    bin_width: int
    samples: int = 1
    unit: str = "ps"
    channel_start: int
    channel_stop: int
    method: Literal["software", "hardware"] = "software"
    counts_start: Optional[list[int]]
    counts_stop: Optional[list[int]]
    singles_start: list[float]
    singles_stop: list[float]
    integration_time: list[float]
    stop_delay: list[int]
    n_bins: Optional[list[int]] = None
    stop_offset: Optional[list[int]] = None
    histogram: Optional[list[NDArray[np.uint64]]] = None
    bin_edges: Optional[list[NDArray[np.int64]]] = None
    window_start: Optional[list[int]] = None
    window_stop: Optional[list[int]] = None
    raw_counts: Optional[list[int]] = None
    accidental_counts: Optional[list[float]] = None
    accidental_counts_per_bin: Optional[list[float]] = None
    accidental_method: Optional[list[Literal["sideband", "rate_product"]]] = None

    def __post_init__(self):
        _validate_coincidence(self)

    @property
    def window_width(self) -> Optional[list[int]]:
        if self.window_start is None or self.window_stop is None:
            return None
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> Optional[list[int]]:
        widths = self.window_width
        if widths is None:
            return None
        return [(width + self.bin_width - 1) // self.bin_width for width in widths]

    @property
    def normalized(self) -> Optional[list[NDArray[np.float64]]]:
        if self.mode != "histogram" or self.histogram is None or self.bin_edges is None:
            return None
        unit_to_s = {"ps": 1e-12, "ns": 1e-09, "us": 1e-06, "ms": 0.001}
        if self.unit not in unit_to_s:
            raise ValueError(f"Unsupported time unit: {self.unit!r}")
        curves = []
        for hist, edges, start, stop, duration in zip(
            self.histogram,
            self.bin_edges,
            self.singles_start,
            self.singles_stop,
            self.integration_time,
            strict=True,
        ):
            bin_width_s = np.diff(edges) * unit_to_s[self.unit]
            denominator = start * stop * bin_width_s * duration
            curves.append(
                np.divide(
                    hist,
                    denominator,
                    out=np.zeros_like(denominator, dtype=np.float64),
                    where=denominator > 0,
                )
            )
        return curves

    @property
    def net_counts(self) -> Optional[list[float]]:
        if self.raw_counts is None or self.accidental_counts is None:
            return None
        return [
            float(raw) - accidental
            for raw, accidental in zip(
                self.raw_counts, self.accidental_counts, strict=True
            )
        ]

    @property
    def raw_pair_rate(self) -> Optional[list[float]]:
        if self.raw_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.raw_counts, self.integration_time, strict=True
            )
        ]

    @property
    def acc_pair_rate(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.accidental_counts, self.integration_time, strict=True
            )
        ]

    @property
    def net_pair_rate(self) -> Optional[list[float]]:
        counts = self.net_counts
        if counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(counts, self.integration_time, strict=True)
        ]

    @property
    def raw_pair_rate_mean(self) -> Optional[float]:
        rates = self.raw_pair_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def raw_pair_rate_std(self) -> Optional[float]:
        rates = self.raw_pair_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))

    @property
    def net_pair_rate_mean(self) -> Optional[float]:
        rates = self.net_pair_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def net_pair_rate_std(self) -> Optional[float]:
        rates = self.net_pair_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))


@dataclass(kw_only=True)
class MultiCoincidenceResult:
    """Repeated coincidence results for a fixed group of at least three channels.

    The first channel is the reference. Dictionary keys are actual channel IDs
    or directed (start, stop) pairs. Lists retain acquisition order. Physical
    times use unit (integer ps by default); integration_time is seconds.
    """

    channels: tuple[int, ...]
    mode: Literal["histogram", "window_count"]
    bin_width: int
    count_mode: Literal["combinations", "reference_events"]
    histogram_scope: Literal["coincident_events", "all_pair_hits"]
    samples: int = 1
    unit: str = "ps"
    method: Literal["software", "hardware"] = "software"
    deduplicate: bool = False
    counts: dict[int, list[int]]
    singles: dict[int, list[float]]
    integration_time: list[float]
    channel_delays: dict[int, list[int]]
    window_start: list[int]
    window_stop: list[int]
    raw_counts: list[int]
    accidental_counts: Optional[list[float]] = None
    accidental_method: Optional[list[Literal["sideband", "rate_product"]]] = None
    pairwise_hists: Optional[dict[tuple[int, int], list[NDArray[np.uint64]]]] = None
    bin_edges: Optional[dict[tuple[int, int], list[NDArray[np.int64]]]] = None
    events: Optional[list[list[tuple[tuple[int, ...], int]]]] = None

    def __post_init__(self):
        _validate_multi(self)

    @property
    def channel_ref(self) -> int:
        return self.channels[0]

    @property
    def order(self) -> int:
        return len(self.channels)

    @property
    def n_signals(self) -> int:
        return len(self.channels) - 1

    @property
    def n_bins(self) -> Optional[dict[tuple[int, int], list[int]]]:
        if self.pairwise_hists is None:
            return None
        return {
            pair: [len(hist) for hist in histograms]
            for pair, histograms in self.pairwise_hists.items()
        }

    @property
    def stop_offset(self) -> Optional[dict[tuple[int, int], list[int]]]:
        if self.bin_edges is None:
            return None
        return {
            pair: [int(edges[0]) for edges in axes]
            for pair, axes in self.bin_edges.items()
        }

    @property
    def window_width(self) -> list[int]:
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> list[int]:
        return [
            (width + self.bin_width - 1) // self.bin_width
            for width in self.window_width
        ]

    @property
    def net_counts(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            float(raw) - accidental
            for raw, accidental in zip(
                self.raw_counts, self.accidental_counts, strict=True
            )
        ]

    @property
    def raw_coincidence_rate(self) -> list[float]:
        return [
            count / duration
            for count, duration in zip(
                self.raw_counts, self.integration_time, strict=True
            )
        ]

    @property
    def acc_coincidence_rate(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.accidental_counts, self.integration_time, strict=True
            )
        ]

    @property
    def net_coincidence_rate(self) -> Optional[list[float]]:
        counts = self.net_counts
        if counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(counts, self.integration_time, strict=True)
        ]

    @property
    def raw_coincidence_rate_mean(self) -> float:
        return float(np.mean(self.raw_coincidence_rate))

    @property
    def raw_coincidence_rate_std(self) -> Optional[float]:
        if self.samples < 2:
            return None
        return float(np.std(self.raw_coincidence_rate, ddof=1))

    @property
    def net_coincidence_rate_mean(self) -> Optional[float]:
        rates = self.net_coincidence_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def net_coincidence_rate_std(self) -> Optional[float]:
        rates = self.net_coincidence_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))

    def pair_hist(
        self, channel_start: int, channel_stop: int
    ) -> Optional[list[NDArray[np.uint64]]]:
        if self.pairwise_hists is None:
            return None
        return self.pairwise_hists.get((channel_start, channel_stop))


@dataclass(kw_only=True)
class HeraldingGateResult:
    """Repeated gate associations for one heralding and fixed gated channels.

    Every herald opens a gate, including empty gates. Dictionary keys identify
    actual gated channels and lists retain acquisition order. Physical times
    use unit (integer ps by default); integration_time is seconds. Details may
    be omitted or retained in one of the flat or per_gate representations.
    """

    heralding_channel: int
    gated_channels: tuple[int, ...]
    mode: Literal["histogram", "window_count"]
    bin_width: int
    samples: int = 1
    unit: str = "ps"
    method: Literal["software", "hardware"] = "software"
    counts_heralding: list[int]
    singles_heralding: list[float]
    counts_gated: dict[int, list[int]]
    singles_gated: dict[int, list[float]]
    integration_time: list[float]
    stop_delay: dict[int, list[int]]
    window_start: list[int]
    window_stop: list[int]
    raw_counts: dict[int, list[int]]
    accidental_counts: Optional[dict[int, list[float]]] = None
    accidental_counts_per_bin: Optional[dict[int, list[float]]] = None
    accidental_method: Optional[
        dict[int, list[Literal["sideband", "rate_product"]]]
    ] = None
    histogram: Optional[dict[int, list[NDArray[np.uint64]]]] = None
    bin_edges: Optional[list[NDArray[np.int64]]] = None
    n_bins: Optional[list[int]] = None
    stop_offset: Optional[list[int]] = None
    flat_photons: Optional[list[NDArray[np.int64]]] = None
    flat_channels: Optional[list[NDArray[np.int32]]] = None
    flat_offsets: Optional[list[NDArray[np.int64]]] = None
    per_gate: Optional[list[list[list[tuple[int, int]]]]] = None

    def __post_init__(self):
        _validate_heralding(self)

    @property
    def n_gates(self) -> list[int]:
        return self.counts_heralding.copy()

    @property
    def total_photons(self) -> list[int]:
        return [
            sum((self.raw_counts[ch][i] for ch in self.gated_channels))
            for i in range(self.samples)
        ]

    @property
    def window_width(self) -> list[int]:
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> list[int]:
        return [
            (width + self.bin_width - 1) // self.bin_width
            for width in self.window_width
        ]

    @property
    def net_counts(self) -> Optional[dict[int, list[float]]]:
        if self.accidental_counts is None:
            return None
        return {
            ch: [
                float(raw) - accidental
                for raw, accidental in zip(
                    self.raw_counts[ch], self.accidental_counts[ch], strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def raw_pair_rate(self) -> dict[int, list[float]]:
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    self.raw_counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def acc_pair_rate(self) -> Optional[dict[int, list[float]]]:
        if self.accidental_counts is None:
            return None
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    self.accidental_counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def net_pair_rate(self) -> Optional[dict[int, list[float]]]:
        counts = self.net_counts
        if counts is None:
            return None
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def raw_pair_rate_mean(self) -> dict[int, float]:
        return {ch: float(np.mean(rates)) for ch, rates in self.raw_pair_rate.items()}

    @property
    def raw_pair_rate_std(self) -> Optional[dict[int, float]]:
        if self.samples < 2:
            return None
        return {
            ch: float(np.std(rates, ddof=1)) for ch, rates in self.raw_pair_rate.items()
        }

    @property
    def net_pair_rate_mean(self) -> Optional[dict[int, float]]:
        rates = self.net_pair_rate
        if rates is None:
            return None
        return {ch: float(np.mean(values)) for ch, values in rates.items()}

    @property
    def net_pair_rate_std(self) -> Optional[dict[int, float]]:
        rates = self.net_pair_rate
        if rates is None or self.samples < 2:
            return None
        return {ch: float(np.std(values, ddof=1)) for ch, values in rates.items()}

    def gate_hits(
        self, sample_index: int, gate_index: int
    ) -> Optional[list[tuple[int, int]]]:
        if not 0 <= sample_index < self.samples:
            raise IndexError("sample_index out of range")
        if not 0 <= gate_index < self.counts_heralding[sample_index]:
            raise IndexError("gate_index out of range")
        if self.flat_photons is not None:
            offsets = self.flat_offsets[sample_index]
            start, stop = (int(offsets[gate_index]), int(offsets[gate_index + 1]))
            return [
                (int(delay), int(ch))
                for delay, ch in zip(
                    self.flat_photons[sample_index][start:stop],
                    self.flat_channels[sample_index][start:stop],
                    strict=True,
                )
            ]
        if self.per_gate is not None:
            return self.per_gate[sample_index][gate_index].copy()
        return None


# ===========================================================================
# 2. Data Storage (I/O)
# ===========================================================================


class DataWriter:
    """Helper class to write measurement data rows to a file with headers."""

    def __init__(self, filename: Optional[str]) -> None:
        self.filename = filename
        self.header_written = False

    def write_row(self, headers: List[str], values: List[str]) -> None:
        """Write a row of values to the data storage file.

        If the file does not exist or is empty, writes the headers first.
        """
        if not self.filename:
            return

        # Check if file already exists and has content
        file_exists = (
            os.path.exists(self.filename) and os.path.getsize(self.filename) > 0
        )

        with open(self.filename, "a") as f:
            if not file_exists and not self.header_written:
                # Write header row
                header_line = " ".join(f"{h:>10s}" for h in headers)
                f.write(header_line + "\n")
                self.header_written = True

            # Write data row
            data_line = " ".join(f"{v:>10s}" for v in values)
            f.write(data_line + "\n")


def read_log(filename: str, schema: List, merge: bool = False) -> dict:
    """Parses a tabular data file into a dictionary of columns.

    Convenience method to read out data files generated by DataWriter.

    Args:
        filename: Filename of log file.
        schema: List of datatypes to parse each column in logfile.
        merge:
            Whether multiple logging runs in the same file should
            be merged into a single list, or as a list-of-lists.

    Note:
        This code assumes tokens in columns do not contain spaces,
        including headers.
    """

    # Custom datatype
    def convert_time(s):
        """Converts time in HHMMSS format to datetime object.

        Note:
            The default date is 1 Jan 1900.
        """
        return dt.datetime.strptime(s, "%H%M%S")

    # Parse schema
    _maps = []
    for dtype in schema:
        # Parse special (hardcoded) types
        if isinstance(dtype, str):
            if dtype == "time":
                _map = convert_time
            else:
                raise ValueError(f"Unrecognized schema value - '{dtype}'")
        # Treat everything else as regular Python datatypes
        elif isinstance(dtype, type):
            _map = dtype
        else:
            raise ValueError(f"Unrecognized schema value - '{dtype}'")
        _maps.append(_map)

    # A log may contain several runs, each introduced by a header row.  Keep
    # the runs separate until the caller asks to merge them.
    headers: list[str] | None = None
    runs: list[list[list[object]]] = []
    current: list[list[object]] = []
    with open(filename, "r", encoding="utf-8") as f:
        for row_str in f:
            text = row_str.strip()
            if not text:
                continue
            row = re.sub(r"\s+", " ", text).split(" ")
            try:
                if len(row) != len(_maps):
                    raise ValueError("row width does not match schema")
                converted = [mapper(value) for mapper, value in zip(_maps, row)]
            except Exception:
                if headers is None:
                    headers = row
                else:
                    if current:
                        runs.append(current)
                        current = []
                continue
            current.append(converted)

    if current:
        runs.append(current)
    if headers is None:
        raise ValueError("Data file does not contain a header.")
    if len(headers) != len(_maps):
        raise ValueError("Header width does not match schema")

    def columns(rows: list[list[object]]) -> list[np.ndarray]:
        if not rows:
            return [np.asarray([], dtype=object) for _ in _maps]
        return [np.asarray(values) for values in zip(*rows)]

    per_run = [columns(rows) for rows in runs]
    if merge:
        merged = {
            name: np.concatenate([run[index] for run in per_run])
            if per_run
            else np.asarray([], dtype=object)
            for index, name in enumerate(headers)
        }
        return merged

    # Preserve the historical array shape for a single run.  For files with
    # repeated headers, expose one array per run so merge=False now has a real
    # effect instead of being an ignored argument.
    if len(per_run) <= 1:
        one = per_run[0] if per_run else columns([])
        return {name: one[index] for index, name in enumerate(headers)}
    return {
        name: [run[index] for run in per_run]
        for index, name in enumerate(headers)
    }


# Shared validation keeps the three public models consistent.
_UNIT_TO_PS = {"ps": 1, "ns": 1000, "us": 1_000_000, "ms": 1_000_000_000}
_CONFIG_FIELDS = {
    "mode",
    "bin_width",
    "samples",
    "unit",
    "method",
    "channel_start",
    "channel_stop",
    "channels",
    "count_mode",
    "histogram_scope",
    "deduplicate",
    "heralding_channel",
    "gated_channels",
}


def _integer(value):
    return isinstance(value, (int, np.integer)) and not isinstance(
        value, (bool, np.bool_)
    )


def validate_bin_width(value: int | float) -> int:
    """Return a positive integer bin width in ps without rounding."""
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not np.isfinite(value)
        or value <= 0
        or int(value) != value
    ):
        raise ValueError("bin_width must be a positive integer number of ps")
    return int(value)


def time_to_ps(value, unit):
    """Convert a physical time to integer picoseconds without silent rounding."""
    if unit not in _UNIT_TO_PS:
        raise ValueError(f"Unsupported time unit: {unit!r}")
    scaled = value * _UNIT_TO_PS[unit]
    if not np.isfinite(scaled) or not np.isclose(
        scaled, round(scaled), rtol=0, atol=1e-6
    ):
        raise ValueError("time must be representable as integer picoseconds")
    return int(round(scaled))


def _series(value, name, samples):
    if not isinstance(value, list) or len(value) != samples:
        raise ValueError(f"{name} must be a list of length samples={samples}")
    if any(item is None for item in value):
        raise ValueError(f"{name} cannot contain missing samples")


def _numbers(values, name, *, integer=False, nonnegative=False, positive=False):
    if values is None:
        raise ValueError(f"{name} is required")
    for value in values:
        if integer and not _integer(value):
            raise ValueError(f"{name} must contain integers")
        if not isinstance(value, (int, float, np.number)) or not np.isfinite(value):
            raise ValueError(f"{name} must contain finite numbers")
        if nonnegative and value < 0 or positive and value <= 0:
            raise ValueError(f"{name} has an invalid sign")


def _fixed(values, name):
    if values is not None and any(
        not np.array_equal(value, values[0]) for value in values[1:]
    ):
        raise ValueError(f"{name} must be identical across repeated samples")


def _channels(channels, minimum):
    if not isinstance(channels, tuple) or len(channels) < minimum:
        raise ValueError(f"channels must be a tuple with at least {minimum} entries")
    if any(not _integer(ch) or ch < 0 for ch in channels) or len(set(channels)) != len(
        channels
    ):
        raise ValueError("channels must contain distinct nonnegative integer IDs")


def _keys(mapping, channels, name):
    if not isinstance(mapping, dict) or set(mapping) != set(channels):
        raise ValueError(f"{name} must have exactly the configured channel keys")


def _common(result):
    if not _integer(result.samples) or result.samples <= 0:
        raise ValueError("samples must be a positive integer")
    if not _integer(result.bin_width) or result.bin_width <= 0:
        raise ValueError("bin_width must be a positive integer")
    if result.unit not in _UNIT_TO_PS:
        raise ValueError(f"Unsupported time unit: {result.unit!r}")
    if result.mode not in {"histogram", "window_count"}:
        raise ValueError("mode must be 'histogram' or 'window_count'")
    if result.method not in {"software", "hardware"}:
        raise ValueError("method must be 'software' or 'hardware'")
    for item in fields(result):
        if item.name in _CONFIG_FIELDS:
            continue
        value = getattr(result, item.name)
        if value is None:
            continue
        if isinstance(value, dict):
            for key, series in value.items():
                _series(series, f"{item.name}[{key}]", result.samples)
        else:
            _series(value, item.name, result.samples)
    _numbers(result.integration_time, "integration_time", positive=True)


def _singles(counts, rates, duration, name, *, allow_unknown=False):
    _numbers(rates, name + " rates", nonnegative=True)
    if counts is None:
        if not allow_unknown:
            raise ValueError(f"{name} counts are required")
        return
    _numbers(counts, name + " counts", integer=True, nonnegative=True)
    if not np.allclose(rates, np.asarray(counts) / duration, rtol=1e-8, atol=1e-10):
        raise ValueError(
            f"{name} rates must use the corresponding counts and live time"
        )


def _window(result, *, allow_unknown=False):
    start, stop = result.window_start, result.window_stop
    if start is None and stop is None:
        if not allow_unknown:
            raise ValueError("window boundaries are required")
        return
    _numbers(start, "window_start", integer=True)
    _numbers(stop, "window_stop", integer=True)
    if any(b <= a for a, b in zip(start, stop, strict=True)):
        raise ValueError("window_stop must be greater than window_start")
    _fixed(start, "window_start")
    _fixed(stop, "window_stop")


def _background(counts, methods, per_bin=None):
    if (counts is None) != (methods is None):
        raise ValueError(
            "accidental_counts and accidental_method must be provided together"
        )
    if counts is not None:
        _numbers(counts, "accidental_counts", nonnegative=True)
        if any(method not in {"sideband", "rate_product"} for method in methods):
            raise ValueError("unsupported accidental_method")
    if per_bin is not None:
        if counts is None:
            raise ValueError(
                "accidental_counts_per_bin requires an accidental estimate"
            )
        _numbers(per_bin, "accidental_counts_per_bin", nonnegative=True)


def _histograms(histograms, edges, n_bins, offsets, width):
    if any(value is None for value in (histograms, edges, n_bins, offsets)):
        raise ValueError(
            "histogram, bin_edges, n_bins and stop_offset must be supplied together"
        )
    _numbers(n_bins, "n_bins", integer=True, positive=True)
    _numbers(offsets, "stop_offset", integer=True)
    for hist, axis, size, offset in zip(
        histograms, edges, n_bins, offsets, strict=True
    ):
        if (
            not isinstance(hist, np.ndarray)
            or hist.dtype != np.uint64
            or hist.shape != (size,)
        ):
            raise ValueError(
                "histogram must be a one-dimensional uint64 array of n_bins entries"
            )
        if (
            not isinstance(axis, np.ndarray)
            or axis.dtype != np.int64
            or axis.shape != (size + 1,)
        ):
            raise ValueError(
                "bin_edges must be a one-dimensional int64 array of n_bins+1 entries"
            )
        if axis[0] != offset or np.any(np.diff(axis) != width):
            raise ValueError(
                "bin_edges must start at stop_offset and use bin_width spacing"
            )
    _fixed(edges, "bin_edges")
    _fixed(n_bins, "n_bins")
    _fixed(offsets, "stop_offset")


def _validate_coincidence(result):
    _common(result)
    _channels((result.channel_start, result.channel_stop), 2)
    for role in ("start", "stop"):
        _singles(
            getattr(result, "counts_" + role),
            getattr(result, "singles_" + role),
            result.integration_time,
            role,
            allow_unknown=result.method == "hardware",
        )
    _numbers(result.stop_delay, "stop_delay", integer=True)
    _fixed(result.stop_delay, "stop_delay")
    _window(
        result, allow_unknown=result.mode == "histogram" or result.method == "hardware"
    )
    if result.mode == "window_count" or result.raw_counts is not None:
        _numbers(result.raw_counts, "raw_counts", integer=True, nonnegative=True)
    _background(
        result.accidental_counts,
        result.accidental_method,
        result.accidental_counts_per_bin,
    )
    axes = (result.histogram, result.bin_edges, result.n_bins, result.stop_offset)
    if result.mode == "histogram" or any(value is not None for value in axes):
        _histograms(*axes, result.bin_width)
        if result.raw_counts is not None and result.window_start is not None:
            for start, stop, edges in zip(
                result.window_start, result.window_stop, result.bin_edges, strict=True
            ):
                if start not in edges or stop not in edges:
                    raise ValueError(
                        "histogram integration window must align with bin edges"
                    )


def _validate_multi(result):
    _common(result)
    _channels(result.channels, 3)
    if result.count_mode not in {"combinations", "reference_events"}:
        raise ValueError("unsupported count_mode")
    if result.histogram_scope not in {"coincident_events", "all_pair_hits"}:
        raise ValueError("unsupported histogram_scope")
    for name in ("counts", "singles", "channel_delays"):
        _keys(getattr(result, name), result.channels, name)
    for ch in result.channels:
        _singles(
            result.counts[ch],
            result.singles[ch],
            result.integration_time,
            f"channel {ch}",
        )
        _numbers(result.channel_delays[ch], "channel_delays", integer=True)
        _fixed(result.channel_delays[ch], "channel_delays")
    if any(result.channel_delays[result.channel_ref]):
        raise ValueError("reference channel delays must be zero")
    _window(result)
    _numbers(result.raw_counts, "raw_counts", integer=True, nonnegative=True)
    _background(result.accidental_counts, result.accidental_method)
    hists, axes = result.pairwise_hists, result.bin_edges
    if result.mode == "histogram" or hists is not None or axes is not None:
        if not hists or axes is None or set(hists) != set(axes):
            raise ValueError(
                "pairwise_hists and bin_edges must have the same nonempty keys"
            )
        for pair, histograms in hists.items():
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or pair[0] == pair[1]
                or not set(pair) <= set(result.channels)
            ):
                raise ValueError("invalid directed histogram channel pair")
            _histograms(
                histograms,
                axes[pair],
                result.n_bins[pair],
                result.stop_offset[pair],
                result.bin_width,
            )
        required = {(result.channel_ref, ch) for ch in result.channels[1:]}
        if result.histogram_scope == "coincident_events" and result.order == 3:
            required |= {
                (result.channels[1], result.channels[2]),
                (result.channels[2], result.channels[1]),
            }
        if not required <= set(hists):
            raise ValueError("missing required directed pair histograms")
    if result.events is not None:
        for i, events in enumerate(result.events):
            for delays, ref in events:
                if (
                    len(delays) != result.order
                    or delays[0] != 0
                    or any(not _integer(d) for d in delays)
                ):
                    raise ValueError(
                        "event delays must match channels with zero reference delay"
                    )
                if (
                    not _integer(ref)
                    or not 0 <= ref < result.counts[result.channel_ref][i]
                ):
                    raise ValueError("event reference index is out of range")
                if any(
                    not result.window_start[i] <= delay < result.window_stop[i]
                    for delay in delays[1:]
                ):
                    raise ValueError("event delays must lie in the coincidence window")


def _validate_heralding(result):
    _common(result)
    _channels(result.gated_channels, 1)
    _channels((result.heralding_channel,) + result.gated_channels, 2)
    _singles(
        result.counts_heralding,
        result.singles_heralding,
        result.integration_time,
        "heralding",
    )
    required = ("counts_gated", "singles_gated", "stop_delay", "raw_counts")
    optional = (
        "accidental_counts",
        "accidental_method",
        "accidental_counts_per_bin",
        "histogram",
    )
    for name in required + optional:
        value = getattr(result, name)
        if name in required or value is not None:
            _keys(value, result.gated_channels, name)
    if (result.accidental_counts is None) != (result.accidental_method is None):
        raise ValueError(
            "accidental_counts and accidental_method must be provided together"
        )
    if (
        result.accidental_counts_per_bin is not None
        and result.accidental_counts is None
    ):
        raise ValueError("accidental_counts_per_bin requires an accidental estimate")
    _window(result)
    for ch in result.gated_channels:
        _singles(
            result.counts_gated[ch],
            result.singles_gated[ch],
            result.integration_time,
            f"channel {ch}",
        )
        _numbers(result.stop_delay[ch], "stop_delay", integer=True)
        _fixed(result.stop_delay[ch], "stop_delay")
        _numbers(result.raw_counts[ch], "raw_counts", integer=True, nonnegative=True)
        _background(
            None if result.accidental_counts is None else result.accidental_counts[ch],
            None if result.accidental_method is None else result.accidental_method[ch],
            None
            if result.accidental_counts_per_bin is None
            else result.accidental_counts_per_bin[ch],
        )
        if any(
            n == 0 and count != 0
            for n, count in zip(result.n_gates, result.raw_counts[ch], strict=True)
        ):
            raise ValueError("zero heralding triggers require zero gate associations")
    axes = (result.histogram, result.bin_edges, result.n_bins, result.stop_offset)
    if result.mode == "histogram" or any(value is not None for value in axes):
        if any(value is None for value in axes):
            raise ValueError(
                "histogram and complete axis metadata are required together"
            )
        for ch in result.gated_channels:
            _histograms(
                result.histogram[ch],
                result.bin_edges,
                result.n_bins,
                result.stop_offset,
                result.bin_width,
            )
        for start, stop, edges in zip(
            result.window_start, result.window_stop, result.bin_edges, strict=True
        ):
            if start not in edges or stop not in edges:
                raise ValueError("gate window must align with histogram bin edges")
    flat = (result.flat_photons, result.flat_channels, result.flat_offsets)
    has_flat = any(value is not None for value in flat)
    if has_flat and (
        any(value is None for value in flat) or result.per_gate is not None
    ):
        raise ValueError("provide exactly one complete gate-detail representation")
    for i in range(result.samples):
        if has_flat:
            delays, channels, offsets = (value[i] for value in flat)
            for array, dtype in (
                (delays, np.int64),
                (channels, np.int32),
                (offsets, np.int64),
            ):
                if (
                    not isinstance(array, np.ndarray)
                    or array.ndim != 1
                    or array.dtype != dtype
                ):
                    raise ValueError("gate detail arrays have invalid shape or dtype")
            if len(delays) != len(channels) or len(offsets) != result.n_gates[i] + 1:
                raise ValueError("gate detail array lengths do not match")
            if (
                offsets[0] != 0
                or offsets[-1] != len(delays)
                or np.any(np.diff(offsets) < 0)
            ):
                raise ValueError("invalid gate offsets")
            hits = zip(delays, channels, strict=True)
        elif result.per_gate is not None:
            gates = result.per_gate[i]
            if len(gates) != result.n_gates[i]:
                raise ValueError(
                    "per_gate must contain every gate, including empty gates"
                )
            hits = (hit for gate in gates for hit in gate)
        else:
            continue
        counts = dict.fromkeys(result.gated_channels, 0)
        for delay, ch in hits:
            if not _integer(delay) or not _integer(ch) or ch not in counts:
                raise ValueError(
                    "gate hits must use integer delays and actual gated channel IDs"
                )
            if not result.window_start[i] <= delay < result.window_stop[i]:
                raise ValueError("gate hit delay lies outside the window")
            counts[ch] += 1
        if any(counts[ch] != result.raw_counts[ch][i] for ch in counts):
            raise ValueError("gate details do not match raw_counts")


def combine_samples(results):
    """Join completed acquisitions with the same model and measurement configuration."""
    if not results:
        raise ValueError("at least one result is required")
    first = results[0]
    if any(type(result) is not type(first) for result in results):
        raise ValueError("all samples must use the same result model")
    values = {}
    for item in fields(first):
        name = item.name
        group = [getattr(result, name) for result in results]
        if name == "samples":
            values[name] = sum(group)
        elif name in _CONFIG_FIELDS:
            if any(value != group[0] for value in group[1:]):
                raise ValueError(
                    f"inconsistent repeated measurement configuration: {name}"
                )
            values[name] = group[0]
        elif all(value is None for value in group):
            values[name] = None
        elif any(value is None for value in group):
            raise ValueError(f"incomplete repeated measurement data: {name}")
        elif isinstance(group[0], dict):
            if any(set(value) != set(group[0]) for value in group[1:]):
                raise ValueError(f"inconsistent channel keys: {name}")
            values[name] = {
                key: [sample for value in group for sample in value[key]]
                for key in group[0]
            }
        else:
            values[name] = [sample for value in group for sample in value]
    return type(first)(**values)


def convert_time_unit(result, unit):
    """Return an analysis result in another unit, rejecting fractional integers."""
    if unit not in _UNIT_TO_PS:
        raise ValueError(f"Unsupported time unit: {unit!r}")
    source, target = _UNIT_TO_PS[result.unit], _UNIT_TO_PS[unit]

    def scale(value):
        if value is None:
            return None
        if isinstance(value, dict):
            return {key: scale(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scale(item) for item in value]
        if isinstance(value, np.ndarray):
            return np.asarray([scale(int(item)) for item in value], dtype=np.int64)
        integer, remainder = divmod(int(value) * source, target)
        if remainder:
            raise ValueError(
                f"time value {value} cannot be represented as integer {unit}"
            )
        return integer

    names = {
        "bin_width",
        "stop_delay",
        "channel_delays",
        "stop_offset",
        "bin_edges",
        "window_start",
        "window_stop",
        "flat_photons",
    }
    values = {item.name: getattr(result, item.name) for item in fields(result)}
    for name in names & values.keys():
        values[name] = scale(values[name])
    if values.get("events") is not None:
        values["events"] = [
            [(tuple(scale(delay) for delay in delays), ref) for delays, ref in events]
            for events in values["events"]
        ]
    if values.get("per_gate") is not None:
        values["per_gate"] = [
            [[(scale(delay), ch) for delay, ch in hits] for hits in gates]
            for gates in values["per_gate"]
        ]
    values["unit"] = unit
    return type(result)(**values)


def _timestamp_arrays(result):
    markers = result.markers or []
    return {
        "timestamps": result.timestamps,
        "channels": result.channels,
        "resolution_ps": np.float64(result.resolution_ps),
        "total_time_ns": np.float64(result.total_time_ns),
        "markers_provided": np.bool_(result.markers is not None),
        "marker_mask": np.asarray([m.mask for m in markers], dtype=np.uint64),
        "marker_photon_index": np.asarray(
            [m.photon_index for m in markers], dtype=np.int64
        ),
        "marker_timestamp_ps": np.asarray(
            [m.timestamp_ps if m.timestamp_ps is not None else 0 for m in markers],
            dtype=np.int64,
        ),
        "marker_timestamp_valid": np.asarray(
            [m.timestamp_ps is not None for m in markers], dtype=np.bool_
        ),
        "marker_stream_index": np.asarray(
            [m.stream_index if m.stream_index is not None else 0 for m in markers],
            dtype=np.int64,
        ),
        "marker_stream_valid": np.asarray(
            [m.stream_index is not None for m in markers], dtype=np.bool_
        ),
    }


def _timestamp_from_arrays(data):
    markers = None
    if bool(data["markers_provided"]):
        markers = [
            MarkerEvent(
                int(mask),
                int(photon),
                int(ts) if ts_valid else None,
                int(stream) if stream_valid else None,
            )
            for mask, photon, ts, ts_valid, stream, stream_valid in zip(
                *(
                    data[name]
                    for name in (
                        "marker_mask",
                        "marker_photon_index",
                        "marker_timestamp_ps",
                        "marker_timestamp_valid",
                        "marker_stream_index",
                        "marker_stream_valid",
                    )
                ),
                strict=True,
            )
        ]
    return TimestampResult(
        timestamps=data["timestamps"],
        channels=data["channels"],
        resolution_ps=float(data["resolution_ps"]),
        total_time_ns=float(data["total_time_ns"]),
        markers=markers,
    )


def save_ts_binary(filename, result: TimestampResult):
    """Save a complete acquisition as TDC v2 followed by NumPy archive records."""
    with open(filename, "wb") as stream:
        stream.write(b"TDC\x02")
        np.savez(stream, **_timestamp_arrays(result))


def load_ts_binary(filename) -> TimestampResult:
    """Read a TDC v2 acquisition, including marker validity and ordering."""
    with open(filename, "rb") as stream:
        if stream.read(4) != b"TDC\x02":
            raise ValueError("Unsupported timestamp file format; expected TDC v2")
        with np.load(stream, allow_pickle=False) as archive:
            return _timestamp_from_arrays(archive)


def save_hdf5(filename, result: TimestampResult):
    """Save a complete acquisition, including markers, in compressed HDF5."""
    import h5py

    with h5py.File(filename, "w") as stream:
        stream.attrs["format_version"] = 2
        for name, value in _timestamp_arrays(result).items():
            stream.create_dataset(
                name, data=value, compression="gzip" if np.ndim(value) else None
            )


def load_hdf5(filename) -> TimestampResult:
    """Read an HDF5 acquisition saved by save_hdf5."""
    import h5py

    with h5py.File(filename, "r") as stream:
        if stream.attrs.get("format_version") != 2:
            raise ValueError("Unsupported HDF5 timestamp format")
        return _timestamp_from_arrays(
            {name: value[()] for name, value in stream.items()}
        )
