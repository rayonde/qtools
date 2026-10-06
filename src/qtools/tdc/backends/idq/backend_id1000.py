"""IDQ ID1000 Time Controller TDC Backend implementation.

Connects to the ID Quantique ID1000 via Gigabit Ethernet (TCP socket over ZeroMQ).
Features:
- Sub-picosecond precision: 1 ps resolution in High Resolution (HIRES) mode.
- 5 input channels: START, INPUT 1, INPUT 2, INPUT 3, INPUT 4.
- Hardware-accelerated singles, multi-fold coincidence, and start-stop histograms.
- Support for DLT (DataLinkTargetService) for high-rate timestamp recording.
- Safe local network device discovery without invasive subnet sweeping.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from qtools.tdc.backends.base import BackendCapability, TDCBackend
from qtools.tdc.connection import register_backend
from qtools.tdc.data import (
    CoincidenceResult,
    DeviceInfo,
    G2Result,
    SinglesResult,
    TimestampResult,
)

logger = logging.getLogger(__name__)

# Try importing pyzmq
try:
    import zmq
    ZMQ_AVAILABLE = True
except ImportError:
    ZMQ_AVAILABLE = False


# Channel to SCPI block names
_INPUT_BLOCK_MAP: Dict[int, str] = {
    0: "STARt",
    1: "INPU1",
    2: "INPU2",
    3: "INPU3",
    4: "INPU4",
    5: "STARt",
}

# 2-fold coincidence block mapping (from ID1000 default config COUNT)
_COINC_BLOCK_MAP: Dict[Tuple[int, int], str] = {
    (1, 2): "TSCO6",
    (2, 1): "TSCO6",
    (1, 3): "TSCO7",
    (3, 1): "TSCO7",
    (1, 4): "TSCO8",
    (4, 1): "TSCO8",
    (2, 3): "TSCO3",
    (3, 2): "TSCO3",
    (2, 4): "TSCO4",
    (4, 2): "TSCO4",
    (3, 4): "TSCO5",
    (4, 3): "TSCO5",
}


@register_backend("idq_id1000")
@register_backend("id1000")
class ID1000Backend(TDCBackend):
    """Backend implementation for IDQ ID1000 Time Controller TDC.
    
    Communicates via Ethernet (ZeroMQ REQ socket on port 5555).
    """

    DEFAULT_PORT = 5555
    DEFAULT_DLT_PORT = 6060
    DEFAULT_IP = "169.254.99.100"

    def __init__(self, device_path: Optional[str] = None, **kwargs) -> None:
        self._device_path = device_path
        self._host = ""
        self._port = self.DEFAULT_PORT
        self._dlt_host = kwargs.get("dlt_host", "127.0.0.1")
        self._dlt_port = kwargs.get("dlt_port", self.DEFAULT_DLT_PORT)
        
        self._zmq_ctx: Optional[Any] = None
        self._tc_sock: Optional[Any] = None
        self._connected = False
        self._resolution_ps = 1.0  # Default 1 ps for ID1000 in HIRES mode
        self._is_hires = True

    @property
    def name(self) -> str:
        return "id1000"

    @property
    def vendor(self) -> str:
        return "IDQ (ID Quantique)"

    @property
    def channel_count(self) -> int:
        # Channels 1-4 correspond to INPUT 1-4; Channel 5 (or 0) corresponds to START
        return 5

    @property
    def capabilities(self) -> BackendCapability:
        return (
            BackendCapability.SINGLES
            | BackendCapability.TIMESTAMPS
            | BackendCapability.HIST_HARDWARE
            | BackendCapability.HIST_SOFTWARE
            | BackendCapability.COINCIDENCE
            | BackendCapability.COINCIDENCE_SOFTWARE
            | BackendCapability.THRESHOLD_CONTROL
        )

    @property
    def resolution_ps(self) -> float:
        return self._resolution_ps

    def _parse_address(self, device_path: Optional[str]) -> Tuple[str, int]:
        addr = device_path or self._device_path or os.environ.get("ID1000_IP")
        if not addr:
            discovered = self.discover_devices()
            if discovered:
                addr = discovered[0].device_path
            else:
                addr = self.DEFAULT_IP

        # Format: tcp://169.254.99.100:5555 or 169.254.99.100:5555 or 169.254.99.100
        addr = addr.replace("tcp://", "")
        if ":" in addr:
            host, port_str = addr.split(":", 1)
            port = int(port_str)
        else:
            host = addr
            port = self.DEFAULT_PORT

        return host.strip(), port

    def connect(self, device_path: str = None, **kwargs) -> None:
        if self._connected:
            return

        if not ZMQ_AVAILABLE:
            raise ImportError(
                "pyzmq is required for ID1000 backend communication. "
                "Install it using `pip install pyzmq`."
            )

        host, port = self._parse_address(device_path)
        self._host = host
        self._port = port
        self._device_path = f"tcp://{host}:{port}"
        timeout_s = kwargs.get("timeout_s", 2.0)
        hires = kwargs.get("hires", True)

        logger.info("Connecting to IDQ ID1000 at %s:%d...", host, port)

        # 1. Pre-check TCP socket reachability to avoid zmq hanging indefinitely
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout_s)
            s.connect((host, port))
            s.close()
        except (socket.error, socket.timeout) as exc:
            raise ConnectionError(
                f"Cannot reach IDQ ID1000 at '{host}:{port}'. "
                "Ensure Ethernet cable is connected and IP is correct."
            ) from exc

        # 2. Setup ZeroMQ REQ Socket
        try:
            self._zmq_ctx = zmq.Context()
            self._tc_sock = self._zmq_ctx.socket(zmq.REQ)
            self._tc_sock.setsockopt(zmq.RCVTIMEO, int(timeout_s * 1000))
            self._tc_sock.setsockopt(zmq.SNDTIMEO, int(timeout_s * 1000))
            self._tc_sock.connect(f"tcp://{host}:{port}")

            # 3. Handshake and query device
            dev_id = self.exec_scpi("*IDN?")
            logger.info("Connected to IDQ ID1000: %s", dev_id.strip())

            # 4. Set resolution mode
            mode_cmd = "HIRES" if hires else "LOWRES"
            self.exec_scpi(f"DEVIce:RESolution {mode_cmd}")
            self._is_hires = hires

            # 5. Query resolution timebase (ps)
            try:
                bwid_str = self.exec_scpi("DEVI:RES:BWID?").strip()
                self._resolution_ps = float(bwid_str)
                logger.info("ID1000 Time Resolution: %.2f ps", self._resolution_ps)
            except Exception as e:
                logger.warning("Could not read resolution, defaulting to 1.0 ps: %s", e)
                self._resolution_ps = 1.0 if hires else 100.0

            self._connected = True
        except Exception as e:
            self.disconnect()
            raise ConnectionError(f"Failed to initialize ID1000 communication: {e}") from e

    def disconnect(self) -> None:
        if self._tc_sock is not None:
            try:
                self._tc_sock.close(linger=0)
            except Exception:
                pass
            self._tc_sock = None

        if self._zmq_ctx is not None:
            try:
                self._zmq_ctx.term()
            except Exception:
                pass
            self._zmq_ctx = None

        self._connected = False
        logger.info("Disconnected from IDQ ID1000")

    def is_connected(self) -> bool:
        return self._connected and self._tc_sock is not None

    def exec_scpi(self, cmd: str) -> str:
        """Send a SCPI text command to the ID1000 and return the response."""
        if self._tc_sock is None:
            raise RuntimeError("ID1000 is not connected.")

        try:
            self._tc_sock.send_string(cmd)
            ans = self._tc_sock.recv().decode("utf-8")
            return ans
        except Exception as e:
            raise RuntimeError(f"SCPI command execution failed for '{cmd}': {e}") from e

    def set_threshold(self, threshold: float, channel: int | None = None) -> None:
        """Set input comparator threshold voltage.
        
        Args:
            threshold: Voltage threshold in Volts (e.g. -0.4).
            channel: Channel index (1..4 for Inputs 1..4, 5 or 0 for Start, None for all).
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        channels_to_set = range(1, self.channel_count + 1) if channel is None else [channel]
        for ch in channels_to_set:
            if ch not in _INPUT_BLOCK_MAP:
                raise ValueError(f"Invalid channel index: {ch}")
            block = _INPUT_BLOCK_MAP[ch]
            self.exec_scpi(
                f"{block}:ENAB ON;THRE {threshold:g}V;COUP DC;SELE UNSHAPED"
            )

    def set_edge(self, channel: int | None = None, edge: str = "RISING") -> None:
        """Set channel trigger edge polarity ('RISING' or 'FALLING')."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        edge_val = edge.upper()
        if edge_val not in ("RISING", "FALLING"):
            raise ValueError(f"Invalid edge: {edge!r}. Expected 'RISING' or 'FALLING'.")
        channels_to_set = range(1, self.channel_count + 1) if channel is None else [channel]
        for ch in channels_to_set:
            if ch not in _INPUT_BLOCK_MAP:
                raise ValueError(f"Invalid channel index: {ch}")
            block = _INPUT_BLOCK_MAP[ch]
            self.exec_scpi(f"{block}:EDGE {edge_val}")

    def get_singles(self, integration_time: float) -> SinglesResult:
        """Measure singles count rate for all channels.
        
        Args:
            integration_time: Exposure duration in seconds.
            
        Returns:
            SinglesResult containing counts and count rates for channels 1..4 and Start.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        if integration_time <= 0:
            raise ValueError("integration_time must be positive")

        exp_ns = max(int(integration_time * 1e9), 1)

        # Configure all 4 input channels and START channel counters
        setup_cmds = [
            f"INPU{i}:COUN:MODE CYCL;INTE {exp_ns};RESEt" for i in range(1, 5)
        ] + [f"STARt:COUN:MODE CYCL;INTE {exp_ns};RESEt"]
        self.exec_scpi(";".join(setup_cmds))

        # Sleep integration duration
        time.sleep(integration_time)

        # Read counters in a single batch
        query = ";:".join([f"INPU{i}:COUNter?" for i in range(1, 5)] + ["STARt:COUNter?"])
        ans = self.exec_scpi(query)

        raw_counts = [int(line.strip()) for line in ans.splitlines() if line.strip()]
        if len(raw_counts) < 5:
            # Fallback per-channel query if batch returned truncated lines
            raw_counts = []
            for i in range(1, 5):
                raw_counts.append(int(self.exec_scpi(f"INPU{i}:COUN?").strip()))
            raw_counts.append(int(self.exec_scpi("STARt:COUN?").strip()))

        counts = np.array(raw_counts[:5], dtype=np.uint64)
        count_rates = counts.astype(np.float64) / integration_time

        return SinglesResult(
            integration_time=integration_time,
            counts=counts,
            count_rates=count_rates,
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
        method: str = "hardware",
    ) -> CoincidenceResult:
        """Measure coincidence counts using hardware TSCO blocks or software analysis."""
        if method == "software":
            return super().get_coincidence(
                duration=duration,
                ch_start=ch_start,
                ch_stop=ch_stop,
                ch_stop_delay=ch_stop_delay,
                unit=unit,
                window_start=window_start,
                window_stop=window_stop,
                method="software",
            )

        if method != "hardware":
            raise ValueError(f"Unsupported coincidence method: {method!r}")

        if not self.is_connected():
            raise RuntimeError("Device not connected")

        unit_to_ps = {"ps": 1.0, "ns": 1e3, "ms": 1e6}
        if unit not in unit_to_ps:
            raise ValueError(f"Unsupported unit: {unit!r}")

        pair = (ch_start, ch_stop)
        if pair not in _COINC_BLOCK_MAP:
            raise ValueError(
                f"Hardware 2-fold coincidence is directly available for input channel pairs "
                f"1..4 (e.g. (1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4)). Got {pair}."
            )
        tsco_block = _COINC_BLOCK_MAP[pair]

        # Calculate coincidence window
        if window_start is not None and window_stop is not None:
            window_ps = int(round((float(window_stop) - float(window_start)) * unit_to_ps[unit]))
            window_start_ps = float(window_start) * unit_to_ps[unit]
            window_stop_ps = float(window_stop) * unit_to_ps[unit]
        else:
            window_ps = 10000  # Default 10 ns coincidence window
            window_start_ps = 0.0
            window_stop_ps = float(window_ps)

        if window_ps <= 0:
            raise ValueError(f"Window must be positive, got {window_ps} ps")

        # Load predefined coincidence configuration in hardware
        self.exec_scpi("DEVI:CONFI:LOAD COUNT")

        # Setup delays and window for the coincidence combiners
        self.exec_scpi(f"DELA6:VALU {window_ps * 1}")
        self.exec_scpi(f"DELA7:VALU {window_ps * 2}")
        self.exec_scpi(f"DELA8:VALU {window_ps * 3}")

        # Setup coincidence block window
        self.exec_scpi(f"{tsco_block}:WIND:BEGI:DELA 0")
        self.exec_scpi(f"{tsco_block}:WIND:END:DELA {window_ps}")

        exp_ns = max(int(duration * 1e9), 1)
        self.exec_scpi(f"{tsco_block}:COUN:MODE CYCL;INTE {exp_ns};RESEt")
        self.exec_scpi(f"INPU{ch_start}:COUN:MODE CYCL;INTE {exp_ns};RESEt")
        self.exec_scpi(f"INPU{ch_stop}:COUN:MODE CYCL;INTE {exp_ns};RESEt")

        # Wait duration
        time.sleep(duration)

        # Read counts
        coinc_count = int(self.exec_scpi(f"{tsco_block}:COUNter?").strip())
        rate1 = float(self.exec_scpi(f"INPU{ch_start}:COUNter?").strip()) / duration
        rate2 = float(self.exec_scpi(f"INPU{ch_stop}:COUNter?").strip()) / duration

        # Accidental coincidence background estimate
        accidental_count = int(round(rate1 * rate2 * (window_ps * 1e-12) * duration))
        acc_per_bin = accidental_count / max(1, window_ps)

        return CoincidenceResult(
            count=coinc_count,
            acc_count_perbin=acc_per_bin,
            accidental_count=accidental_count,
            channel1_rate=rate1,
            channel2_rate=rate2,
            integration_time=duration,
            order=2,
            window_ps=window_ps,
            window_start_ps=window_start_ps,
            window_stop_ps=window_stop_ps,
            accidental_method="poisson_rate",
            method="hardware",
        )

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
    ) -> G2Result:
        """Compute the g2 correlation histogram.
        
        Software g2 delegates to tdc.analysis.g2 via get_timestamps().
        For ID1000 onboard hardware Start-Stop histograms (HIST1-HIST4),
        use `get_hardware_histogram()`.
        """
        if method == "hardware":
            raise NotImplementedError(
                f"Backend '{self.name}' does not implement hardware g2 via get_g2(). "
                "Use `get_hardware_histogram()` for ID1000 onboard histogram modules."
            )
        return super().get_g2(
            duration=duration,
            bins=bins,
            ch_start=ch_start,
            ch_stop=ch_stop,
            ch_stop_delay=ch_stop_delay,
            bin_offset=bin_offset,
            unit=unit,
            method=method,
        )

    def get_hardware_histogram(
        self,
        duration: float,
        bins: int = 500,
        ch_start: int = 1,
        ch_stop: int = 2,
        ch_stop_delay: int | float = 0,
        unit: str = "ns",
        hist_index: int = 1,
    ) -> G2Result:
        """Acquire Start-Stop histogram directly calculated by onboard hardware (HIST1..4)."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        unit_to_ps = {"ps": 1.0, "ns": 1e3, "ms": 1e6}
        if unit not in unit_to_ps:
            raise ValueError(f"Unsupported unit: {unit!r}")

        # Bin width in ps: minimum resolution is self._resolution_ps
        bin_width_ps = max(int(round(self._resolution_ps)), 1)
        if unit == "ns":
            # If user asks for bins in ns, scale bin width accordingly
            bin_width_ps = max(int(round(1000.0)), int(round(self._resolution_ps)))

        # Setup hardware routing for HIST1
        start_block = _INPUT_BLOCK_MAP.get(ch_start, f"INPU{ch_start}")
        stop_block = _INPUT_BLOCK_MAP.get(ch_stop, f"INPU{ch_stop}")

        self.exec_scpi("DEVIce:CONF:LOAD HISTO")
        self.exec_scpi(f"HIST1:REF:LINK {start_block}")
        self.exec_scpi(f"HIST1:STOP:LINK {stop_block}")

        if ch_stop_delay > 0 and ch_stop in (1, 2, 3, 4):
            delay_ps = int(round(ch_stop_delay * unit_to_ps[unit]))
            self.exec_scpi(f"DELA{ch_stop}:VALU {delay_ps}")

        # Setup RECord timer
        self.exec_scpi("REC:TRIG:ARM:MODE MANUal;REC:ENABle ON;REC:STOP;REC:NUM 1")
        self.exec_scpi(f"REC:DURation {int(duration * 1e12)}")

        # Configure HIST1
        self.exec_scpi(f"HIST1:BCOUnt {bins};BWID {bin_width_ps};FLUSh")

        # Start acquisition
        self.exec_scpi("REC:PLAY")

        # Wait until RECord completes
        while self.exec_scpi("REC:STAGe?").strip().upper() == "PLAYING":
            time.sleep(0.1)

        # Retrieve histogram data
        raw_hist = eval(self.exec_scpi("HIST1:DATA?").strip())
        histogram = np.array(raw_hist, dtype=np.uint64)

        # Compute bin edges in bins
        bin_edges = np.arange(len(histogram) + 1, dtype=np.int64)

        # Query singles
        rate_start = float(self.exec_scpi(f"{start_block}:COUN?").strip()) / duration
        rate_stop = float(self.exec_scpi(f"{stop_block}:COUN?").strip()) / duration

        return G2Result(
            histogram=histogram,
            bin_edges=bin_edges.astype(np.float64),
            singles_start=rate_start,
            singles_stop=rate_stop,
            integration_time=duration,
            resolution_ps=float(bin_width_ps),
        )

    def get_timestamps(self, duration: float, channels: Optional[List[int]] = None, **kwargs) -> TimestampResult:
        """Acquire timestamps.
        
        Requires the DataLinkTargetService (DLT) service running on the host machine.
        If DLT is not running, raises a descriptive RuntimeError.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        target_channels = channels or [1, 2]
        fmt = kwargs.get("format", "bin")
        output_dir = Path(kwargs.get("output_dir", Path.cwd()))

        # Check if DLT is reachable
        dlt_socket = None
        if ZMQ_AVAILABLE:
            try:
                # Test DLT port 6060
                s = socket.socket()
                s.settimeout(0.5)
                s.connect((self._dlt_host, self._dlt_port))
                s.close()

                dlt_ctx = zmq.Context()
                dlt_socket = dlt_ctx.socket(zmq.REQ)
                dlt_socket.setsockopt(zmq.RCVTIMEO, 2000)
                dlt_socket.setsockopt(zmq.SNDTIMEO, 2000)
                dlt_socket.connect(f"tcp://{self._dlt_host}:{self._dlt_port}")
            except Exception:
                dlt_socket = None

        if dlt_socket is None:
            raise RuntimeError(
                f"Timestamp streaming for ID1000 requires DataLinkTargetService running on "
                f"{self._dlt_host}:{self._dlt_port}. Please start DataLinkTargetService.exe on the "
                "host machine, or use hardware coincidence / g2 / singles acquisition."
            )

        def dlt_cmd(cmd: str) -> dict:
            dlt_socket.send_string(cmd)
            ans = dlt_socket.recv().decode("utf-8")
            return json.loads(ans) if ans.strip() else {}

        acquisitions_id: Dict[int, str] = {}
        file_map: Dict[int, Path] = {}

        try:
            # 1. Stop any ongoing acquisitions on DLT
            active = dlt_cmd("list")
            if isinstance(active, list):
                for acq in active:
                    dlt_cmd(f"stop --id {acq}")

            # 2. Configure ID1000 RECord timer
            self.exec_scpi("REC:TRIG:ARM:MODE MANUal;REC:ENABle ON;REC:STOP;REC:NUM 1")
            self.exec_scpi(f"REC:DURation {int(duration * 1e12)}")

            # 3. Open DLT file saves
            for ch in target_channels:
                self.exec_scpi(f"RAW{ch}:ERRORS:CLEAR")
                ext = "bin" if fmt == "bin" else "txt"
                filepath = output_dir / f"timestamps_ch{ch}_{int(time.time())}.{ext}"
                file_map[ch] = filepath
                filepath_escaped = str(filepath).replace("\\", "\\\\")

                cmd = f'start-save --address {self._host} --channel {ch} --filename "{filepath_escaped}" --format {fmt} --with-ref-index'
                resp = dlt_cmd(cmd)
                acquisitions_id[ch] = resp["id"]
                self.exec_scpi(f"RAW{ch}:SEND ON")

            # 4. Trigger acquisition
            self.exec_scpi("REC:PLAY")

            # 5. Wait for acquisition to finish
            time.sleep(duration + 0.1)
            while self.exec_scpi("REC:STAGe?").strip().upper() == "PLAYING":
                time.sleep(0.1)

            # 6. Stop transfer
            for ch in target_channels:
                self.exec_scpi(f"RAW{ch}:SEND OFF")
                if ch in acquisitions_id:
                    dlt_cmd(f"stop --id {acquisitions_id[ch]}")

            # 7. Read and parse binary timestamps
            all_ts = []
            all_ch = []
            dtype = np.dtype([("timestamp", np.uint64), ("refIndex", np.uint64)])

            for ch, path in file_map.items():
                if path.exists() and path.stat().st_size > 0:
                    raw_data = np.fromfile(str(path), dtype=dtype)
                    ts = raw_data["timestamp"].astype(np.int64)
                    # Convert to picoseconds
                    ts_ps = (ts.astype(np.float64) * self._resolution_ps).astype(np.int64)
                    ch_arr = np.full(len(ts_ps), ch, dtype=np.uint8)
                    all_ts.append(ts_ps)
                    all_ch.append(ch_arr)
                    try:
                        path.unlink()  # Clean up temp file
                    except Exception:
                        pass

            if all_ts:
                merged_ts = np.concatenate(all_ts)
                merged_ch = np.concatenate(all_ch)
                # Sort by timestamp
                sort_idx = np.argsort(merged_ts)
                final_ts = merged_ts[sort_idx]
                final_ch = merged_ch[sort_idx]
            else:
                final_ts = np.empty(0, dtype=np.int64)
                final_ch = np.empty(0, dtype=np.uint8)

            return TimestampResult(
                timestamps=final_ts,
                channels=final_ch,
                resolution_ps=self._resolution_ps,
                total_time_ns=duration * 1e9,
            )

        finally:
            if dlt_socket is not None:
                dlt_socket.close(linger=0)

    # -- ID1000 Advanced Diagnostics & Status Helpers -------------------------

    def get_input_status(self) -> Dict[str, str]:
        """Query and return the operating status of all 5 physical input channels."""
        status_map: Dict[str, str] = {}
        for ch in range(0, 5):
            block = "STARt" if ch == 0 else f"INPU{ch}"
            if self._is_hires:
                err_code = int(self.exec_scpi(f"{block}:HIRES:ERROR?").strip())
                self.exec_scpi(f"{block}:HIRES:ERROR:CLEAR")
                status_map[block] = f"ErrorCode: {err_code}" if err_code else "OK"
            else:
                status_map[block] = "OK"
        return status_map

    def recalibrate(self) -> str:
        """Trigger device internal sampling recalibration."""
        return self.exec_scpi("DEVIce:SAMPling:RECAlibrate")

    # -- Device Discovery (Safe implementation) -------------------------------

    @classmethod
    def discover_devices(cls) -> List[DeviceInfo]:
        """Safely discover ID1000 devices on the local network.
        
        SAFETY POLICY:
        To prevent network disruption or triggering security alarms (IDS/IPS),
        this method NEVER performs broad subnet sweeps. Instead, it:
        1. Checks environment variable `ID1000_IP` or `IDQ_IP`.
        2. Probes the IDQ factory default IP range (169.254.99.100 - 169.254.99.105)
           using rapid non-blocking socket checks (150ms timeout).
        3. Inspects the system ARP cache for active local devices.
        """
        devices: List[DeviceInfo] = []
        candidate_ips: List[str] = []

        # 1. Environment variable
        env_ip = os.environ.get("ID1000_IP") or os.environ.get("IDQ_IP")
        if env_ip:
            candidate_ips.append(env_ip.strip())

        # 2. Factory default Link-Local IPs
        for last_byte in range(100, 106):
            candidate_ips.append(f"169.254.99.{last_byte}")

        # 3. Read system ARP cache safely (read-only, no packets emitted)
        try:
            arp_out = subprocess.check_output(["arp", "-a"], timeout=1.0).decode("utf-8", errors="ignore")
            found_ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", arp_out)
            for ip in found_ips:
                if ip.startswith("169.254.") and ip not in candidate_ips:
                    candidate_ips.append(ip)
        except Exception:
            pass

        # 4. Probe candidates safely
        for ip in candidate_ips:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.15)
                res = s.connect_ex((ip, cls.DEFAULT_PORT))
                s.close()
                if res == 0:
                    # Verified port 5555 open, attempt brief *IDN? handshake
                    ctx = zmq.Context()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 400)
                    sock.setsockopt(zmq.SNDTIMEO, 400)
                    sock.connect(f"tcp://{ip}:{cls.DEFAULT_PORT}")
                    sock.send_string("*IDN?")
                    ans = sock.recv().decode("utf-8").strip()
                    sock.close(linger=0)
                    ctx.term()

                    sn_match = re.search(r"Serial\s*:\s*(\w+)", ans)
                    sn = sn_match.group(1) if sn_match else None

                    devices.append(
                        DeviceInfo(
                            backend_name="id1000",
                            device_path=f"tcp://{ip}:{cls.DEFAULT_PORT}",
                            serial_number=sn,
                            description=f"IDQ ID1000 Time Controller ({ans[:40]})",
                        )
                    )
            except Exception:
                continue

        return devices
