import random
import time
import math
import os
import json
import bisect
from qtools.powermeter.backends.powermeter import register_backend

pkg_dir = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CAL_FILES = {
    "s5106": os.path.join(pkg_dir, "..", "s15", "s5106_interpolated.cal"),
    "fdg50": os.path.join(pkg_dir, "..", "s15", "fdg50_interpolated.cal"),
}

@register_backend("mock")
class MockPowerMeter:
    """
    Mock Power Meter for simulation and verification.
    Generates a realistic power signal with noise, drift, and S15-like range/voltage responses.
    """
    VALID_RANGES = [1, 2, 3, 4, 5]  # Supported range indices

    def __init__(
        self, 
        address: str = "MOCK0", 
        base_power: float = 0.0015,  # 1.5 mW
        noise_level: float = 0.02,   # 2% relative noise
        drift_rate: float = 0.1,     # drift modulation speed
        **kwargs
    ):
        """
        Initialize the Mock Power Meter.
        """
        self.address = address
        self.base_power = base_power
        self.noise_level = noise_level
        self.drift_rate = drift_rate
        self.kwargs = kwargs
        self.connected = False
        self.start_time = 0.0
        self.wavelength = 780.0
        self.cal_file = None
        
        # Load arrays to store loaded calibration
        self.cal_wavelengths = []
        self.cal_responsivities = []
        
        # Auto-ranging parameters matching Hamamatsu S5106 sense resistors
        # Index 0 unused so range indices 1..5 map directly (mirrors S15 backend).
        self.resistors = [None, 1e6, 99099.0990990991, 10e3, 1e3, 20.0]
        self.RANGE_DOWN = [None, 0.0, 0.2, 0.2, 0.2, 0.04]
        self.RANGE_UP = [None, 2.2, 2.2, 2.2, 2.2, 100.0]
        self.range_idx = 1
        self.auto_range = True
        self._last_voltage: float | None = None
        self._last_range: int | None = 1

    def connect(self) -> None:
        self.connected = True
        self.start_time = time.time()
        self.update_calibration()

    def disconnect(self) -> None:
        self.connected = False

    def get_power(self) -> float:
        if not self.connected:
            raise RuntimeError("Mock device is not connected. Call connect() first.")
        
        # If running default simulation, sweep across all ranges (1uW to 50mW) dynamically
        # to observe auto-ranging switching. If user customized base_power, use that.
        elapsed = time.time() - self.start_time
        if self.base_power == 0.0015:
            # Sweep period of 30 seconds
            period = 30.0
            angle = (elapsed * 2 * math.pi) / period
            # Map sine -1..1 to log power -6.0..-1.3
            log_power = -3.65 + 2.35 * math.sin(angle)
            target_power = 10 ** log_power
        else:
            # Maintain custom base power with drift
            drift = 0.05 * math.sin(elapsed * self.drift_rate) * self.base_power
            flicker = 0.02 * math.cos(elapsed * 2.3) * self.base_power
            target_power = self.base_power + drift + flicker

        noise = random.gauss(0, self.noise_level * target_power)
        power = target_power + noise
        power = max(0.0, power)
        
        # Simulate auto-ranging based on voltage levels across resistors
        responsivity = self._interpolate_responsivity(self.wavelength)
        current = power * responsivity
        
        for _ in range(5):
            resistor = self.resistors[self.range_idx]
            volt = current * resistor
            if self.auto_range:
                if volt > self.RANGE_UP[self.range_idx] and self.range_idx < 5:
                    self.range_idx += 1
                elif volt < self.RANGE_DOWN[self.range_idx] and self.range_idx > 1:
                    self.range_idx -= 1
                else:
                    break
            else:
                break

        self._last_voltage = volt
        self._last_range = self.range_idx
        return power

    def get_info(self) -> str:
        return f"MockPowerMeter,Model-M100,SN-{self.address},FW-1.0.0"

    def load_calibration_file(self, path_or_name: str) -> None:
        """Simulate loading a calibration file and parse its wavelengths/responsivities."""
        if path_or_name in DEFAULT_CAL_FILES:
            path = DEFAULT_CAL_FILES[path_or_name]
            self.cal_file = path_or_name
        elif os.path.exists(path_or_name):
            path = path_or_name
            self.cal_file = path_or_name
        else:
            # Fallback path lookup inside s15 directory
            pkg_s15_dir = os.path.join(pkg_dir, "..", "s15")
            pkg_path = os.path.join(pkg_s15_dir, path_or_name)
            if os.path.exists(pkg_path):
                path = pkg_path
                self.cal_file = path_or_name
            else:
                raise FileNotFoundError(f"Calibration file '{path_or_name}' not found.")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.cal_wavelengths = [float(x) for x in data[0]]
        self.cal_responsivities = [float(x) for x in data[1]]
        
        file_basename = os.path.basename(path)
        print(f"Calibration file in use: {path_or_name} (loaded from {file_basename})")

    def _interpolate_responsivity(self, wavelength: float) -> float:
        """Interpolate responsivity (A/W) from the loaded calibration data."""
        if not self.cal_wavelengths:
            return 0.6  # Default fallback
            
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

    def update_calibration(self) -> None:
        """Automatically switch calibration files based on wavelength (FDG50 vs S5106)."""
        if self.wavelength >= 1100.0:
            self.load_calibration_file("fdg50")
        else:
            self.load_calibration_file("s5106")

    def set_wavelength(self, wavelength: float) -> None:
        if not self.connected:
            raise RuntimeError("Mock device is not connected.")
        self.wavelength = wavelength
        self.update_calibration()

    def get_wavelength(self) -> float:
        if not self.connected:
            raise RuntimeError("Mock device is not connected.")
        return self.wavelength

    def set_range(self, range_val: float) -> None:
        if not self.connected:
            raise RuntimeError("Mock device is not connected.")
        if range_val is None or range_val <= 0:
            self.auto_range = True
        else:
            self.auto_range = False
            # Check if index 1-5 was explicitly provided
            if range_val in self.VALID_RANGES or float(range_val) in [float(x) for x in self.VALID_RANGES]:
                self.range_idx = int(range_val)
            else:
                # Map float range limits to index
                if range_val <= 2e-5:
                    self.range_idx = 5
                elif range_val <= 1e-3:
                    self.range_idx = 4
                elif range_val <= 10e-3:
                    self.range_idx = 3
                elif range_val <= 100e-3:
                    self.range_idx = 2
                else:
                    self.range_idx = 1
            self._last_range = self.range_idx

    def get_range(self) -> int:
        if not self.connected:
            raise RuntimeError("Mock device is not connected.")
        # Prefer the range used by the most recent get_power() call.
        if self._last_range is not None:
            return self._last_range
        return self.range_idx

    @property
    def last_voltage(self) -> float | None:
        return self._last_voltage

    @property
    def last_range(self) -> int | None:
        return self._last_range

    def get_voltage(self) -> float:
        if not self.connected:
            raise RuntimeError("Mock device is not connected.")
        if self._last_voltage is not None:
            return self._last_voltage
        power = self.get_power()
        return self._last_voltage if self._last_voltage is not None else 0.0