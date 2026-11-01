"""Convenience API for coincidence measurements.

The main TDC interface is :class:`qtools.tdc.TDC`.  This module keeps a
one-shot wrapper for callers that want a coincidence measurement without
managing the device context explicitly.
"""

from __future__ import annotations

from typing import Optional

from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.connection import get_tdc
from qtools.tdc.data import CoincidenceResult


def coincidence(
    backend: str = DEFAULT_TDC1_BACKEND,
    port: Optional[str] = None,
    duration: float = 1.0,
    ch_start: int = 1,
    ch_stop: int = 2,
    ch_stop_delay: int | float = 0,
    unit: str = "ns",
    window_start: int | float | None = None,
    window_stop: int | float | None = None,
    method: str = "software",
    samples: int = 1,
    bin_width: int | None = None,
) -> CoincidenceResult:
    """Acquire repeated window counts and expose per-sample rates and mean/std.

    Duration is seconds per acquisition; samples defaults to one. Delay and
    window inputs use ``unit`` (ps/ns/us/ms), and results use integer ps. Omit
    both window bounds to select a window on the first acquisition and reuse
    it. Channels and settings are fixed across acquisitions.
    """
    with get_tdc(backend, port) as tdc:
        return tdc.measure_coincidence(
            bin_width=bin_width,
            duration=duration,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            unit=unit,
            window_start=window_start,
            window_stop=window_stop,
            method=method,
            samples=samples,
        )
