"""Direct-serial experimental backend for the S-Fifteen TDC1."""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import replace
from struct import unpack
from typing import List, Optional, Tuple

import numpy as np
import serial

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.backends.s15_common import decode_pattern_channels
from qtools.tdc.connection import register_backend
from qtools.tdc.data import CoincidenceResult, DeviceInfo, SinglesResult, TimestampResult

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration constants
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_BAUD_RATE = 115200
CHANNEL_COUNT = 4
RESOLUTION_PS = 2000.0  # 2 ns resolution
USB_SERIAL_PATTERNS = ["TDC1", "FT232"]
# After the first response bytes arrive, read the full line under this short
# timeout instead of the acquisition-time long timeout.  The count line can
# straddle several USB frames, so blocking for the whole integration window
# makes readline() time out mid-line on the first acquisition.
_COUNTS_READ_TIMEOUT = 0.5
DEVICE_IDENTIFIER = "TDC1"
TTL_LEVEL = "TTL"
NIM_LEVEL = "NIM"

# ═══════════════════════════════════════════════════════════════════════════════
# Device discovery
# ═══════════════════════════════════════════════════════════════════════════════

def find_tdc1_devices() -> List[DeviceInfo]:
    """Scan and find S-Fifteen TDC1 devices on Linux, macOS, and Windows.

    Uses active probe (like powermeter's list_devices): opens each serial
    port, sends ``*IDN?``, and checks for a TDC response.  Falls back to
    ``/dev/serial/by-id/`` on Linux and ``/dev/cu.*`` globs on macOS.
    """
    devices: List[DeviceInfo] = []

    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for port in ports:
            desc = port.description or ""
            mfg = port.manufacturer or ""
            sn = port.serial_number or ""
            dev_path = port.device or ""

            # Skip known non-TDC ports (Thorlabs motors, etc.)
            if getattr(port, "vid", None) == 0x0403 and getattr(port, "pid", None) == 0xFAF0:
                continue
            if any(k in desc.lower() or k in mfg.lower()
                   for k in ["k10cr1", "thorlabs", "apt", "bluetooth", "bt-ecu", "wireless"]):
                continue

            # Active probe: open port and send *IDN? to verify it's an S15 TDC
            matched = False
            try:
                ser = serial.Serial(dev_path, baudrate=115200, timeout=0.15)
                ser.write(b"*IDN?\n")
                resp = ser.readline().decode("ascii", errors="ignore").strip()
                ser.close()
                if "TDC" in resp.upper():
                    matched = True
            except Exception:
                pass

            if matched:
                devices.append(
                    DeviceInfo(
                        backend_name="s15_tdc1",
                        device_path=dev_path,
                        serial_number=sn or None,
                        description=f"{desc} ({mfg})" if desc else "S-Fifteen TDC1 Device",
                    )
                )

    except ImportError:
        logger.warning("pyserial is not installed; cannot perform dynamic serial port discovery")

    # Fallback to standard path matching if no devices were found via pyserial
    system = platform.system()
    import pathlib

    if not devices and system == "Linux":
        try:
            paths = list(pathlib.Path("/dev/serial/by-id/").glob("*TDC1*"))
            for path in paths:
                devices.append(
                    DeviceInfo(
                        backend_name="s15_tdc1",
                        device_path=str(path.resolve()),
                        serial_number=path.name,
                        description="S-Fifteen TDC1 (by-id fallback)",
                    )
                )
        except Exception:
            pass

    if not devices and system == "Darwin":
        try:
            for pattern in ["*usbserial*", "*USBtoUART*", "*usbmodem*"]:
                for path in pathlib.Path("/dev/").glob(f"cu.{pattern}"):
                    devices.append(
                        DeviceInfo(
                            backend_name="s15_tdc1",
                            device_path=str(path),
                            serial_number=path.name,
                            description="S-Fifteen TDC1 (macOS fallback)",
                        )
                    )
        except Exception:
            pass

    return devices


@register_backend("exp_s15_tdc1")
class ExpS15TDC1Backend(TDCBackend):
    """TDC1 backend that directly implements the TimestampTDC1 serial protocol."""

    def __init__(self, device_path: Optional[str] = None) -> None:
        self._device_path = device_path
        self._com = None
        self._connected = False
        self._extra_terminator_patched = False
        self._init_mode = "singles"
        self._init_level = TTL_LEVEL
        self._init_integration_time = 1.0
        self._init_threshold = 0.6
        self.accumulate_timestamps = False
        self.accumulated_timestamps_filename = "timestamps.raw"

    @property
    def name(self) -> str:
        return "exp_s15_tdc1"

    @property
    def vendor(self) -> str:
        return "S-Fifteen Instruments"

    @property
    def channel_count(self) -> int:
        return CHANNEL_COUNT

    @property
    def capabilities(self) -> BackendCapability:
        return (
            BackendCapability.SINGLES
            | BackendCapability.TIMESTAMPS
            | BackendCapability.HIST_SOFTWARE
            | BackendCapability.COINCIDENCE
            | BackendCapability.COINCIDENCE_SOFTWARE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return RESOLUTION_PS

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        target_path = device_path or self._device_path
        if not target_path:
            devices = self.discover_devices()
            if not devices:
                raise ConnectionError("No S-Fifteen TDC1 devices found.")
            target_path = devices[0].device_path

        try:
            self._device_path = target_path
            self._extra_terminator_patched = False
            # Defaults come from __init__; on reconnect, keep the previous
            # settings unless the caller explicitly overrides them.
            self._init_mode = str(kwargs.get("mode", self._init_mode))
            self._init_level = str(kwargs.get("level", self._init_level))
            self._init_integration_time = float(
                kwargs.get("integration_time", self._init_integration_time)
            )
            self._init_threshold = float(
                kwargs.get("threshold", self._init_threshold)
            )

            self.accumulate_timestamps = False
            self.accumulated_timestamps_filename = kwargs.get("tmpfile", "timestamps.raw")

            self._com = serial.Serial(target_path, timeout=0.01)
            self._com.write(b"\r\n")
            self._com.readlines()

            self._apply_connection_settings()
            time.sleep(0.2)

            self._com.write(b"abort\r\n")
            self._com.readlines()

            # Some TDC1 units need doubled terminators; if already in a bad
            # state at connect time, patch immediately and re-send config.
            # if self._ensure_extra_terminator_patch():
            #     self._apply_connection_settings()
            #     self._com.write(b"abort\r\n")
            #     self._com.readlines()

            # Mirror stable backend: discard init/configure chatter.
            self._com.reset_input_buffer()
            self._connected = True
        except Exception as exc:
            connection = self._com
            self._com = None
            self._connected = False
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise ConnectionError(
                f"Failed to connect to experimental S15 TDC1 at {target_path}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        connection = self._com
        self._com = None
        self._connected = False
        if connection is None:
            return
        try:
            # Stop any active timestamp stream before closing the port.
            try:
                connection.write(b"abort\r\n")
                connection.readlines()
            except Exception:
                pass
            connection.reset_input_buffer()
            connection.reset_output_buffer()
            connection.close()
        except Exception as exc:
            logger.warning("Error while closing experimental S15 TDC1: %s", exc)

    def is_connected(self) -> bool:
        return self._connected

    def _flush_serial_buffers(self) -> None:
        """Discard pending RX/TX bytes on the open serial port."""
        connection = self._require_connection()
        connection.reset_input_buffer()
        connection.reset_output_buffer()

    def _apply_connection_settings(self) -> None:
        """Apply the last requested mode/level/time/threshold to the device."""
        self.mode = self._init_mode
        self.level = self._init_level
        self.int_time = self._init_integration_time
        self.threshold = self._init_threshold

    # def _ensure_extra_terminator_patch(self) -> bool:
    #     """Detect firmware double-terminator bug and patch writes if needed.

    #     Returns:
    #         True if the patch was newly applied during this call.
    #     """
    #     if self._extra_terminator_patched or self._com is None:
    #         return False
    #     try:
    #         # Reading mode exercises a simple query. On affected firmware,
    #         # a single terminator yields an empty reply and int("") fails.
    #         _ = self.mode
    #         return False
    #     except (ValueError, serial.SerialException):
    #         self._apply_extra_terminator_patch()
    #         return True

    # def _apply_extra_terminator_patch(self) -> None:
    #     pass
    #     # """Monkey-patch serial write to insert extra terminators (TDC1-0049)."""
    #     # if self._extra_terminator_patched or self._com is None:
    #     #     return

    #     # self._com._write = self._com.write

    #     # def write(connection, message: bytes, *args, **kwargs):
    #     #     message = b";;".join(message.split(b";"))
    #     #     message = b"\n\r\n".join(message.split(b"\n"))
    #     #     return connection._write(message, *args, **kwargs)

    #     # self._com.write = types.MethodType(write, self._com)
    #     # self._extra_terminator_patched = True
    #     # self._com.write(b"abort\r\n")
    #     # self._com.readlines()
    #     # logger.info(
    #     #     "Applied extra-terminator serial write patch for experimental S15 TDC1"
    #     # )


    @property
    def int_time(self):
        """Integration time reported by the device, in milliseconds.

        Note:
            The device protocol uses milliseconds. The setter accepts seconds
            (S15lib-compatible). Prefer :meth:`_int_time_seconds` for timeouts.
        """
        connection = self._require_connection()
        connection.write(b"time?\r\n")
        integration_time = int(connection.readline())
        return integration_time if integration_time >= 0 else integration_time + (1 << 16)

    @int_time.setter
    def int_time(self, value: float):
        """Set integration time.

        Args:
            value: Integration time in **seconds** (converted to ms on the wire).
        """
        connection = self._require_connection()
        self._init_integration_time = float(value)
        value_ms = float(value) * 1000
        if value_ms < 1:
            print("Invalid integration time.")
        elif value_ms > 65535:
            print("Integration time cannot exceed 65535 ms in counter/coincidence mode")
        else:
            connection.write(f"time {int(value_ms):d};".encode())
            connection.readlines()

    def _int_time_seconds(self) -> float:
        """Return the device integration time converted to seconds."""
        return self.int_time / 1000.0

    @property
    def mode(self):
        connection = self._require_connection()
        connection.write(b"mode?\r\n")
        mode = int(connection.readline())
        return {0: "singles", 1: "pairs", 3: "timestamp"}.get(mode)

    @mode.setter
    def mode(self, value):
        value = value.lower()
        if value in {"singles", "pairs", "timestamp"}:
            self._init_mode = value
            self.write_only(value)

    def write_only(self, command: str) -> None:
        connection = self._require_connection()
        connection.write((command + "\r\n").encode())
        connection.readlines()
        time.sleep(0.1)

    @property
    def level(self):
        connection = self._require_connection()
        connection.write(b"level?\r\n")
        return connection.readline()

    @level.setter
    def level(self, value: str):
        if value.lower() == "nim":
            self._init_level = "NIM"
            self.write_only("NIM")
        elif value.lower() == "ttl":
            self._init_level = "TTL"
            self.write_only("TTL")
        else:
            print("Accepted input is a string and either 'TTL' or 'NIM'")

    @property
    def threshold(self):
        return self.level

    @threshold.setter
    def threshold(self, value: float):
        self._init_threshold = float(value)
        self.write_only(f"NEG {value}" if value < 0 else f"POS {value}")

    @property
    def clock(self) -> str:
        connection = self._require_connection()
        connection.write(b"REFCLK?\r\n")
        return connection.readline()

    @clock.setter
    def clock(self, value: str):
        self.write_only(f"REFCLK {value}")

    @property
    def eclock(self) -> str:
        connection = self._require_connection()
        connection.write(b"ECLOCK?\r\n")
        return connection.readline()

    def _counts_from_response(self, command: bytes, duration_seconds: float) -> Tuple[int, ...]:
        """Run a text-protocol count command and parse the single-line response.

        Waits up to ``duration_seconds`` for the first response byte, then reads
        the rest of the line under a short timeout (the device emits the line in
        several USB frames, and ``readline()`` with the long acquisition timeout
        can time out mid-line on the first acquisition).  Parses the response as
        integer fields and validates the count before returning.

        Raises:
            serial.SerialTimeoutException: If no response arrives within the
                integration window.
            ValueError: If the response is not a valid line of integer counts.
        """
        connection = self._require_connection()
        connection.timeout = 0.05
        connection.write(command)

        start_time = time.time()
        while True:
            if connection.inWaiting() > 0:
                break
            if time.time() > start_time + duration_seconds + 0.1:
                raise serial.SerialTimeoutException("Command timeout")

        connection.timeout = _COUNTS_READ_TIMEOUT
        try:
            response = connection.readline()
        finally:
            connection.timeout = 0.05
        try:
            counts = tuple(int(value) for value in response.split())
        except ValueError as exc:
            raise ValueError(
                f"Invalid counts response from device: {response!r}"
            ) from exc
        # ``singles`` lines carry 4 fields; ``pairs`` lines carry 4 singles
        # plus 4 coincidence counts.  A truncated line fails this check and is
        # left to the caller's retry loop instead of being parsed as a valid
        # (partial) read.
        expected_fields = CHANNEL_COUNT if command.startswith(b"singles") else 2 * CHANNEL_COUNT
        if len(counts) != expected_fields:
            raise ValueError(
                f"Unexpected counts response from device: {response!r}"
            )
        return counts

    def _get_counts_raw(self, duration_seconds: Optional[float] = None) -> Tuple[int, ...]:
        if duration_seconds is None:
            # Device getter returns milliseconds; timeouts use seconds.
            duration_seconds = self._int_time_seconds()
        else:
            self.int_time = duration_seconds
        return self._counts_from_response(b"singles;counts?\r\n", duration_seconds)

    def get_singles(self, integration_time: float) -> SinglesResult:
        self._require_connected()
        counts = np.asarray(self._get_counts_raw(integration_time), dtype=np.uint64)
        # Mirror stable backend: isolate text-protocol residue from later binary I/O.
        self._flush_serial_buffers()
        return SinglesResult(
            integration_time=integration_time,
            counts=counts,
            count_rates=counts.astype(np.float64) / integration_time,
        )

    def get_counts_and_coincidences(self, integration_time: float = 1) -> Tuple[int, ...]:
        self._require_connected()
        self.int_time = integration_time
        return self._counts_from_response(b"pairs;counts?\r\n", integration_time)

    def _stream_response_into_buffer(
        self, command: str, acquisition_time: float
    ) -> Tuple[bytes, List[int]]:
        connection = self._require_connection()
        chunks = []
        chunk_lengths = []
        # Keep a minimum chunk size if timeout was left very small.
        effective_timeout = connection.timeout if connection.timeout and connection.timeout > 0 else 0.05
        chunk_size = max(int((1 << 22) * effective_timeout) * 4, 4096)
        start_time = time.time()
        connection.write((command + "\r\n").encode())

        while time.time() - start_time <= acquisition_time + 0.02:
            chunks.append(connection.read(chunk_size))
        chunk_lengths.extend(len(chunk) for chunk in chunks)

        connection.write(b"abort\r\n")
        connection.flush()
        buffer = b"".join(chunks)
        time.sleep(0.05)
        while connection.in_waiting:
            chunk = connection.read(connection.in_waiting)
            if chunk:
                buffer += chunk
                chunk_lengths.append(len(chunk))
        return buffer, list(filter(None, chunk_lengths))

    def _get_timestamps_raw(
        self, acquisition_time: float = 1, legacy: bool = True, highcount: bool = False
    ):
        connection = self._require_connection()
        while connection.in_waiting:
            connection.readlines()
        if self.mode != "timestamp":
            self.mode = "timestamp"
        if acquisition_time > 65.536:
            time_command = "time 0;"
        elif acquisition_time != self._int_time_seconds():
            time_command = f"time {int(acquisition_time * 1000):d};"
        else:
            time_command = ""
        command = "INPKT;" + time_command + "counts?;"
        buffer, chunk_lengths = self._stream_response_into_buffer(command, acquisition_time)
        if highcount:
            return self.read_timestamps_bin3(buffer, chunk_lengths, legacy=legacy)
        return self.read_timestamps_bin2(buffer, legacy=legacy)

    def get_timestamps(self, duration: float) -> TimestampResult:
        self._require_connected()
        # Mirror stable backend: drop any stale text bytes before binary stream.
        # struct.unpack requires exact 4-byte alignment.
        self._require_connection().reset_input_buffer()

        timestamps_ns, patterns = self._get_timestamps_raw(
            duration, legacy=True, highcount=False
        )

        # Firmware double-terminator bug often appears only after timestamp mode.
        # Detect/patch now so subsequent mode/time/threshold queries keep working.
        # if self._ensure_extra_terminator_patch():
        #     self._require_connection().reset_input_buffer()

        pattern_masks = np.asarray(
            [int(pattern, 2) if isinstance(pattern, str) else int(pattern) for pattern in patterns],
            dtype=np.uint8,
        )
        timestamps_ps = (np.asarray(timestamps_ns) * 1000).astype(np.int64)
        timestamps_ps, channels = decode_pattern_channels(
            timestamps_ps, pattern_masks, CHANNEL_COUNT
        )
        total_time_ns = duration * 1e9
        return TimestampResult(
            timestamps=timestamps_ps,
            channels=channels,
            resolution_ps=RESOLUTION_PS,
            total_time_ns=total_time_ns,
        )

    def read_timestamps_bin2(self, binary_stream, legacy=True):
        total = len(binary_stream) // 4
        if total == 0:
            empty_patterns = np.array([], dtype=str if legacy else np.int64)
            return np.array([], dtype=np.int64), empty_patterns
        uint_list = np.array(unpack(f"<{total}I", binary_stream[: total * 4]), dtype="int64")
        # Drop control words (bit 0x10 set); only the low 4 bits encode channels.
        # Mirrors the vendor reference decoder, which skips words with
        # (pattern & 0x10) != 0 so control/protocol bytes never become
        # phantom per-channel events.
        uint_list = uint_list[(uint_list & 0x10) == 0]
        if uint_list.size == 0:
            empty_patterns = np.array([], dtype=str if legacy else np.int64)
            return np.array([], dtype=np.int64), empty_patterns
        raw_timestamps = (uint_list >> 5) << 1
        rollover_indices = np.nonzero(np.diff(raw_timestamps) < (-1 << 25))[0]
        for index in rollover_indices:
            raw_timestamps[index + 1 :] += 1 << 28
        event_channels = uint_list & 0xF
        if legacy:
            event_channels = np.vectorize("{0:04b}".format)(event_channels)
        return raw_timestamps, event_channels

    def read_timestamps_bin3(
        self, buffer, chunk_lengths, min_time_step=1 << 25, legacy=False
    ):
        start = 0
        end = 0
        skip = 0
        raw_words = np.array([], dtype="int64")
        for chunk_length in chunk_lengths:
            end += chunk_length
            end_index = end - (end - start) % 4
            word_count = (end_index - start) // 4
            if word_count <= 0:
                start += chunk_length
                continue
            words = np.array(
                unpack(f"<{word_count}I", buffer[start - skip : end_index - skip])
            )
            differences = np.diff(words)
            negative_count = int(np.sum(differences < 0))
            while negative_count > 1:
                corrupt_index = int(np.argmax(np.abs(differences) > min_time_step)) + 1
                new_start = start + (corrupt_index + 2) * 4
                skip = 2 if skip == 0 else 0
                remaining = (end - new_start) // 4
                if remaining <= 0:
                    words = words[:corrupt_index]
                    break
                remaining_words = np.array(
                    unpack(f"<{remaining}I", buffer[new_start - skip : end - skip])
                )
                words = np.append(words[:corrupt_index], remaining_words)
                differences = np.diff(words)
                negative_count = int(np.sum(differences < 0))
            raw_words = np.append(raw_words, words)
            start += chunk_length

        # Drop control words (bit 0x10 set); only the low 4 bits encode channels.
        # Mirrors the vendor reference decoder, which skips words with
        # (pattern & 0x10) != 0 so control/protocol bytes never become
        # phantom per-channel events.
        raw_words = raw_words[(raw_words & 0x10) == 0]
        if raw_words.size == 0:
            empty_patterns = np.array([], dtype=str if legacy else np.int64)
            return np.array([], dtype=np.int64), empty_patterns
        raw_timestamps = (raw_words >> 5) << 1
        rollover_indices = np.nonzero(np.diff(raw_timestamps) < (-1 << 25))[0]
        for index in rollover_indices:
            raw_timestamps[index + 1 :] += 1 << 28
        event_channels = raw_words & 0xF
        if legacy:
            event_channels = np.vectorize("{0:04b}".format)(event_channels)
        return raw_timestamps, event_channels

    def read_timestamps_bin(self, binary_stream, legacy=True):
        bytes_hex = binary_stream[::-1].hex()
        words = [
            int(bytes_hex[index : index + 8], 16)
            for index in range(0, len(bytes_hex), 8)
        ][::-1]
        timestamps = []
        channels = []
        period_count = 0
        previous_timestamp = -1
        for word in words:
            timestamp = word >> 5
            pattern = word & 0x1F
            if previous_timestamp != -1 and timestamp < previous_timestamp:
                period_count += 1
            previous_timestamp = timestamp
            if pattern & 0x10 == 0:
                timestamps.append(timestamp + (1 << 27) * period_count)
                channels.append(f"{pattern & 0xF:04b}" if legacy else pattern & 0xF)
        timestamps = np.asarray(timestamps, dtype="int64") * 2
        if not legacy:
            channels = np.asarray(channels)
        return timestamps, channels

    def get_coincidence(
        self,
        duration: float,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        unit: str = "ns",
        window_start: int | float | None = None,
        window_stop: int | float | None = None,
        method: str = "software",
    ) -> CoincidenceResult:
        """Use TDC1's fixed ``pairs`` counter for hardware coincidence."""
        if method != "hardware":
            return super().get_coincidence(
                duration=duration,
                ch_start=ch_start,
                ch_stop=ch_stop,
                ch_stop_delay=ch_stop_delay,
                unit=unit,
                window_start=window_start,
                window_stop=window_stop,
                method=method,
            )
        if duration <= 0:
            raise ValueError("duration must be positive")
        if (ch_start, ch_stop) not in {(1, 3), (1, 4), (2, 3), (2, 4)}:
            raise ValueError(
                "TDC1 hardware pairs supports channel pairs (1,3), (1,4), "
                "(2,3), and (2,4) only"
            )
        if ch_stop_delay != 0:
            raise ValueError("TDC1 hardware pairs has no configurable channel delay")
        if window_start is not None or window_stop is not None:
            raise ValueError("TDC1 hardware pairs uses the device's fixed coincidence gate")
        if not self._connected or self._com is None:
            raise RuntimeError("Device not connected")

        values = tuple(self.get_counts_and_coincidences(duration))
        if len(values) < 8:
            raise RuntimeError(f"TDC1 pairs response has {len(values)} fields; expected at least 8")
        pair_index = {(1, 3): 4, (1, 4): 5, (2, 3): 6, (2, 4): 7}[(ch_start, ch_stop)]
        counts = np.asarray(values[:4], dtype=np.float64)
        return CoincidenceResult(
            count=int(values[pair_index]),
            acc_count_perbin=None,
            accidental_count=None,
            channel1_rate=float(counts[ch_start - 1] / duration),
            channel2_rate=float(counts[ch_stop - 1] / duration),
            integration_time=duration,
            order=2,
            accidental_method=None,
            method="hardware",
        )

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        self._require_connected()
        self.threshold = float(threshold)
        # Threshold writes can leave residual text protocol bytes.
        self._require_connection().reset_input_buffer()

    def help(self):
        connection = self._require_connection()
        connection.write(b"help\r\n")
        return connection.readlines()

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        return [
            replace(device, backend_name="exp_s15_tdc1")
            for device in find_tdc1_devices()
        ]

    def _require_connection(self):
        if self._com is None:
            raise RuntimeError("Device not connected")
        return self._com

    def _require_connected(self) -> None:
        if not self._connected or self._com is None:
            raise RuntimeError("Device not connected")
