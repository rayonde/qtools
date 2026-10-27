"""Pure Python parser for Siminics FT10xx T2/T3 TTTR words."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence
from os import PathLike
from pathlib import Path

import numpy as np

from .models import MarkerEvent, ParsedTTTR, TTTREvent

T2 = "T2"
T3 = "T3"

T2_START_WORD = 0xEB90B712
T3_START_WORD = 0xEB90B713
END_WORD = 0xEEEEDDDD

_T2_TIME_MASK = (1 << 25) - 1
_T3_TIME_MASK = (1 << 15) - 1
_SYNC_MASK = (1 << 10) - 1
_CHANNEL_MASK = 0x3F
_OVERFLOW_INDICATOR = 0x3F
_T2_OVERFLOW_PERIOD = 1 << 25
_OVERFLOW_COUNTER_PERIOD = 1 << 10


def words_from_bytes(raw: bytes, *, byteorder: str = "little") -> tuple[int, ...]:
    """Convert a raw memory block into 32-bit logical words.

    ``GetMemoryData`` exposes an ``unsigned char*``.  The vendor file format
    stores each 32-bit word in the displayed MSB-first order (for example
    ``02 00 6A AB`` is a CH2 event), so big-endian is the default. Callers may
    select little-endian for a host-normalized buffer.
    """

    if byteorder not in {"little", "big"}:
        raise ValueError("byteorder must be 'little' or 'big'")
    if len(raw) % 4:
        raise ValueError(f"TTTR byte length must be a multiple of 4, got {len(raw)}")
    fmt = "<I" if byteorder == "little" else ">I"
    return tuple(value[0] for value in struct.iter_unpack(fmt, raw))


def _marker_mask(indicator: int) -> int:
    """Return a Marker mask, or zero when the indicator is not a Marker."""

    # The vendor format reserves 111111 for overflow and uses 00xxxx for
    # Marker M4..M1 bits.  Indicator zero is not a useful Marker record.
    if indicator == _OVERFLOW_INDICATOR or indicator == 0:
        return 0
    if indicator & 0x30:
        return 0
    return indicator & 0x0F


def parse_words(
    words: Iterable[int] | Sequence[int],
    *,
    mode: str,
    resolution_ps: float,
    sync_period_ps: float | None = None,
    skip_sentinels: bool = True,
) -> ParsedTTTR:
    """Decode logical T2/T3 words.

    Channel numbers are returned as 1-based CH1..CH8 values.  Marker and
    overflow records remain in ``events`` but are excluded from the generic
    timestamp arrays.
    """

    mode = mode.upper()
    if mode not in {T2, T3}:
        raise ValueError("mode must be 'T2' or 'T3'")
    if not np.isfinite(resolution_ps) or resolution_ps <= 0:
        raise ValueError("resolution_ps must be positive")
    if sync_period_ps is not None and (
        not np.isfinite(sync_period_ps) or sync_period_ps <= 0
    ):
        raise ValueError("sync_period_ps must be positive when supplied")

    event_list: list[TTTREvent] = []
    marker_list: list[MarkerEvent] = []
    timestamps: list[int] = []
    channels: list[int] = []
    overflow_count = 0
    time_epoch = 0
    sync_epoch = 0
    t2_overflow_wrap = 0
    t3_overflow_wrap = 0
    last_t2_overflow_value: int | None = None
    last_t3_overflow_value: int | None = None

    for stream_index, raw_word in enumerate(words):
        word = int(raw_word) & 0xFFFFFFFF
        if skip_sentinels and word in {T2_START_WORD, T3_START_WORD, END_WORD}:
            continue

        flag = (word >> 31) & 0x1
        indicator = (word >> 25) & _CHANNEL_MASK

        if flag == 0:
            channel = indicator + 1
            if mode == T2:
                tick = word & _T2_TIME_MASK
                # The vendor manual defines the expanded T2 timestamp as
                # ``epoch * 2**25 + cur_val + 1``.  ``time_epoch`` is the
                # overflow counter value after extending its ten-bit wrap.
                absolute_tick = time_epoch * _T2_OVERFLOW_PERIOD + tick + 1
                timestamp_ps = round(absolute_tick * resolution_ps)
                event = TTTREvent(
                    kind="channel",
                    mode=mode,
                    raw_word=word,
                    stream_index=stream_index,
                    channel=channel,
                    timestamp_ps=timestamp_ps,
                )
            else:
                delta_tick = (word >> 10) & _T3_TIME_MASK
                sync_number = word & _SYNC_MASK
                sync_index = sync_epoch * _OVERFLOW_COUNTER_PERIOD + sync_number
                delta_ps = round(delta_tick * resolution_ps)
                timestamp_ps = delta_ps
                if sync_period_ps is not None:
                    timestamp_ps = round(sync_index * sync_period_ps + delta_ps)
                event = TTTREvent(
                    kind="channel",
                    mode=mode,
                    raw_word=word,
                    stream_index=stream_index,
                    channel=channel,
                    timestamp_ps=timestamp_ps,
                    delta_ps=delta_ps,
                    sync_index=sync_index,
                )
            event_list.append(event)
            timestamps.append(int(event.timestamp_ps or 0))
            channels.append(channel)
            continue

        if indicator == _OVERFLOW_INDICATOR:
            value = word & (_SYNC_MASK if mode == T3 else 0x3FF)
            event_list.append(
                TTTREvent(
                    kind="overflow",
                    mode=mode,
                    raw_word=word,
                    stream_index=stream_index,
                    overflow_value=value,
                )
            )
            overflow_count += 1
            if mode == T2:
                if last_t2_overflow_value is not None and value < last_t2_overflow_value:
                    t2_overflow_wrap += 1
                last_t2_overflow_value = value
                # The low ten bits are the overflow counter value, rather
                # than merely a boolean overflow flag.  A value of zero
                # therefore starts the next 2^25-tick epoch.
                time_epoch = (t2_overflow_wrap * _OVERFLOW_COUNTER_PERIOD) + value + 1
            else:
                if last_t3_overflow_value is not None and value < last_t3_overflow_value:
                    t3_overflow_wrap += 1
                last_t3_overflow_value = value
                sync_epoch = (t3_overflow_wrap * _OVERFLOW_COUNTER_PERIOD) + value + 1
            continue

        mask = _marker_mask(indicator)
        if mask:
            marker = MarkerEvent(
                mask=mask,
                mode=mode,
                raw_word=word,
                stream_index=stream_index,
            )
            marker_list.append(marker)
            event_list.append(
                TTTREvent(
                    kind="marker",
                    mode=mode,
                    raw_word=word,
                    stream_index=stream_index,
                    marker_mask=mask,
                )
            )
            continue

        event_list.append(
            TTTREvent(
                kind="special",
                mode=mode,
                raw_word=word,
                stream_index=stream_index,
            )
        )

    return ParsedTTTR(
        mode=mode,
        resolution_ps=float(resolution_ps),
        events=tuple(event_list),
        timestamps=np.asarray(timestamps, dtype=np.int64),
        channels=np.asarray(channels, dtype=np.uint8),
        markers=tuple(marker_list),
        overflow_count=overflow_count,
        sync_period_ps=sync_period_ps,
    )


def parse_bytes(
    raw: bytes,
    *,
    mode: str,
    resolution_ps: float,
    sync_period_ps: float | None = None,
    byteorder: str = "big",
) -> ParsedTTTR:
    """Decode a raw TTTR byte stream."""

    return parse_words(
        words_from_bytes(raw, byteorder=byteorder),
        mode=mode,
        resolution_ps=resolution_ps,
        sync_period_ps=sync_period_ps,
    )


def parse_blocks(
    blocks: Iterable[bytes],
    *,
    mode: str,
    resolution_ps: float,
    sync_period_ps: float | None = None,
    byteorder: str = "big",
) -> ParsedTTTR:
    """Decode sequential binary blocks returned by ``GetMemoryData``.

    The block boundary is an SDK transport detail and has no meaning in the
    TTTR word stream, so blocks are joined before decoding.  Keeping this
    operation here means the backend never needs to interpret binary records.
    """

    return parse_bytes(
        b"".join(bytes(block) for block in blocks),
        mode=mode,
        resolution_ps=resolution_ps,
        sync_period_ps=sync_period_ps,
        byteorder=byteorder,
    )


def parse_file(
    path: str | PathLike[str],
    *,
    mode: str,
    resolution_ps: float,
    sync_period_ps: float | None = None,
    byteorder: str = "big",
) -> ParsedTTTR:
    """Read and decode a Siminics TTTR binary file.

    File I/O intentionally lives in this parser module rather than in the
    hardware backend.  This makes saved T2/T3 files and live SDK buffers use
    the same decoding path.  The vendor file header/trailer words are ignored
    by :func:`parse_words` by default.
    """

    return parse_bytes(
        Path(path).read_bytes(),
        mode=mode,
        resolution_ps=resolution_ps,
        sync_period_ps=sync_period_ps,
        byteorder=byteorder,
    )

