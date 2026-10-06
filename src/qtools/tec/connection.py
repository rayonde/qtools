"""Serial connection and hardware discovery for TEC devices."""

from __future__ import annotations

import logging
import pathlib
import sys
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


import serial
import serial.tools.list_ports as list_ports

from qtools.tec.exceptions import (
    TECConnectionError,
    TECDeviceNotFoundError,
    TECProtocolError,
)

logger = logging.getLogger(__name__)

# Default USB IDs for QinHeng CH340 USB-to-Serial converter commonly used by SenseFuture TEC
DEFAULT_VID = 0x1A86
DEFAULT_PID = 0x7523
DEFAULT_PATTERN = "1a86_USB_Serial"


def list_serial_ports() -> List[Dict[str, Any]]:
    """List all available serial ports on the system.

    Returns:
        A list of dictionaries containing device name, description, vid, pid, and hwid.
    """
    ports = []
    for p in list_ports.comports():
        ports.append(
            {
                "device": p.device,
                "description": p.description,
                "vid": p.vid,
                "pid": p.pid,
                "serial_number": p.serial_number,
                "manufacturer": p.manufacturer,
                "hwid": p.hwid,
            }
        )
    return ports


def find_serial_device(
    pattern: str = DEFAULT_PATTERN,
    vid: Optional[int] = DEFAULT_VID,
    pid: Optional[int] = DEFAULT_PID,
) -> str:
    """Find a TEC serial device port matching pattern and/or USB VID:PID.

    Supports cross-platform discovery (macOS, Linux, Windows):
    1. Checks ports via pyserial's ``comports()`` for matching VID:PID or description.
    2. Fallback to ``/dev/serial/by-id/`` on Linux.

    Args:
        pattern: Pattern or substring to match against port description or path.
        vid: Optional USB Vendor ID (default: 0x1A86).
        pid: Optional USB Product ID (default: 0x7523).

    Returns:
        The device port path (e.g., '/dev/ttyUSB0', '/dev/cu.usbserial-110').

    Raises:
        TECDeviceNotFoundError: If no devices or multiple ambiguous devices are found.
    """
    matched_ports: List[str] = []

    # 1. Inspect comports (cross-platform)
    try:
        for p in list_ports.comports():
            # Check VID/PID match
            is_vid_pid_match = False
            if vid is not None and pid is not None and p.vid is not None and p.pid is not None:
                if p.vid == vid and p.pid == pid:
                    is_vid_pid_match = True

            # Check pattern match
            is_pattern_match = False
            if pattern:
                p_lower = pattern.lower()
                device_str = (p.device or "").lower()
                desc_str = (p.description or "").lower()
                hwid_str = (p.hwid or "").lower()
                manuf_str = (p.manufacturer or "").lower()
                if (
                    p_lower in device_str
                    or p_lower in desc_str
                    or p_lower in hwid_str
                    or p_lower in manuf_str
                ):
                    is_pattern_match = True

            if is_vid_pid_match or is_pattern_match:
                if p.device not in matched_ports:
                    matched_ports.append(p.device)
    except Exception as e:
        logger.debug("Failed querying serial comports: %s", e)

    # 2. Linux fallback: /dev/serial/by-id/
    by_id_dir = pathlib.Path("/dev/serial/by-id/")
    if sys.platform.startswith("linux") and by_id_dir.is_dir():
        glob_pat = "*" if not pattern else f"*{pattern}*"
        for p in by_id_dir.glob(glob_pat):
            dev_str = str(p)
            if dev_str not in matched_ports:
                matched_ports.append(dev_str)

    if len(matched_ports) == 0:
        raise TECDeviceNotFoundError(
            f"No TEC serial device found matching VID={hex(vid) if vid else 'None'} "
            f"PID={hex(pid) if pid else 'None'} pattern='{pattern}'"
        )
    elif len(matched_ports) == 1:
        return matched_ports[0]
    else:
        raise TECDeviceNotFoundError(
            f"Multiple matching serial devices found: {matched_ports}. "
            "Please specify the device port path explicitly."
        )


class BaseTransport(ABC):
    """Abstract base class for TEC communication transports."""

    @abstractmethod
    def write(self, command: str) -> None:
        """Send command string to TEC."""

    @abstractmethod
    def read(self) -> str:
        """Read response string from TEC."""

    def rw(self, command: str) -> str:
        """Write command and return response."""
        self.write(command)
        return self.read()

    @abstractmethod
    def close(self) -> None:
        """Close connection."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Check if transport is open."""


class SerialTransport(BaseTransport):
    """Pyserial transport for physical TEC hardware."""

    def __init__(
        self,
        port: str,
        baudrate: int = 38400,
        timeout: float = 0.5,
        write_timeout: float = 1.0,
        inter_command_delay: float = 0.005,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.inter_command_delay = inter_command_delay
        self._last_write_time = 0.0
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
                write_timeout=write_timeout,
            )
        except Exception as e:
            raise TECConnectionError(
                f"Failed to open serial port '{port}' at {baudrate} baud: {e}"
            ) from e

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write(self, command: str) -> None:
        if not self.is_open:
            raise TECConnectionError(f"Serial port '{self.port}' is closed.")
        # Follow protocol specification: wait at least 5ms between consecutive transmissions
        elapsed = time.time() - self._last_write_time
        if elapsed < self.inter_command_delay:
            time.sleep(self.inter_command_delay - elapsed)

        cmd_str = command if command.endswith("@") else f"{command}@"
        try:
            self._serial.write(cmd_str.encode("ascii"))
            self._serial.flush()
            self._last_write_time = time.time()
        except Exception as e:
            raise TECConnectionError(f"Serial write error on '{self.port}': {e}") from e

    def read(self) -> str:
        if not self.is_open:
            raise TECConnectionError(f"Serial port '{self.port}' is closed.")
        try:
            raw = self._serial.read_until(b"@")
            if not raw:
                raise TECProtocolError(
                    f"Timeout ({self.timeout}s) waiting for response from TEC device on '{self.port}'"
                )
            if self._serial.in_waiting > 0:
                trailing = self._serial.read_until(b"\n")
                raw += trailing
            return raw.decode("ascii", errors="replace").strip("\r\n\x00 ")
        except TECProtocolError:
            raise
        except Exception as e:
            raise TECConnectionError(f"Serial read error on '{self.port}': {e}") from e

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception as e:
                logger.debug("Error closing serial port: %s", e)


class MockSerialTransport(BaseTransport):
    """In-memory mock transport simulating a SenseFuture RD105 TEC device."""

    def __init__(self, model: str = "RD105", initial_temp: float = 25.0):
        self._is_open = True
        self.port = "mock://sensefuture-tec"
        temp_int = round(initial_temp * 100000)
        self.registers: Dict[str, Any] = {
            "TEC": model,
            "FPV": 100,  # Firmware v1.0.0
            "SINTERIORTEMP": 25,  # 25°C internal temp
            "OVERTVPT": 70,  # Internal over-temp threshold (40~100 °C)
            "ERRORCODE": 0,  # No errors
            # Channel 1
            "TC1:ENABLE": 0,
            "TC1:TG": temp_int,  # Target temp in 1e-5 °C
            "TC1:TCADJTEMP": temp_int,  # Actual temp in 1e-5 °C
            "TC1:RESISTOR": 10000000000,  # 10.000000 kΩ
            "TC1:SPEED": 1000,  # 1.0 K/s (1e-3)
            "TC1:CURRENT": 0,  # 0.0 A
            "TC1:SETCURRENT": 15,  # 1.5 A (1e-1)
            "TC1:LIMITED": 80,  # 80 %
            "TC1:PIDPOL": 0,  # Normal polarity
            "TC1:MODE": 0,  # Both heat and cool
            "TC1:PWMDUTY": 0,
            "TC1:KP": 1000,  # 1.000 A/K
            "TC1:KI": 500,  # 0.500 As/K
            "TC1:KD": 50,  # 0.050 A/sK
            "TC1:AUTOPID": 0,
            "TC1:POLYOMIAL": 0,
            "TC1:BX": 395000,  # B=3950.00
            "TC1:RP": 10000,   # R0=10.000 kΩ
            "TC1:OVERTEMPUP": 500000000,  # 5000.0 °C
            "TC1:OVERTEMPLOWER": -300000000,  # -3000.0 °C
            "TC1:ONSENSOR": 1,
            "TC1:POWERMODE": 0,
            # Channel 2
            "TC2:ENABLE": 0,
            "TC2:TG": temp_int,
            "TC2:TCADJTEMP": temp_int,
            "TC2:RESISTOR": 10000000000,
            "TC2:SPEED": 1000,
            "TC2:CURRENT": 0,
            "TC2:SETCURRENT": 15,
            "TC2:LIMITED": 80,
            "TC2:PIDPOL": 0,
            "TC2:MODE": 0,
            "TC2:PWMDUTY": 0,
            "TC2:KP": 1000,
            "TC2:KI": 500,
            "TC2:KD": 50,
            "TC2:AUTOPID": 0,
            "TC2:POLYOMIAL": 0,
            "TC2:BX": 395000,
            "TC2:RP": 10000,
            "TC2:OVERTEMPUP": 500000000,
            "TC2:OVERTEMPLOWER": -300000000,
            "TC2:ONSENSOR": 1,
            "TC2:POWERMODE": 0,
        }
        self._last_response = ""

    @property
    def is_open(self) -> bool:
        return self._is_open

    def write(self, command: str) -> None:
        if not self._is_open:
            raise TECConnectionError("Mock serial port is closed.")

        cmd = command.rstrip("@\r\n ")

        # Batch commands (Section 3.6 & 3.5.9)
        if cmd == "INQUIRE=1":
            self._last_response = (
                f"OKTC1:TG={self.registers['TC1:TG']}@TC2:TG={self.registers['TC2:TG']}@"
                f"OKTC1:LIMITED={self.registers['TC1:LIMITED']}@TC2:LIMITED={self.registers['TC2:LIMITED']}@"
                f"OKTC1:MODE={self.registers['TC1:MODE']}@TC2:MODE={self.registers['TC2:MODE']}@"
                f"OKTC1:ENABLE={self.registers['TC1:ENABLE']}@TC2:ENABLE={self.registers['TC2:ENABLE']}@"
                f"OKTC1:KP={self.registers['TC1:KP']}@TC2:KP={self.registers['TC2:KP']}@"
                f"OKTC1:KI={self.registers['TC1:KI']}@TC2:KI={self.registers['TC2:KI']}@"
                f"OKTC1:KD={self.registers['TC1:KD']}@TC2:KD={self.registers['TC2:KD']}@"
                f"OKTEC={self.registers['TEC']}@"
            )
        elif cmd == "DATADEMAND=1":
            self._last_response = (
                f"TC1:TCADJTEMP={self.registers['TC1:TCADJTEMP']}@"
                f"TC1:RESISTOR={self.registers['TC1:RESISTOR']}@"
                f"TC1:PWM=0@"
                f"TC2:TCADJTEMP={self.registers['TC2:TCADJTEMP']}@"
                f"TC2:RESISTOR={self.registers['TC2:RESISTOR']}@"
                f"TC2:PWM=0@"
                f"SINTERIORTEMP={self.registers['SINTERIORTEMP']}@"
            )
        elif cmd == "DATADEMAND=2":
            self._last_response = (
                f"TC1:TCADJTEMP={self.registers['TC1:TCADJTEMP']}@"
                f"TC1:RESISTOR={self.registers['TC1:RESISTOR']}@"
                f"TC1:OUTV=0@"
                f"TC2:TCADJTEMP={self.registers['TC2:TCADJTEMP']}@"
                f"TC2:RESISTOR={self.registers['TC2:RESISTOR']}@"
                f"TC2:OUTV=0@"
                f"SINTERIORTEMP={self.registers['SINTERIORTEMP']}@"
            )
        elif cmd == "RESET=1":
            self.registers["TC1:ENABLE"] = 0
            self.registers["TC2:ENABLE"] = 0
            self._last_response = "OKRESET=1@"
        elif cmd.endswith("=?"):
            # Query command (e.g. "TC1:TG=?" or "TEC=?")
            key = cmd[:-2]
            if key in self.registers:
                val = self.registers[key]
                self._last_response = f"OK{key}={val}@"
            else:
                self._last_response = f"OK{key}=0@"
        elif "=" in cmd:
            # Set command (e.g. "TC1:TG=2500000")
            key, _, val_str = cmd.partition("=")
            try:
                val = int(val_str)
            except ValueError:
                val = val_str
            self.registers[key] = val
            # If target changed, simulate actual temp moving
            if key == "TC1:TG":
                self.registers["TC1:TCADJTEMP"] = val
            elif key == "TC2:TG":
                self.registers["TC2:TCADJTEMP"] = val
            self._last_response = f"OK{cmd}@"
        else:
            self._last_response = f"OK{cmd}@"


    def read(self) -> str:
        if not self._is_open:
            raise TECConnectionError("Mock serial port is closed.")
        return self._last_response

    def close(self) -> None:
        self._is_open = False
