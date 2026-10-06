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
from dataclasses import dataclass, field
from typing import List, Optional, Type

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
        device_path:  Device path or URI, e.g. ``"/dev/ttyUSB0"`` or ``"usb://0x1234"``.
        serial_number: Device serial number (if available).
        description:  Human-readable device description.
    """

    backend_name: str
    device_path: str
    serial_number: Optional[str] = None
    description: Optional[str] = None

    def __str__(self) -> str:
        parts = [f"[{self.backend_name}] {self.device_path}"]
        if self.serial_number:
            parts.append(f"S/N: {self.serial_number}")
        if self.description:
            parts.append(self.description)
        return " | ".join(parts)


@dataclass
class SinglesResult:
    """Singles (count-rate) measurement result.

    Returned by ``TDCBackend.get_singles()``.

    Attributes:
        integration_time: Integration time in seconds.
        counts:           Raw counts per channel, shape ``(n_channels,)``.
        count_rates:      Count rates per channel in counts/s, shape ``(n_channels,)``.
    """

    integration_time: float
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

    def __post_init__(self) -> None:
        self.total_events = len(self.timestamps)
        if len(self.timestamps) != len(self.channels):
            raise ValueError(
                f"timestamps and channels length mismatch: "
                f"{len(self.timestamps)} vs {len(self.channels)}"
            )

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


@dataclass
class G2Result:
    """Second-order correlation (g²) result.

    Returned by ``TDCBackend.get_g2()`` or post-processing functions.

    Attributes:
        histogram:        Correlation histogram counts, shape ``(n_bins,)``.
        bin_edges:         Histogram bin edges in bin, shape ``(n_bins + 1,)``.
        singles_start:    Singles count rate of the start channel (counts/s).
        singles_stop:     Singles count rate of the stop channel (counts/s).
        integration_time: Integration time in seconds.
        resolution_ps:    Bin width in picoseconds.
    """

    histogram: NDArray[np.uint64]
    bin_edges: NDArray[np.float64]
    singles_start: float
    singles_stop: float
    integration_time: float
    resolution_ps: float

    # -- convenience helpers ------------------------------------------------

    @property
    def bin_centers(self) -> NDArray[np.float64]:
        """Bin centres"""
        return (self.bin_edges[:-1] + self.bin_edges[1:]) / 2.0

    @property
    def n_bins(self) -> int:
        """Number of bins."""
        return len(self.histogram)

    @property
    def normalized(self) -> NDArray[np.float64]:
        """Normalized g²(τ) values.

        Uses the formula: g²(τ) = C(τ) / (R_start * R_stop * Δτ * T)
        where C(τ) is raw coincidence counts, Δτ is bin width, T is integration time.
        """
        bin_width_s = np.diff(self.bin_edges) * 1e-12  # ps -> s
        denominator = self.singles_start * self.singles_stop * bin_width_s * self.integration_time
        with np.errstate(divide="ignore", invalid="ignore"):
            g2 = np.where(denominator > 0, self.histogram / denominator, 0.0)
        return g2

    def __repr__(self) -> str:
        return (
            f"G2Result(bins={self.n_bins}, "
            f"start={self.singles_start:.0f}cps, "
            f"stop={self.singles_stop:.0f}cps, "
            f"t={self.integration_time:.3f}s)"
        )

@dataclass
class CoincidenceResult:
    """Coincidence counting result.

    Returned by ``TDCBackend.get_coincidence()``.

    Attributes:
        count:            Raw coincidence events inside the signal window.
        acc_count_perbin: Mean accidental count per sideband bin. ``None`` for
                          hardware results without a background measurement.
        accidental_count: Estimated accidental events inside the signal window,
                          inferred from ``acc_count_perbin``. ``None`` for
                          hardware results without a background measurement.
        accidental_method: Method used for the accidental estimate, such as
                           ``"sideband"`` or ``"rate_product"``.
        channel1_rate:    Count rate (counts/s) of the first coincidence channel.
        channel2_rate:    Count rate (counts/s) of the second coincidence channel.
        channel3_rate:    Count rate (counts/s) of the third channel (3-fold only), else None.
        integration_time: Actual acquisition duration in seconds.
        order:            Coincidence order (2 = two-fold, 3 = three-fold).
        window_ps:        Coincidence gate width in picoseconds (if known).
        window_start_ps:  Signal-window start in picoseconds (if known).
        window_stop_ps:   Signal-window stop in picoseconds (if known).
        method:           ``"software"`` or ``"hardware"``.
    """

    count: int
    channel1_rate: float
    channel2_rate: float
    channel3_rate: Optional[float] = None
    integration_time: float = 0.0
    order: int = 2
    window_ps: Optional[int] = None
    acc_count_perbin: Optional[float] = None
    accidental_count: Optional[float] = None
    accidental_method: Optional[str] = None
    window_start_ps: Optional[float] = None
    window_stop_ps: Optional[float] = None
    method: str = "software"

    def __post_init__(self) -> None:
        if self.order not in (2, 3):
            raise ValueError(f"order must be 2 or 3, got {self.order}")
        if self.method not in ("software", "hardware"):
            raise ValueError(f"Unsupported coincidence method: {self.method!r}")
        if self.window_ps is None and self.window_start_ps is not None and self.window_stop_ps is not None:
            self.window_ps = int(self.window_stop_ps - self.window_start_ps)

    @property
    def net_count(self) -> float:
        """Raw signal-window count after subtracting estimated background."""
        if self.accidental_count is None:
            return float(self.count)
        return float(self.count) - self.accidental_count

    @property
    def background_count(self) -> Optional[float]:
        """Backward-compatible alias for ``accidental_count``."""
        return self.accidental_count

    @property
    def net_rate(self) -> float:
        """Background-corrected coincidence rate in counts/s."""
        if self.integration_time > 0:
            return self.net_count / self.integration_time
        return 0.0

    @property
    def rate(self) -> float:
        """Coincidence count rate in counts/s."""
        if self.integration_time > 0:
            return self.count / self.integration_time
        return 0.0

    def __repr__(self) -> str:
        return (
            f"CoincidenceResult(count={self.count}, accidental={self.accidental_count}, "
            f"order={self.order}-fold, method={self.method}, "
            f"window={self.window_ps}ps, t={self.integration_time:.3f}s)"
        )


@dataclass
class TripletResult:
    """3-fold coincidence measurement result.

    Attributes:
        hist_21: Histogram of (t2 - t1) delays, shape ``(bins,)``.
        hist_31: Histogram of (t3 - t1) delays, shape ``(bins,)``.
        hist_32: Histogram of (t3 - t2) delays, shape ``(bins,)``.
        hist_23: Histogram of (t2 - t3) delays, shape ``(bins,)``.
        bins:    Number of histogram bins.
        singles: Tuple of singles rates ``(rate_ch1, rate_ch2, rate_ch3)``.
        integration_time: Total integration time in seconds.
        events:  List of triplet events (may be empty). Each event is
            ``((t1, t2, t3), ref_idx)`` where timestamps are in bin units
            (int64) and *ref_idx* is the index of the reference event in
            the original t1 array.
    """

    hist_21: NDArray[np.uint64]
    hist_31: NDArray[np.uint64]
    hist_32: NDArray[np.uint64]
    hist_23: NDArray[np.uint64]
    bins: int
    singles: tuple
    integration_time: float
    events: list = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"TripletResult(bins={self.bins}, "
            f"singles={tuple(f'{s:.0f}' for s in self.singles)}, "
            f"events={len(self.events)}, "
            f"t={self.integration_time:.3f}s)"
        )


@dataclass
class GateResult:
    """N-fold gated coincidence measurement result.

    Attributes:
        pairwise_hists: List of histograms ``(signal[k] - ref)`` for each signal channel.
            Each histogram records the delay of **all** signal hits within the window,
            regardless of whether the other signal channels also had a hit.
        n_fold_count:   Number of reference events for which **all** signal channels
            had at least one hit in the coincidence window. This is a count of gated
            reference events, not the product of per-channel hit multiplicities.
        bins:           Number of histogram bins.
        channels:       Channel list ``[ref_ch, sig_ch1, sig_ch2, ...]``.
        singles:        Singles rates for each channel.
        integration_time: Total integration time in seconds.
        events:  List of N-fold gate events (may be empty). Each event is
            ``((t_ref, t_sig0, t_sig1, ...), ref_idx)`` where timestamps are
            in bin units (int64) and *ref_idx* is the index of the reference
            event in the original t_ref array.
    """

    pairwise_hists: list
    n_fold_count: int
    bins: int
    channels: list
    singles: list
    integration_time: float
    events: list = field(default_factory=list)

    @property
    def n_signals(self) -> int:
        """Number of signal channels."""
        return len(self.pairwise_hists)

    def __repr__(self) -> str:
        return (
            f"GateResult(bins={self.bins}, "
            f"n_fold={self.n_fold_count}, "
            f"channels={self.channels}, "
            f"events={len(self.events)}, "
            f"t={self.integration_time:.3f}s)"
        )


@dataclass
class GatePhotonResult:
    """Gate-to-photon correspondence result.

    For each gate trigger event, lists all photon hits within the
    coincidence window (one-to-many mapping).

    Attributes:
        per_gate:       List of per-gate photon hit lists. ``per_gate[i]`` is a
                        list of ``(photon_ts, channel_idx)`` tuples for gate *i*.
        flat_photons:   Flat int64 array of all photon timestamps (bin units).
        flat_channels:  Flat int32 array of channel indices for each photon.
        flat_offsets:   Int32 array ``[n_gates+1]`` of start offsets into the
                        flat arrays for each gate.
        n_gates:        Number of gate events.
        bins:           Window size in bins.
        channels:       Channel list ``[gate_ch, ph_ch1, ph_ch2, ...]``.
        singles:        Singles rates for each channel.
        integration_time: Total integration time in seconds.
    """

    per_gate: list
    flat_photons: "NDArray[np.int64] | None"
    flat_channels: "NDArray[np.int32] | None"
    flat_offsets: "NDArray[np.int32] | None"
    n_gates: int
    bins: int
    channels: list
    singles: list
    integration_time: float

    @property
    def total_photons(self) -> int:
        """Total number of photon hits across all gates."""
        if self.flat_photons is not None:
            return len(self.flat_photons)
        return sum(len(h) for h in self.per_gate)

    def __repr__(self) -> str:
        return (
            f"GatePhotonResult(gates={self.n_gates}, "
            f"photons={self.total_photons}, "
            f"bins={self.bins}, "
            f"t={self.integration_time:.3f}s)"
        )


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
        file_exists = os.path.exists(self.filename) and os.path.getsize(self.filename) > 0

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

    # Read file
    is_header_logged = False
    _headers = []
    _data = []
    with open(filename, "r") as f:
        for row_str in f:
            # Squash all intermediate spaces
            row = re.sub(r"\s+", " ", row_str.strip()).split(" ")
            try:
                # Equivalent to Pandas's 'applymap'
                row = [f(v) for f, v in zip(_maps, row)]
                _data.append(row)
            except Exception:
                # If fails, assume is string header
                if not is_header_logged:
                    _headers = row
                    is_header_logged = True

    if not is_header_logged:
        raise ValueError("Data file does not contain a header.")

    # Merge headers
    _data = np.array(list(zip(*_data)))  # type: ignore
    _items = tuple(zip(_headers, _data))  # type: ignore
    return dict(_items)


def save_ts_binary(filename: str, timestamps: NDArray[np.int64], channels: NDArray[np.uint8], resolution_ps: float) -> None:
    """Save raw timestamp events to a binary .ts file.

    File format:
      - 4 bytes: ASCII signature b"TDC\\x01"
      - 8 bytes (uint64): Number of events N
      - 8 bytes (float64): Time resolution in ps
      - N * 8 bytes (int64): Timestamps array
      - N * 1 byte (uint8): Channels array
    """
    with open(filename, "wb") as f:
        f.write(b"TDC\x01")
        f.write(np.uint64(len(timestamps)).tobytes())
        f.write(np.float64(resolution_ps).tobytes())
        f.write(timestamps.tobytes())
        f.write(channels.tobytes())


def save_hdf5(filename: str, timestamps: NDArray[np.int64], channels: NDArray[np.uint8], resolution_ps: float) -> None:
    """Save raw timestamp events to a compressed HDF5 (.h5) file."""
    try:
        import h5py
    except ImportError:
        raise ImportError(
            "The 'h5py' library is required to save HDF5 files. "
            "Please install it using: pip install h5py"
        )
    with h5py.File(filename, "w") as f:
        f.create_dataset("timestamps", data=timestamps, compression="gzip")
        f.create_dataset("channels", data=channels, compression="gzip")
        f.attrs["resolution_ps"] = resolution_ps
