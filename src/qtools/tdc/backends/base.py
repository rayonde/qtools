"""TDC Backend Abstract Base Class.

This module defines the unified interface that all TDC hardware backends must implement.
By subclassing ``TDCBackend`` and implementing all abstract methods,
any TDC hardware can be integrated into the framework.
"""

from __future__ import annotations

import enum
import math
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import List, Optional

import numpy as np

from qtools.tdc.data import (
    CoincidenceResult,
    DeviceInfo,
    SinglesResult,
    TimestampResult,
    time_to_ps,
    validate_bin_width,
)


def _find_coincidence_peaks(histogram: np.ndarray) -> np.ndarray:
    """Find prominent local peaks, with a NumPy fallback for optional SciPy."""
    histogram = np.asarray(histogram, dtype=float)
    prominence = max(1.0, 0.1 * float(np.max(histogram, initial=0.0)))
    try:
        from scipy.signal import find_peaks
    except (ImportError, OSError):
        if histogram.size < 3:
            return np.empty(0, dtype=np.int64)
        candidates = np.flatnonzero(
            (histogram[1:-1] > histogram[:-2])
            & (histogram[1:-1] >= histogram[2:])
            & (histogram[1:-1] >= prominence)
        )
        return candidates.astype(np.int64) + 1
    peaks, _ = find_peaks(histogram, prominence=prominence)
    return np.asarray(peaks, dtype=np.int64)


def _find_coincidence_peak(histogram: np.ndarray) -> Optional[int]:
    """Return the index of the single highest coincidence peak, or ``None``.

    Detects the prominent local peaks and selects the highest one. A noisy
    g2 histogram commonly shows many small side peaks; the coincidence peak
    is the dominant one, so picking the highest keeps auto-detection robust
    instead of requiring exactly one peak.
    """
    histogram = np.asarray(histogram, dtype=float)
    peaks = _find_coincidence_peaks(histogram)
    if peaks.size == 0:
        return None
    return int(peaks[int(np.argmax(histogram[peaks]))])


def _peak_width_bins(histogram: np.ndarray, peak: int, level: float = 0.5) -> int:
    """Estimate a peak's full width in bins at ``level`` of its height.

    Scans outward from ``peak`` while the histogram stays at or above
    ``level`` times the peak value. Used to size a coincidence window to the
    measured peak instead of a fixed margin.
    """
    histogram = np.asarray(histogram, dtype=float)
    if histogram.size == 0 or peak < 0 or peak >= histogram.size:
        return 1
    peak_val = float(histogram[peak])
    if peak_val <= 0:
        return 1
    cutoff = level * peak_val
    left = peak
    while left > 0 and histogram[left - 1] >= cutoff:
        left -= 1
    right = peak
    while right < histogram.size - 1 and histogram[right + 1] >= cutoff:
        right += 1
    return max(1, right - left + 1)


class BackendCapability(enum.Flag):
    """Describes hardware capabilities of a backend.

    Capabilities are combined using bitwise OR:

    Example::

        caps = BackendCapability.SINGLES | BackendCapability.TIMESTAMPS
        if BackendCapability.HIST_HARDWARE in caps:
            ...
    """

    SINGLES = enum.auto()
    """Supports singles (count-rate) acquisition."""

    TIMESTAMPS = enum.auto()
    """Supports timestamp data acquisition."""

    HIST_HARDWARE = enum.auto()
    """Supports hardware-level histogram computation."""

    HIST_SOFTWARE = enum.auto()
    """Supports software histogram computation from acquired data."""

    COINCIDENCE = enum.auto()
    """Supports hardware coincidence counting within a gate window."""

    COINCIDENCE_SOFTWARE = enum.auto()
    """Supports software coincidence counting from acquired data."""

    THRESHOLD_CONTROL = enum.auto()
    """Supports channel threshold voltage control."""


class TDCBackend(ABC):
    """Abstract base class for all TDC backends.

    Subclasses must implement all methods and properties marked with ``@abstractmethod``.

    Supports the context-manager protocol for safe connection lifecycle management:

    Example::

        with MyTDCBackend("/dev/ttyUSB0") as tdc:
            singles = tdc.get_singles(integration_time=1.0)
            print(singles)
    """

    # -- identity properties ------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier name.

        Returns:
            A unique backend name string, e.g. ``"tdc1"``.
        """

    @property
    @abstractmethod
    def vendor(self) -> str:
        """Hardware vendor name.

        Returns:
            Vendor name, e.g. ``"S-Fifteen Instruments"``.
        """

    @property
    @abstractmethod
    def channel_count(self) -> int:
        """Number of channels supported by this backend.

        Returns:
            Positive integer channel count.
        """

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapability:
        """Set of capabilities supported by this backend.

        Returns:
            Combined ``BackendCapability`` flags.
        """

    @property
    @abstractmethod
    def resolution_ps(self) -> float:
        """Time resolution in picoseconds per timestamp bin.

        Used by high-level routines (e.g. ``TDC.measure_pairs``) to convert
        bin-based window parameters into the time units expected by
        :meth:`compute_g2`.

        Returns:
            Resolution in picoseconds per bin (e.g. ``2000.0`` for 2 ns).
        """

    # -- connection management ----------------------------------------------

    # TODO: If a backend or vendor SDK is not safe to share across instances,
    # add an explicit connection-ownership/locking policy. The backend registry
    # stores classes and does not enforce instance uniqueness.

    @abstractmethod
    def connect(self, device_path: str = None, **kwargs) -> None:
        """Connect to the specified device.

        Args:
            device_path: Device path or URI. If None, the backend may
                auto-discover or use a path stored during ``__init__``.
            **kwargs:    Backend-specific connection parameters.

        Raises:
            ConnectionError: Unable to establish connection.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the current device.

        Must be safe to call even if not currently connected (idempotent).
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether the backend is currently connected.

        Returns:
            True if connected, False otherwise.
        """

    # -- data acquisition ---------------------------------------------------

    @abstractmethod
    def get_singles(self, integration_time: float) -> SinglesResult:
        """Acquire singles counts.

        Args:
            integration_time: Integration time in seconds.

        Returns:
            A ``SinglesResult`` containing per-channel counts and rates.

        Raises:
            RuntimeError: Not connected or hardware error.
        """

    @abstractmethod
    def get_timestamps(self, duration: float) -> TimestampResult:
        """Acquire timestamp data.

        Args:
            duration: Acquisition duration in seconds.

        Returns:
            A ``TimestampResult`` containing timestamps and channel data.

        Raises:
            RuntimeError: Not connected or hardware error.
        """
    
    def _bin_width(self, bin_width: int | None) -> int:
        """Resolve an analysis bin width independently of hardware resolution."""
        return validate_bin_width(self.resolution_ps if bin_width is None else bin_width)

    def get_g2(
        self,
        duration: float,
        bins: int = 500,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        bin_offset: int = 0,
        unit: str = "ns",
        method: str = "software",
        bin_width: int | None = None,
    ) -> CoincidenceResult:
        """Compute the g²(τ) correlation histogram.

        The default software implementation acquires timestamps and delegates
        histogram calculation to ``tdc.analysis.g2``. A backend that provides
        hardware g² should override this method and handle
        ``method="hardware"``.

        Args:
            duration: Acquisition duration in seconds.
            bins: Number of histogram bins (default: 500).
            ch_start: Start channel index (1-based, default: 1).
            ch_stop: Stop channel index (1-based, default: 2).
            ch_stop_delay: Time delay in specified ``unit`` added to stop channel (default: 0).
            bin_offset: Start of the correlation window in bins (default: 0).
            unit: Input time unit for ``ch_stop_delay``; results use integer ps.
            method: Implementation to use: ``"software"`` (default) or
                ``"hardware"``.
            bin_width: Analysis bin width in ps, or None for native resolution.

        Returns:
            A ``CoincidenceResult`` containing the histogram, bin edges, count rates and
            the backend-reported live measurement time.

        Raises:
            NotImplementedError: If the requested implementation is not
                supported by the backend.
        """
        if method == "hardware":
            raise NotImplementedError(
                f"Backend '{self.name}' does not implement hardware g2 computation"
            )
        if method != "software":
            raise ValueError(
                f"Unsupported g2 method: {method!r}. "
                "Expected 'software' or 'hardware'."
            )
        if (
            BackendCapability.HIST_SOFTWARE not in self.capabilities
            or BackendCapability.TIMESTAMPS not in self.capabilities
        ):
            raise NotImplementedError(
                f"Backend '{self.name}' cannot compute g2 in software: "
                "timestamp acquisition is unavailable. Use method='hardware' "
                "if the backend provides hardware g2."
            )

        if bin_width is not None:
            bin_width = validate_bin_width(bin_width)
        res = self.get_timestamps(duration)
        width = validate_bin_width(res.resolution_ps) if bin_width is None else bin_width
        # Event timestamps do not mark the start/end of the acquisition gate:
        # their first-to-last span is shortened by random arrival gaps and can
        # be inflated by a corrupt or unwrapped timestamp.  ``total_time_ns``
        # is the backend-reported live time and is the correct rate denominator.
        integration_time = res.total_time_ns * 1e-9

        ch_stop_delay_ps = time_to_ps(ch_stop_delay, unit)

        # Lazy import to avoid a circular dependency: tdc.analysis.g2 imports
        # tdc.backends.base at module level.
        from qtools.tdc.analysis.g2 import compute_g2

        return compute_g2(
            timestamps_ps=res.timestamps,
            channels=res.channels,
            ch_start=ch_start,
            ch_stop=ch_stop,
            bins=bins,
            resolution_ps=width,
            bin_offset=bin_offset,
            integration_time=integration_time,
            stop_delay=ch_stop_delay_ps,
        )

    def get_coincidence(
        self,
        duration: float,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        unit: str = "ns",
        window_start: Optional[int | float] = None,
        window_stop: Optional[int | float] = None,
        method: str = "software",
        bin_width: int | None = None,
    ) -> CoincidenceResult:
        """Measure coincidence counts using software or backend hardware.

        The default software path acquires a g² histogram and counts bins in a
        physical delay window. Bins outside that window provide a normalized
        background estimate. If no window is supplied, the highest prominent
        peak is selected automatically and its recommended window is printed.
        Hardware-capable backends override this same method.

        Args:
            duration: Acquisition duration in seconds.
            ch_start: Reference channel index (1-based).
            ch_stop: Signal channel index (1-based).
            ch_stop_delay: Delay applied by ``get_g2`` in ``unit``.
            unit: Time unit for delay and coincidence window (``ps``, ``ns``, ``us``, or ``ms``).
            window_start: Signal-window start in ``unit``. If
                omitted together with ``window_stop``, the highest prominent g² peak is
                selected automatically and the recommended window is printed.
            window_stop: Exclusive signal-window stop in ``unit``.
            method: ``"software"`` (default) or ``"hardware"``.
            bin_width: Analysis bin width in ps, or None for native resolution.

        Returns:
            A ``CoincidenceResult`` with raw signal-window pairs and estimated
            background pairs.

        Raises:
            NotImplementedError: If the backend has no hardware coincidence counting.
        """
        if method == "hardware":
            raise NotImplementedError(
                f"Backend '{self.name}' does not implement hardware coincidence counting"
            )
        if method != "software":
            raise ValueError(
                f"Unsupported coincidence method: {method!r}. "
                "Expected 'software' or 'hardware'."
            )
        if duration <= 0:
            raise ValueError("duration must be positive")
        if (window_start is None) != (window_stop is None):
            raise ValueError("window_start and window_stop must be supplied together")

        factor = time_to_ps(1, unit)
        width = self._bin_width(bin_width)
        offset = 0
        if window_start is None:
            g2_bins = 500
        else:
            start_ps = time_to_ps(window_start, unit)
            stop_ps = time_to_ps(window_stop, unit)
            if stop_ps <= start_ps:
                raise ValueError("window_stop must be greater than window_start")
            start_bin = start_ps // width
            stop_bin = math.ceil(stop_ps / width)
            offset = min(0, start_bin)
            sideband_bins = max(20, min(500, stop_bin - start_bin))
            g2_bins = stop_bin - offset + sideband_bins

        g2 = self.get_g2(
            duration=duration, bins=g2_bins, ch_start=ch_start, ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay, bin_offset=offset, unit=unit, method=method,
            bin_width=bin_width,
        )
        histogram, edges = g2.histogram[0], g2.bin_edges[0]
        if window_start is None:
            if histogram.size == 0 or np.max(histogram, initial=0) <= 0:
                raise ValueError("Cannot detect a coincidence peak in an empty histogram")
            peak = _find_coincidence_peak(histogram)
            if peak is None:
                raise ValueError("Cannot detect a coincidence peak in the histogram")
            start_ps, stop_ps = int(edges[peak]), int(edges[peak + 1])
            print(
                "Recommended coincidence window: "
                f"window_start={start_ps / factor:g} {unit}, "
                f"window_stop={stop_ps / factor:g} {unit}"
            )
        else:
            start_ps = (time_to_ps(window_start, unit) // g2.bin_width) * g2.bin_width
            stop_ps = math.ceil(time_to_ps(window_stop, unit) / g2.bin_width) * g2.bin_width

        from qtools.tdc.analysis.efficiency import compute_coincidence

        count, per_bin, accidental = compute_coincidence(
            histogram=histogram, bin_edges=edges,
            window_start=start_ps, window_stop=stop_ps,
        )
        return replace(
            g2, mode="window_count", window_start=[start_ps], window_stop=[stop_ps],
            raw_counts=[count], accidental_counts_per_bin=[per_bin],
            accidental_counts=[accidental], accidental_method=["sideband"],
        )

    # -- threshold control --------------------------------------------------

    @abstractmethod
    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        """Set threshold voltage in volts (V).

        A backend with a global threshold may ignore ``channel``. A backend
        with per-channel threshold control should apply the value to the
        specified channel, or to all channels when ``channel`` is ``None``.

        Args:
            threshold: Threshold voltage value.
            channel: Channel index (1-based, e.g. 1..N), if applicable.
        """

    def get_threshold(self, channel: int | None = None) -> float:
        """Return the cached threshold in volts.

        Hardware APIs do not expose a common readback operation, so backends
        keep the last requested public value in ``_threshold_v``.  A backend
        may override this method when it can query the instrument directly.
        """
        value = getattr(self, "_threshold_v", None)
        if value is None:
            value = getattr(self, "_init_threshold", None)
        if value is None:
            raise RuntimeError("threshold value is unavailable before configuration")
        return float(value)

    # -- device discovery ---------------------------------------------------

    @classmethod
    @abstractmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        """Discover all available devices of this type.

        Returns:
            A list of ``DeviceInfo`` for discovered devices (may be empty).
        """

    # -- context manager protocol -------------------------------------------

    def __enter__(self) -> "TDCBackend":
        """Enter the context manager.

        Note: ``connect()`` should be called before entering the context
        or within a subclass's ``__enter__`` override.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager, ensuring disconnection."""
        self.disconnect()

    # -- string representation ----------------------------------------------

    def __repr__(self) -> str:
        status = "connected" if self.is_connected() else "disconnected"
        return f"<{self.__class__.__name__} name={self.name!r} status={status}>"
