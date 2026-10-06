"""Tests for ExpS15TDC1Backend — direct-serial experimental TDC1 backend.

These tests cover:
- Identity & capabilities (offline)
- Binary timestamp parsing (offline / synthetic data)
- Count acquisition line-read robustness (offline / fake serial)
- Connection lifecycle & discovery (requires hardware)
- Device settings: mode, level, threshold, int_time, clock (requires hardware)
- Data acquisition: singles, timestamps, g2 (requires hardware)
"""

from __future__ import annotations

import struct
import time

import numpy as np
import pytest
import serial

from qtools.tdc.backends.base import BackendCapability
from qtools.tdc.backends.s15_tdc1.exp_backend import CHANNEL_COUNT, RESOLUTION_PS, ExpS15TDC1Backend
from qtools.tdc.data import G2Result, SinglesResult, TimestampResult


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _synthetic_bin2_stream(
    timestamps_28bit: list[int],
    channels_4bit: list[int],
) -> bytes:
    """Pack (timestamp_28bit << 5 | channel_4bit) into little-endian uint32."""
    words = [(ts << 5) | (ch & 0xF) for ts, ch in zip(timestamps_28bit, channels_4bit)]
    return struct.pack(f"<{len(words)}I", *words)


class _FakeSerial:
    """Minimal pyserial stand-in for exercising count-line acquisition.

    Responds to ``*IDN?``, ``time?`` and count commands.  ``counts_response``
    is consumed byte-by-byte by ``inWaiting()``/``readline()`` so callers can
    inject slow or partial lines.
    """

    timeout = 0.05

    def __init__(
        self,
        counts_response: bytes = b"",
        idn_response: bytes = b"TDC1\n",
    ) -> None:
        self._buffer = bytearray()
        self._counts_response = counts_response
        self._idn_response = idn_response
        self.writes: list[bytes] = []
        self.timeout_was_set = False

    # -- pyserial API -------------------------------------------------------

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data.strip().endswith(b"counts?"):
            self._buffer.extend(self._counts_response)
        return len(data)

    def readline(self, size: int = -1) -> bytes:
        start = time.time()
        while b"\n" not in self._buffer:
            if self.timeout and time.time() - start > self.timeout:
                return b""
            time.sleep(0.005)
        index = self._buffer.index(b"\n") + 1
        line = bytes(self._buffer[:index])
        del self._buffer[:index]
        return line

    def readlines(self) -> list[bytes]:
        lines = []
        while self._buffer:
            line = self.readline()
            if not line:
                break
            lines.append(line)
        return lines

    def inWaiting(self) -> int:
        return len(self._buffer)

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def reset_output_buffer(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        if not self._buffer:
            return b""
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        return chunk

    def close(self) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. Offline identity & capability tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIdentity:
    """Properties and capabilities (no hardware needed)."""

    def test_name(self) -> None:
        backend = ExpS15TDC1Backend()
        assert backend.name == "exp_s15_tdc1"

    def test_vendor(self) -> None:
        backend = ExpS15TDC1Backend()
        assert backend.vendor == "S-Fifteen Instruments"

    def test_channel_count(self) -> None:
        backend = ExpS15TDC1Backend()
        assert backend.channel_count == CHANNEL_COUNT
        assert backend.channel_count == 4

    def test_capabilities(self) -> None:
        backend = ExpS15TDC1Backend()
        caps = backend.capabilities
        assert BackendCapability.SINGLES in caps
        assert BackendCapability.TIMESTAMPS in caps
        assert BackendCapability.HIST_SOFTWARE in caps
        assert BackendCapability.THRESHOLD_CONTROL in caps
        assert BackendCapability.HIST_HARDWARE not in caps

    def test_repr_disconnected(self) -> None:
        backend = ExpS15TDC1Backend()
        r = repr(backend)
        assert "ExpS15TDC1Backend" in r
        assert "disconnected" in r


# ═══════════════════════════════════════════════════════════════════════════
# 2. Binary timestamp parsing (offline / synthetic)
# ═══════════════════════════════════════════════════════════════════════════

class TestReadTimestampsBin2:
    """Unit tests for read_timestamps_bin2 — no hardware needed."""

    def test_empty_stream(self) -> None:
        backend = ExpS15TDC1Backend()
        ts, ch = backend.read_timestamps_bin2(b"")
        assert len(ts) == 0
        assert len(ch) == 0

    def test_single_event(self) -> None:
        backend = ExpS15TDC1Backend()
        # timestamp=100, channel=3  →  word = (100 << 5) | 3 = 3203
        stream = _synthetic_bin2_stream([100], [3])
        ts, ch = backend.read_timestamps_bin2(stream, legacy=True)
        assert len(ts) == 1
        # raw_timestamp = (word >> 5) << 1 = (100) << 1 = 200
        assert ts[0] == 200
        # legacy channels are 4-bit binary strings
        assert ch[0] == "0011"

    def test_control_word_bit4_is_dropped(self) -> None:
        backend = ExpS15TDC1Backend()
        # Real event: timestamp=100, channel=1 → (100 << 5) | 1
        # Control word: bit 0x10 set with low nibble 0x1 → would otherwise
        # decode as a phantom CH1 event.
        stream = (
            struct.pack("<I", (100 << 5) | 1)
            + struct.pack("<I", (999 << 5) | 0x11)
        )
        ts, ch = backend.read_timestamps_bin2(stream, legacy=True)
        assert len(ts) == 1
        assert ts[0] == 200
        assert ch[0] == "0001"

    def test_only_control_words_returns_empty(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = struct.pack("<I", (999 << 5) | 0x11)
        ts, ch = backend.read_timestamps_bin2(stream, legacy=False)
        assert len(ts) == 0
        assert len(ch) == 0

    def test_single_event_non_legacy(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = _synthetic_bin2_stream([42], [0xA])
        ts, ch = backend.read_timestamps_bin2(stream, legacy=False)
        assert ts[0] == 84  # (42 << 1)
        assert ch[0] == 0xA

    def test_multiple_events_no_rollover(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = _synthetic_bin2_stream([10, 20, 30], [1, 2, 4])
        ts, ch = backend.read_timestamps_bin2(stream, legacy=True)
        assert len(ts) == 3
        assert ts.tolist() == [20, 40, 60]
        assert ch.tolist() == ["0001", "0010", "0100"]

    def test_rollover_detection(self) -> None:
        backend = ExpS15TDC1Backend()
        # timestamps near the end of 28-bit range, then wrapping
        stream = _synthetic_bin2_stream(
            [0x0FFF_FFF0 >> 1, 0x0FFF_FFF8 >> 1, 10, 20],
            [1, 1, 1, 1],
        )
        ts, ch = backend.read_timestamps_bin2(stream, legacy=False)
        assert len(ts) == 4
        # first two are before rollover; last two get 1<<28 added
        assert ts[2] > (1 << 28)
        assert ts[3] > (1 << 28)

    def test_all_channels(self) -> None:
        """Every 4-bit channel pattern should survive round-trip."""
        backend = ExpS15TDC1Backend()
        for ch_val in range(16):
            stream = _synthetic_bin2_stream([1], [ch_val])
            _ts, ch = backend.read_timestamps_bin2(stream, legacy=True)
            expected = f"{ch_val:04b}"
            assert ch[0] == expected, f"channel {ch_val} → {ch[0]!r}, expected {expected!r}"

    def test_many_events(self) -> None:
        backend = ExpS15TDC1Backend()
        n = 10000
        tss = list(range(n))
        chs = [i % 16 for i in range(n)]
        stream = _synthetic_bin2_stream(tss, chs)
        ts, ch = backend.read_timestamps_bin2(stream, legacy=False)
        assert len(ts) == n
        np.testing.assert_array_equal(ts, np.array(tss, dtype=np.int64) * 2)


class TestReadTimestampsBin3:
    """Unit tests for read_timestamps_bin3 — no hardware needed."""

    def test_empty_stream(self) -> None:
        backend = ExpS15TDC1Backend()
        ts, ch = backend.read_timestamps_bin3(b"", [])
        assert len(ts) == 0
        assert len(ch) == 0

    def test_single_chunk_no_corruption(self) -> None:
        backend = ExpS15TDC1Backend()
        words = _synthetic_bin2_stream([5, 10, 15], [1, 2, 3])
        chunk_lengths = [len(words)]
        ts, ch = backend.read_timestamps_bin3(words, chunk_lengths, legacy=False)
        assert len(ts) == 3
        np.testing.assert_array_equal(ts, np.array([10, 20, 30], dtype=np.int64))

    def test_control_word_bit4_is_dropped(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = (
            struct.pack("<I", (100 << 5) | 1)
            + struct.pack("<I", (999 << 5) | 0x11)
        )
        ts, ch = backend.read_timestamps_bin3(stream, [len(stream)], legacy=True)
        assert len(ts) == 1
        assert ts[0] == 200

    def test_multiple_chunks(self) -> None:
        backend = ExpS15TDC1Backend()
        chunk1 = _synthetic_bin2_stream([1, 2], [1, 2])
        chunk2 = _synthetic_bin2_stream([3, 4], [3, 4])
        buffer = chunk1 + chunk2
        chunk_lengths = [len(chunk1), len(chunk2)]
        ts, ch = backend.read_timestamps_bin3(buffer, chunk_lengths, legacy=False)
        assert len(ts) == 4
        np.testing.assert_array_equal(ts, np.array([2, 4, 6, 8], dtype=np.int64))

    def test_legacy_mode_returns_strings(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = _synthetic_bin2_stream([1], [5])
        ts, ch = backend.read_timestamps_bin3(stream, [len(stream)], legacy=True)
        assert isinstance(ch[0], str)
        assert ch[0] == "0101"


class TestReadTimestampsBin:
    """Unit tests for read_timestamps_bin — no hardware needed."""

    def test_empty_stream(self) -> None:
        backend = ExpS15TDC1Backend()
        ts, ch = backend.read_timestamps_bin(b"")
        assert len(ts) == 0
        assert len(ch) == 0

    def test_single_event(self) -> None:
        backend = ExpS15TDC1Backend()
        # word: timestamp=1, pattern=0b00001 (ch1, no marker bit) → word = (1<<5) | 1 = 33
        stream = _synthetic_bin2_stream([1], [1])
        ts, ch = backend.read_timestamps_bin(stream, legacy=True)
        assert len(ts) == 1
        assert ts[0] == 2  # (1 << 1)
        assert ch[0] == "0001"

    def test_filter_marker_bit(self) -> None:
        """Words with bit 4 set (pattern & 0x10) are skipped.

        read_timestamps_bin uses 5-bit patterns (word & 0x1F).  Bit 4
        (value 16 / 0x10) is a marker bit — events with that bit set
        are excluded.  We construct the words manually because the
        _synthetic_bin2_stream helper masks to 4 bits.
        """
        backend = ExpS15TDC1Backend()
        # Word 0: ts=100, pattern=0x10 (marker bit set → filtered)
        # Word 1: ts=200, pattern=0x01 (valid, ch1)
        words_raw = struct.pack("<II", (100 << 5) | 0x10, (200 << 5) | 0x01)
        ts, ch = backend.read_timestamps_bin(words_raw, legacy=True)
        # Only the second event (pattern=1) survives the filter
        assert len(ts) == 1
        assert ts[0] == 400  # (200 << 1)
        assert ch[0] == "0001"

    def test_rollover_handling(self) -> None:
        backend = ExpS15TDC1Backend()
        stream = _synthetic_bin2_stream(
            [0x07FF_FFFE, 5, 10],  # first wraps to 0 after rollover
            [1, 1, 1],
        )
        ts, ch = backend.read_timestamps_bin(stream, legacy=False)
        assert len(ts) == 3
        # After rollover, later timestamps get period offset
        assert ts[1] > ts[0]
        assert ts[2] > ts[1]


# ═══════════════════════════════════════════════════════════════════════════
# 2b. Count acquisition line-read robustness (offline / fake serial)
# ═══════════════════════════════════════════════════════════════════════════

class TestCountAcquisition:
    """Line-read robustness for singles/pairs count responses.

    Regression tests for the first-acquisition ``Command timeout``: the device
    emits the count line in several USB frames, so ``readline()`` under the
    long acquisition timeout can time out mid-line.  We assert the backend
    reads the full line under a short timeout, parses exactly four fields, and
    lets the caller's retry loop handle partial lines.
    """

    @staticmethod
    def _make_backend(serial_obj) -> ExpS15TDC1Backend:
        backend = ExpS15TDC1Backend()
        backend._com = serial_obj
        backend._connected = True
        backend._device_path = "/dev/fake"
        return backend

    def test_parses_complete_line(self) -> None:
        fake = _FakeSerial(counts_response=b"1 2 3 4\n")
        backend = self._make_backend(fake)
        assert backend._get_counts_raw(0.1) == (1, 2, 3, 4)
        assert b"singles;counts?\r\n" in fake.writes
        # readline must run under the short timeout, not the acquisition time
        assert fake.timeout <= 1.0

    def test_slow_framed_line_is_assembled(self) -> None:
        """A line arriving in several USB frames must still be read fully."""
        fake = _FakeSerial(counts_response=b"5 6 7 8\n")
        backend = self._make_backend(fake)

        # Frame the response: emit one byte, wait, then the rest.  readline()
        # must block under the short timeout and collect the remaining bytes.
        def framed_write(data: bytes) -> int:
            fake._buffer.clear()
            response = fake._counts_response
            fake._buffer.extend(response[:1])
            time.sleep(0.1)  # byte arrives before the rest of the line
            fake._buffer.extend(response[1:])
            return len(data)

        fake.write = framed_write  # type: ignore[method-assign]
        assert backend._get_counts_raw(0.2) == (5, 6, 7, 8)

    def test_partial_line_raises_value_error(self) -> None:
        """A truncated line must raise ValueError, not hang or parse garbage."""
        fake = _FakeSerial(counts_response=b"1 2 3\n")  # only 3 fields
        backend = self._make_backend(fake)
        with pytest.raises(ValueError, match="counts response"):
            backend._get_counts_raw(0.1)

    def test_non_numeric_line_raises_value_error(self) -> None:
        fake = _FakeSerial(counts_response=b"1 2 3 x\n")
        backend = self._make_backend(fake)
        with pytest.raises(ValueError, match="counts response"):
            backend._get_counts_raw(0.1)

    def test_no_response_raises_timeout(self) -> None:
        """No bytes arriving within the window must raise SerialTimeoutException.

        This is the true "device never answered" case, distinct from a partial
        line; ``measurement._acquire_singles`` catches it and retries.
        """
        fake = _FakeSerial(counts_response=b"")
        backend = self._make_backend(fake)
        with pytest.raises(serial.SerialTimeoutException, match="Command timeout"):
            backend._get_counts_raw(0.1)

    def test_pairs_command_uses_pairs_line(self) -> None:
        fake = _FakeSerial(counts_response=b"1 2 3 4 0 0 0 0\n")
        backend = self._make_backend(fake)
        values = backend.get_counts_and_coincidences(0.1)
        assert values == (1, 2, 3, 4, 0, 0, 0, 0)
        assert b"pairs;counts?\r\n" in fake.writes

    def test_singles_returns_singles_result(self) -> None:
        fake = _FakeSerial(counts_response=b"1 2 3 4\n")
        backend = self._make_backend(fake)
        result = backend.get_singles(integration_time=1.0)
        assert isinstance(result, SinglesResult)
        assert result.counts.tolist() == [1, 2, 3, 4]
        assert result.count_rates.tolist() == [1.0, 2.0, 3.0, 4.0]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Connection lifecycle & discovery (requires hardware)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.hardware
class TestConnectionLifecycle:
    """Connection connect / disconnect / is_connected."""

    @pytest.fixture(autouse=True)
    def _backend(self) -> None:
        self.backend = ExpS15TDC1Backend()

    def teardown_method(self) -> None:
        if hasattr(self, "backend") and self.backend.is_connected():
            self.backend.disconnect()

    def test_discover_devices(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        assert isinstance(devices, list)
        if devices:
            for d in devices:
                assert d.backend_name == "exp_s15_tdc1"
                assert d.device_path

    def test_connect_with_discovered_path(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found for connection test")
        path = devices[0].device_path
        self.backend.connect(path)
        assert self.backend.is_connected()
        assert self.backend._device_path == path

    def test_connect_auto_discover(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found for auto-discover test")
        self.backend.connect()
        assert self.backend.is_connected()

    def test_disconnect_idempotent(self) -> None:
        """disconnect() is safe to call multiple times."""
        self.backend.disconnect()
        self.backend.disconnect()
        assert not self.backend.is_connected()

    def test_connect_idempotent(self) -> None:
        """connect() on an already-connected backend is a no-op."""
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found")
        self.backend.connect(devices[0].device_path)
        assert self.backend.is_connected()
        # Second connect should be a no-op
        self.backend.connect(devices[0].device_path)
        assert self.backend.is_connected()

    def test_connect_with_kwargs(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found")
        self.backend.connect(
            devices[0].device_path,
            mode="singles",
            level="NIM",
            integration_time=0.5,
            threshold=0.8,
        )
        assert self.backend.is_connected()
        # kwargs should be stored
        assert self.backend._init_mode == "singles"
        assert self.backend._init_level == "NIM"
        assert self.backend._init_integration_time == 0.5
        assert self.backend._init_threshold == 0.8

    def test_connect_nonexistent_path_raises(self) -> None:
        with pytest.raises(ConnectionError):
            self.backend.connect("COM999" if "COM" in (self.backend._device_path or "") else "/dev/ttyDOES_NOT_EXIST_999")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Device settings (requires hardware)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.hardware
class TestDeviceSettings:
    """Mode, level, threshold, int_time, clock get/set round-trips."""

    @pytest.fixture(autouse=True)
    def _backend(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found")
        self.backend = ExpS15TDC1Backend()
        self.backend.connect(devices[0].device_path)

    def teardown_method(self) -> None:
        if hasattr(self, "backend") and self.backend.is_connected():
            self.backend.disconnect()

    # -- mode ---------------------------------------------------------------

    def test_mode_get(self) -> None:
        mode = self.backend.mode
        assert mode in {"singles", "pairs", "timestamp"}

    def test_mode_set_singles(self) -> None:
        self.backend.mode = "singles"
        assert self.backend.mode == "singles"

    def test_mode_set_timestamp(self) -> None:
        self.backend.mode = "timestamp"
        assert self.backend.mode == "timestamp"

    def test_mode_set_pairs(self) -> None:
        self.backend.mode = "pairs"
        assert self.backend.mode == "pairs"

    def test_mode_case_insensitive(self) -> None:
        self.backend.mode = "SINGLES"
        assert self.backend.mode == "singles"
        self.backend.mode = "Timestamp"
        assert self.backend.mode == "timestamp"

    # -- level --------------------------------------------------------------

    @staticmethod
    def _decode_line(raw) -> str:
        """Decode a serial readline result (bytes or str) uniformly."""
        return raw.decode(errors="replace").strip() if isinstance(raw, bytes) else str(raw).strip()

    def test_level_get_returns_data(self) -> None:
        """level getter returns response data (bytes or str, fw-dependent)."""
        level = self.backend.level
        decoded = self._decode_line(level)
        # Some firmware returns "TTL"/"NIM"; others return "0.599 POS" etc.
        assert len(decoded) > 0

    def test_level_set_ttl(self) -> None:
        self.backend.level = "TTL"
        # After setting TTL, the init-level tracking should reflect it
        assert self.backend._init_level == "TTL"

    def test_level_set_nim(self) -> None:
        self.backend.level = "NIM"
        assert self.backend._init_level == "NIM"

    def test_level_case_insensitive(self) -> None:
        self.backend.level = "ttl"
        assert self.backend._init_level == "TTL"
        self.backend.level = "nim"
        assert self.backend._init_level == "NIM"

    # -- threshold ----------------------------------------------------------

    def test_threshold_get_returns_data(self) -> None:
        """threshold getter delegates to self.level; returns fw data."""
        thresh = self.backend.threshold
        decoded = self._decode_line(thresh)
        assert len(decoded) > 0

    def test_threshold_set_positive(self) -> None:
        self.backend.threshold = 0.6
        assert self.backend._init_threshold == 0.6

    def test_threshold_set_negative(self) -> None:
        self.backend.threshold = -0.5
        assert self.backend._init_threshold == -0.5

    def test_set_threshold_method(self) -> None:
        """set_threshold(threshold, channel) should delegate to threshold setter."""
        self.backend.set_threshold(channel=1, threshold=0.7)
        assert self.backend._init_threshold == 0.7

    # -- integration time ---------------------------------------------------

    def test_int_time_get(self) -> None:
        t = self.backend.int_time
        assert isinstance(t, int)
        assert 0 < t <= 65535  # ms

    def test_int_time_set(self) -> None:
        self.backend.int_time = 0.5  # 500 ms
        assert self.backend.int_time == 500

    def test_int_time_seconds_helper(self) -> None:
        self.backend.int_time = 1.0
        s = self.backend._int_time_seconds()
        assert s == pytest.approx(1.0, abs=0.01)

    # -- clock --------------------------------------------------------------

    def test_clock_get_returns_data(self) -> None:
        clk = self.backend.clock
        decoded = self._decode_line(clk)
        assert len(decoded) > 0

    def test_clock_set_roundtrip(self) -> None:
        original = self._decode_line(self.backend.clock)
        # Try setting INT — the device should accept it
        self.backend.clock = "INT"
        current = self._decode_line(self.backend.clock)
        # Response varies per firmware: "INT", "EXT", "0", etc.
        assert len(current) > 0
        # Restore original value
        self.backend.clock = original

    # -- eclock (external clock) --------------------------------------------

    def test_eclock_get_returns_data(self) -> None:
        eclk = self.backend.eclock
        decoded = self._decode_line(eclk)
        assert len(decoded) > 0

    # -- help ---------------------------------------------------------------

    def test_help(self) -> None:
        lines = self.backend.help()
        assert isinstance(lines, list)
        assert len(lines) > 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Data acquisition (requires hardware)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.hardware
class TestDataAcquisition:
    """Singles, timestamps, g2 — real hardware."""

    @pytest.fixture(autouse=True)
    def _backend(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found")
        self.backend = ExpS15TDC1Backend()
        self.backend.connect(devices[0].device_path, mode="singles", level="NIM")

    def teardown_method(self) -> None:
        if hasattr(self, "backend") and self.backend.is_connected():
            self.backend.disconnect()

    # -- singles ------------------------------------------------------------

    def test_get_singles_returns_correct_type(self) -> None:
        result = self.backend.get_singles(integration_time=0.1)
        assert isinstance(result, SinglesResult)
        assert result.integration_time == pytest.approx(0.1, abs=0.01)
        assert len(result.counts) == CHANNEL_COUNT
        assert len(result.count_rates) == CHANNEL_COUNT
        assert result.counts.dtype == np.uint64
        assert result.count_rates.dtype == np.float64

    def test_get_singles_counts_are_non_negative(self) -> None:
        result = self.backend.get_singles(integration_time=0.1)
        assert (result.counts >= 0).all()

    def test_get_singles_count_rates_match(self) -> None:
        result = self.backend.get_singles(integration_time=0.2)
        expected_rates = result.counts.astype(np.float64) / result.integration_time
        np.testing.assert_allclose(result.count_rates, expected_rates)

    def test_get_singles_total_counts(self) -> None:
        result = self.backend.get_singles(integration_time=0.1)
        assert result.total_counts == int(np.sum(result.counts))

    def test_get_singles_repr(self) -> None:
        result = self.backend.get_singles(integration_time=0.1)
        r = repr(result)
        assert "SinglesResult" in r

    # -- timestamps ---------------------------------------------------------

    def test_get_timestamps_returns_correct_type(self) -> None:
        result = self.backend.get_timestamps(duration=0.1)
        assert isinstance(result, TimestampResult)
        assert result.resolution_ps == RESOLUTION_PS
        assert result.timestamps.dtype == np.int64
        assert result.channels.dtype == np.uint8
        assert result.total_events == len(result.timestamps)
        assert len(result.timestamps) == len(result.channels)

    def test_get_timestamps_total_time_ns(self) -> None:
        result = self.backend.get_timestamps(duration=0.5)
        assert result.total_time_ns > 0
        assert result.duration_s == pytest.approx(result.total_time_ns * 1e-9)

    def test_get_timestamps_repr(self) -> None:
        result = self.backend.get_timestamps(duration=0.1)
        r = repr(result)
        assert "TimestampResult" in r

    def test_get_timestamps_channels_in_range(self) -> None:
        """Channel indices should be 1..CHANNEL_COUNT (1-based)."""
        result = self.backend.get_timestamps(duration=0.1)
        if result.total_events > 0:
            assert result.channels.min() >= 1
            assert result.channels.max() <= CHANNEL_COUNT

    def test_get_timestamps_monotonic(self) -> None:
        """Timestamps should be strictly non-decreasing."""
        result = self.backend.get_timestamps(duration=0.1)
        if result.total_events > 1:
            assert (np.diff(result.timestamps) >= 0).all(), "Timestamps are not monotonic"

    # -- counts & coincidences ----------------------------------------------

    def test_get_counts_and_coincidences(self) -> None:
        self.backend.mode = "pairs"
        tup = self.backend.get_counts_and_coincidences(integration_time=0.1)
        assert isinstance(tup, tuple)
        assert len(tup) > 0
        for val in tup:
            assert isinstance(val, int)
            assert val >= 0

    # -- g2 -----------------------------------------------------------------

    def test_compute_g2_returns_correct_type(self) -> None:
        result = self.backend.get_g2(duration=0.1, bins=100)
        assert isinstance(result, G2Result)
        assert len(result.histogram) == 100
        assert len(result.bin_edges) == 101
        assert result.histogram.dtype == np.uint64
        assert result.resolution_ps == RESOLUTION_PS

    def test_compute_g2_bin_edges_linear(self) -> None:
        result = self.backend.get_g2(duration=0.1, bins=50, bin_offset=10)
        diffs = np.diff(result.bin_edges)
        # Should be uniform (resolution_ps steps)
        assert np.allclose(diffs, diffs[0])

    def test_compute_g2_histogram_non_negative(self) -> None:
        result = self.backend.get_g2(duration=0.1, bins=100)
        assert (result.histogram >= 0).all()

    def test_compute_g2_with_delay(self) -> None:
        result = self.backend.get_g2(
            duration=0.1, bins=100, ch_stop_delay=5, unit="ns"
        )
        assert isinstance(result, G2Result)

    def test_compute_g2_empty_no_crash(self) -> None:
        """Even with no events, compute_g2 should return a valid (empty) G2Result."""
        # Use a very short acquisition to minimise event count
        result = self.backend.get_g2(duration=0.02, bins=10)
        assert isinstance(result, G2Result)
        assert len(result.histogram) == 10

    def test_compute_g2_invalid_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported unit"):
            self.backend.get_g2(duration=0.1, unit="seconds")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Error paths (requires hardware)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.hardware
class TestErrorPaths:
    """Operations on a disconnected backend should raise."""

    def test_get_singles_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            backend.get_singles(integration_time=0.1)

    def test_get_timestamps_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            backend.get_timestamps(duration=0.1)

    def test_compute_g2_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            backend.get_g2(duration=0.1)

    def test_set_threshold_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            backend.set_threshold(channel=1, threshold=0.5)

    def test_mode_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = backend.mode

    def test_int_time_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = backend.int_time

    def test_level_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = backend.level

    def test_clock_requires_connection(self) -> None:
        backend = ExpS15TDC1Backend()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = backend.clock


# ═══════════════════════════════════════════════════════════════════════════
# 7. Context manager protocol
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.hardware
class TestContextManager:
    def test_context_manager_disconnects(self) -> None:
        devices = ExpS15TDC1Backend.discover_devices()
        if not devices:
            pytest.skip("No TDC1 device found")
        backend = ExpS15TDC1Backend()
        backend.connect(devices[0].device_path)
        assert backend.is_connected()
        with backend as b:
            assert b.is_connected()
        assert not backend.is_connected()
