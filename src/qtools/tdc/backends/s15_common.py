"""Shared utilities for S-Fifteen TDC backends (TDC1 and TDC2).

Pattern Bitmask to Physical Channel Mapping Architecture:
---------------------------------------------------------
For every captured event, S15 TDC hardware returns a binary pattern bitmask (p).
Bit position `ch - 1` (from LSB to MSB) indicates whether physical Channel `ch` fired:
  - 0b0001 (value 1):  Physical Channel 1 fired (1 << 0)
  - 0b0010 (value 2):  Physical Channel 2 fired (1 << 1)
  - 0b0100 (value 4):  Physical Channel 3 fired (1 << 2)
  - 0b1000 (value 8):  Physical Channel 4 fired (1 << 3)

Single-Channel Events (Fast Path):
  Calculates physical channel index via log2: channel = log2(p) + 1

Multi-Channel Simultaneous Hits & Multi-Hit Expansion (Slow Path):
  When multiple channels fire within the exact same hardware clock window,
  the pattern mask is the bitwise OR of their respective channel masks.
  Examples:
    - 0b0011 (value 3  = 0b0001 | 0b0010): Channels 1 and 2 fired simultaneously.
    - 0b0111 (value 7  = 0b0001 | 0b0010 | 0b0100): Channels 1, 2, and 3 fired simultaneously.
    - 0b1100 (value 12 = 0b0100 | 0b1000): Channels 3 and 4 fired simultaneously.

  The decoder expands timestamp T across the parallel output arrays:
    timestamps_out: [..., T, T, T, ...]
    channels_out:   [..., 1, 2, 3, ...]
  This cleanly preserves multi-channel coincidence events without data loss.
"""

from __future__ import annotations

import numpy as np


def decode_pattern_channels(
    timestamps: np.ndarray,
    p_masks: np.ndarray,
    channel_count: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode channel pattern bitmasks into (timestamp, channel) pairs.

    Args:
        timestamps: Absolute timestamps in picoseconds (int64), shape ``(N,)``.
        p_masks:       Channel pattern bitmasks (uint8), shape ``(N,)``.
        channel_count: Number of channels (default 4, bits 0 … 3).

    Returns:
        ``(timestamps_out, channels_out)``:
          - *timestamps_out*: expanded timestamps, int64, shape ``(M,)``.
          - *channels_out*: 1-based physical channel indices (1..N).
    """
    # Fast path: single-hit-only masks (power-of-two: 1, 2, 4, 8).
    single_hit = np.isin(p_masks, [1 << ch for ch in range(channel_count)])
    if np.all(single_hit):
        # Convert to 1-based channel indices via log2 (1→1, 2→2, 4→3, 8→4).
        channels = (np.log2(p_masks.astype(np.float64)) + 0.5).astype(np.uint8) + 1
        return timestamps, channels

    # Slow path: expand multi-hit events.
    # Count set bits per event → repeat count.
    counts = np.zeros(len(p_masks), dtype=np.intp)
    for ch in range(channel_count):
        counts += ((p_masks >> ch) & 1).astype(np.intp)

    total = int(counts.sum())
    ts_out = np.empty(total, dtype=np.int64)
    ch_out = np.empty(total, dtype=np.uint8)

    write_pos = 0
    for i in range(len(p_masks)):
        mask = int(p_masks[i])
        if mask == 0:
            continue  # no channel hit – skip (should not normally happen)
        ts_val = timestamps[i]
        for ch in range(channel_count):
            if mask & (1 << ch):
                ts_out[write_pos] = ts_val
                ch_out[write_pos] = ch + 1  # 1-based physical channel
                write_pos += 1

    return ts_out, ch_out
