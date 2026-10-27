"""Siminics-specific result and event models.

The generic :class:`qtools.tdc.data.TimestampResult` intentionally contains
only timestamped counting-channel events.  Siminics TTTR streams also contain
overflow and Marker records, so those records are represented here and kept
available to callers without mixing them into the generic arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class MarkerEvent:
    """A decoded M1-M4 sideband event from a TTTR stream."""

    mask: int
    mode: str
    raw_word: int
    stream_index: int
    timestamp_ps: int | None = None
    sync_index: int | None = None

    @property
    def m1(self) -> bool:
        return bool(self.mask & 0x1)

    @property
    def m2(self) -> bool:
        return bool(self.mask & 0x2)

    @property
    def m3(self) -> bool:
        return bool(self.mask & 0x4)

    @property
    def m4(self) -> bool:
        return bool(self.mask & 0x8)


@dataclass(frozen=True)
class TTTREvent:
    """One event, Marker, or overflow record in original stream order."""

    kind: str
    mode: str
    raw_word: int
    stream_index: int
    channel: int | None = None
    timestamp_ps: int | None = None
    delta_ps: int | None = None
    sync_index: int | None = None
    marker_mask: int = 0
    overflow_value: int | None = None

    @property
    def is_marker(self) -> bool:
        return self.kind == "marker"

    @property
    def is_channel_event(self) -> bool:
        return self.kind == "channel"


@dataclass
class ParsedTTTR:
    """Decoded TTTR stream plus arrays suitable for the generic API."""

    mode: str
    resolution_ps: float
    events: tuple[TTTREvent, ...]
    timestamps: NDArray[np.int64] = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    channels: NDArray[np.uint8] = field(default_factory=lambda: np.empty(0, dtype=np.uint8))
    markers: tuple[MarkerEvent, ...] = ()
    overflow_count: int = 0
    sync_period_ps: float | None = None

    @property
    def channel_event_count(self) -> int:
        return int(self.timestamps.size)


@dataclass
class T1HistogramResult:
    """A hardware T1 histogram returned by the Siminics FPGA."""

    channel: int
    histogram: NDArray[np.uint64]
    bin_width_ps: float
    integration_time: float
    resolution_ps: float


@dataclass
class ITTRResult:
    """Raw ITTR acquisition result.

    The V2.2 header exposes the generic memory-data API but does not document
    the binary ITTR record layout.  Raw blocks are therefore retained exactly
    and can be decoded by a future vendor-format adapter without data loss.
    """

    mode: str
    channels: tuple[int, ...]
    integration_time: float
    interval_us: int
    raw_blocks: tuple[bytes, ...]
    data_overflow: int | None = None

    @property
    def raw_bytes(self) -> bytes:
        return b"".join(self.raw_blocks)

