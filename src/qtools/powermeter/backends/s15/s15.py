import bisect
import json
import logging
import os
import time
from qtools.powermeter.backends.powermeter import register_backend

logger = logging.getLogger(__name__)

# Lazy import pyserial to avoid dependency issues if pyserial is not installed
serial_available = False
try:
    import serial
    import serial.tools.list_ports
    serial_available = True
except ImportError:
    pass

# Resolve bundled calibration file paths (local to backends/s15 directory)
pkg_dir = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CAL_FILES = {
    "s5106": os.path.join(pkg_dir, "s5106_interpolated.cal"),
    "fdg50": os.path.join(pkg_dir, "fdg50_interpolated.cal"),
}

@register_backend("s15")
class S15PowerMeter:
    """
    S15 Optical Power Meter Backend.
    Uses serial interface (PySerial) to communicate with the OPM hardware device.
    Performs power conversion using photodiode calibration files.
    """
    # Sense resistors for range indices 1..5 (index 0 unused, mirrors firmware).
    RESISTORS = [None, 1e6, 99099.0990990991, 10e3, 1e3, 20]
    VALID_RANGES = [1, 2, 3, 4, 5]

    # Per-range auto-range thresholds (from the original S15 physicsutils driver).
    # DOWN: go to a more sensitive range (lower index) when voltage falls below.
    # UP:   go to a less sensitive range (higher index) when voltage rises above.
    # Index 0 unused; range 1 never downs, range 5 never ups.
    RANGE_DOWN = [None, 0.0, 0.2, 0.2, 0.2, 0.04]
    RANGE_UP = [None, 2.2, 2.2, 2.2, 2.2, 100.0]

    # Settling time after a hardware range change (ADC needs to re-settle).
    RANGE_SETTLE_S = 0.05

    def __init__(self, address: str = "", **kwargs):
        """
        Initialize the S15 Power Meter backend.

        Args:
            address: Device address (e.g. 'COM3', '/dev/ttyACM0'). If empty, attempts to auto-detect.
        """
        if not serial_available:
            raise ImportError(
                "The 'pyserial' library is required to use the S15 backend. "
                "Please install it using 'pip install pyserial'."
            )
        self.address = address
        self.kwargs = kwargs
        self.serial = None
        self.connected = False

        self.wavelength = 780.0

        # Auto-range enabled by default
        self.auto_range = True

        # EMA (exponential moving average) for voltage smoothing
        self.ema_window: int = 1  # 1 = no smoothing; increase for more damping
        self._smoothed_voltage: float = 0.0

        # Cached values from the most recent get_power() call — used by live
        # displays so they don't need extra serial round-trips (which desync
        # the bus and can silently drop the Range readout).
        self._last_voltage: float | None = None
        self._last_range: int | None = None

        self.cal_file = None
        self.cal_wavelengths = []
        self.cal_responsivities = []

    def connect(self) -> None:
        if self.connected:
            return

        if not self.address:
            detected = self.list_devices()
            if detected:
                self.address = detected[0]
                logger.info(f"Auto-detected S15 device: {self.address}")
            else:
                raise ConnectionError("No serial devices matching S15 power meter (OPM) detected.")

        try:
            self.serial = serial.Serial(self.address, baudrate=115200, timeout=2.0)
            # Flush hardware buffer
            self._serial_write('a')
            try:
                # Read the response (which is usually an 'Unknown command' or warning, to clear buffer)
                self._serial_read()
            except Exception:
                pass
                
            self.connected = True
            self.update_calibration()
        except Exception as e:
            self.disconnect()
            raise ConnectionError(f"Failed to connect to S15 power meter at '{self.address}': {e}")

    def disconnect(self) -> None:
        if self.serial:
            try:
                if self.serial.is_open:
                    self.serial.close()
            except Exception:
                pass
            self.serial = None
        self.connected = False

    def _serial_write(self, cmd: str) -> None:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Device is not connected. Call connect() first.")
        self.serial.write(f"{cmd}\n".encode("ascii"))

    def _serial_read(self) -> str:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Device is not connected. Call connect() first.")
        line = self.serial.readline()
        return line.rstrip().decode("ascii")

    def reset(self) -> str:
        self._serial_write("*RST")
        return self._serial_read()

    def get_voltage(self) -> float:
        """Query the raw photodiode voltage from the hardware."""
        self._serial_write("VOLT?")
        res = self._serial_read()
        try:
            return float(res)
        except ValueError:
            raise RuntimeError(f"Invalid voltage response from S15 device: '{res}'")

    def get_range(self) -> int:
        """
        Return the current range index.

        Prefers the value cached by the most recent :meth:`get_power` call so
        live displays don't need an extra serial round-trip. Falls back to a
        hardware query if nothing has been cached yet.
        """
        if self._last_range is not None:
            return self._last_range
        return self._query_range()

    def _query_range(self) -> int:
        """Query the current range index directly from the hardware."""
        self._serial_write("RANGE?")
        res = self._serial_read()
        try:
            range_idx = int(res)
        except ValueError:
            raise RuntimeError(f"Invalid range response from S15 device: '{res}'")
        self._last_range = range_idx
        return range_idx

    def set_range(self, range_val: float | None) -> None:
        """
        Set power range index (1 to 5), or 0/None to enable auto-ranging.
        """
        if range_val is None or int(range_val) == 0:
            self.auto_range = True
            return

        val = int(range_val)
        if val not in self.VALID_RANGES:
            raise ValueError(f"S15 range index must be one of {self.VALID_RANGES}.")

        # Manual range: disable auto-range and push the index to the hardware.
        self.auto_range = False
        self._set_range(val)

    def _set_range(self, range_idx: int) -> None:
        """
        Push a range index (1 to 5) to the hardware.

        This is the low-level range setter used internally by the auto-range
        loop. Unlike :meth:`set_range`, it does **not** touch ``auto_range``,
        so it can be called repeatedly while auto-ranging is active without
        disabling it.

        Uses ``RANGE {n}`` (space-separated) to match the original S15 firmware
        protocol used by physicsutils.
        """
        if range_idx not in self.VALID_RANGES:
            raise ValueError(f"S15 range index must be one of {self.VALID_RANGES}.")
        self._serial_write(f"RANGE {range_idx}")
        self._last_range = range_idx
        # Give the ADC time to settle after the gain change.
        time.sleep(self.RANGE_SETTLE_S)

    def get_info(self) -> str:
        if not self.connected:
            return "S15 Power Meter (Disconnected)"
        try:
            self._serial_write("*IDN?")
            info = self._serial_read()
            # *IDN? response ends with an extra blank line (\r\n\r\n);
            # drain it so it doesn't desync subsequent queries.
            self._drain_buffer()
            return info
        except Exception:
            return f"S15 Power Meter on {self.address}"

    def _drain_buffer(self) -> None:
        """Read and discard any leftover data in the serial input buffer.

        The S15 firmware appends a trailing blank line after some responses
        (notably *IDN?).  Without draining, the empty line gets picked up by
        the next command's _serial_read() and causes parse errors.
        """
        while self.serial.in_waiting:
            self.serial.readline()

    def set_wavelength(self, wavelength: float) -> None:
        self.wavelength = wavelength
        self.update_calibration()

    def get_wavelength(self) -> float:
        return self.wavelength

    def load_calibration_file(self, path_or_name: str) -> None:
        """
        Load calibration file from a name ('s5106', 'fdg50') or an absolute file path.
        """
        if path_or_name in DEFAULT_CAL_FILES:
            path = DEFAULT_CAL_FILES[path_or_name]
            self.cal_file = path_or_name
        elif os.path.exists(path_or_name):
            path = path_or_name
            self.cal_file = path_or_name
        else:
            # Try to resolve relative to package root
            pkg_path = os.path.join(pkg_dir, path_or_name)
            if os.path.exists(pkg_path):
                path = pkg_path
                self.cal_file = path_or_name
            else:
                raise FileNotFoundError(f"Calibration file/name '{path_or_name}' not found.")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if len(data) != 2 or not data[0]:
            raise ValueError(f"Invalid format in calibration file '{path}'")

        self.cal_wavelengths = [float(x) for x in data[0]]
        self.cal_responsivities = [float(x) for x in data[1]]
        logger.info("Loaded calibration data from '%s'", self.cal_file)

    def update_calibration(self) -> None:
        """
        Automatically switch default calibration files based on wavelength
        if a custom calibration file is not loaded.
        """
        # Switch only if cal_file is None or one of the default calibration names/paths
        is_default_s5106 = (self.cal_file in ["s5106", DEFAULT_CAL_FILES["s5106"]])
        is_default_fdg50 = (self.cal_file in ["fdg50", DEFAULT_CAL_FILES["fdg50"]])
        if self.cal_file is None or is_default_s5106 or is_default_fdg50:
            target = "fdg50" if self.wavelength >= 1100.0 else "s5106"
            if self.cal_file != target:
                self.load_calibration_file(target)

    def _apply_ema(self, raw: float) -> float:
        """Apply exponential moving average to smooth voltage readings."""
        if self._smoothed_voltage == 0.0:
            self._smoothed_voltage = raw
        else:
            self._smoothed_voltage = (
                (self.ema_window - 1) * self._smoothed_voltage + raw
            ) / self.ema_window
        return self._smoothed_voltage

    @property
    def smoothed_voltage(self) -> float:
        """The EMA-smoothed voltage from the most recent get_power() call."""
        return self._smoothed_voltage

    @property
    def last_voltage(self) -> float | None:
        """Raw (EMA-smoothed) voltage from the most recent get_power() call."""
        return self._last_voltage

    @property
    def last_range(self) -> int | None:
        """Range index used by the most recent get_power() call."""
        return self._last_range

    def get_power(self) -> float:
        """Read voltage, apply EMA, auto-range, calibrate, and return power in Watts."""
        if not self.connected:
            raise RuntimeError("Device is not connected. Call connect() first.")

        if not self.cal_wavelengths:
            self.update_calibration()

        # Prefer the cached range to avoid an extra serial round-trip every
        # sample; fall back to a hardware query on the first call.
        range_idx = self._last_range if self._last_range is not None else self._query_range()

        if self.auto_range:
            # Keep stepping until the voltage sits inside the per-range window.
            # Thresholds match the original S15 physicsutils driver so range
            # can actually drop below 4/5 under moderate optical power.
            for _ in range(len(self.VALID_RANGES)):
                raw = self.get_voltage()
                volt = self._apply_ema(raw)
                if volt > self.RANGE_UP[range_idx] and range_idx < 5:
                    range_idx += 1
                    self._set_range(range_idx)
                    continue
                if volt < self.RANGE_DOWN[range_idx] and range_idx > 1:
                    range_idx -= 1
                    self._set_range(range_idx)
                    continue
                break
        else:
            raw = self.get_voltage()
            volt = self._apply_ema(raw)

        # Cache for live displays (avoid extra serial queries that desync the bus).
        self._last_voltage = volt
        self._last_range = range_idx

        # Interpolate responsivity
        resp = self._interpolate_responsivity(self.wavelength)

        # Calculate optical power: I = V/R, P = I / responsivity
        resistance = self.RESISTORS[range_idx]
        power = volt / resistance / resp
        return power

    def _interpolate_responsivity(self, wavelength: float) -> float:
        if not self.cal_wavelengths:
            raise RuntimeError("Calibration data not loaded.")

        wl_list = self.cal_wavelengths
        resp_list = self.cal_responsivities

        if wavelength in wl_list:
            return resp_list[wl_list.index(wavelength)]

        position = bisect.bisect_left(wl_list, wavelength)
        if position == 0:
            return resp_list[0]
        if position >= len(wl_list):
            return resp_list[-1]

        left_wl = wl_list[position - 1]
        right_wl = wl_list[position]
        left_resp = resp_list[position - 1]
        right_resp = resp_list[position]

        fraction = (wavelength - left_wl) / (right_wl - left_wl)
        return left_resp + fraction * (right_resp - left_resp)

    @staticmethod
    def list_devices() -> list:
        """
        Scan and automatically identify powermeter serial/USB devices (OPM).
        Queries *IDN? with a short timeout to prevent blocking other devices.
        """
        if not serial_available:
            return []
        
        opm_ports = []
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception:
            return []

        for port_info in ports:
            dev = port_info.device
            desc = (port_info.description or "").lower()
            
            # Skip known non-OPM ports (including Thorlabs motors) to save scan time and prevent serial corruption
            if getattr(port_info, "vid", None) == 0x0403 and getattr(port_info, "pid", None) == 0xFAF0:
                continue
            mfg = (getattr(port_info, "manufacturer", "") or "").lower()
            if any(k in desc or k in mfg for k in ["k10cr1", "thorlabs", "apt", "bluetooth", "bt-ecu", "wireless"]):
                continue
                
            # If description specifically has "opm", we can prioritize it
            if "opm" in desc:
                opm_ports.append(dev)
                continue
                
            # Otherwise, check identity query to verify it's the custom power meter
            try:
                # Open with small timeout to quickly verify
                ser = serial.Serial(dev, baudrate=115200, timeout=0.15)
                ser.write(b"a\n*IDN?\n")
                # Read response
                response = ser.readline().decode("ascii", errors="ignore").strip()
                ser.close()
                if "OPM" in response:
                    opm_ports.append(dev)
            except Exception:
                pass
                
        return opm_ports
