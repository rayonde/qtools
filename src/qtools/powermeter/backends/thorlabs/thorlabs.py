import logging
from qtools.powermeter.backends.powermeter import register_backend

logger = logging.getLogger(__name__)

# Lazy import support for pyvisa to prevent package-wide failures if pyvisa is not installed
pyvisa_available = False
try:
    import pyvisa
    pyvisa_available = True
except ImportError:
    pass

@register_backend("thorlabs")
class ThorlabsPowerMeter:
    """
    Thorlabs Power Meter backend communicating via PyVISA / SCPI.
    Compatible with PM100D, PM100A, PM100USB, and other PM100x series meters.
    """

    def __init__(self, address: str, timeout: int = 2000, **kwargs):
        """
        Initialize the Thorlabs Power Meter backend.
        
        Args:
            address: VISA resource identifier (e.g. 'USB0::0x1313::0x8078::P0001234::INSTR')
            timeout: Timeout in milliseconds.
            **kwargs: Extra parameters passed to the Resource Manager / Open Resource.
        """
        if not pyvisa_available:
            raise ImportError(
                "The 'pyvisa' library is required to use the Thorlabs backend. "
                "Please install it using 'pip install pyvisa' and verify your VISA installation."
            )
        self.address = address
        self.timeout = timeout
        self.kwargs = kwargs
        self.rm = None
        self.instrument = None

    def connect(self) -> None:
        try:
            self.rm = pyvisa.ResourceManager()
            self.instrument = self.rm.open_resource(self.address, **self.kwargs)
            self.instrument.timeout = self.timeout
            
            # Standard SCPI termination characters
            self.instrument.write_termination = '\n'
            self.instrument.read_termination = '\n'
            
            # Configure default mode to power measurement
            try:
                self.instrument.write("CONF:POW")
            except Exception as e:
                logger.warning(f"Could not write 'CONF:POW' command to instrument: {e}")
        except Exception as e:
            self.disconnect()
            raise ConnectionError(
                f"Failed to connect to Thorlabs power meter at '{self.address}': {e}\n"
                "Please ensure the device is connected and set to NI-VISA mode (not TLPM)."
            )

    def disconnect(self) -> None:
        if self.instrument:
            try:
                self.instrument.close()
            except Exception:
                pass
            self.instrument = None
        if self.rm:
            try:
                self.rm.close()
            except Exception:
                pass
            self.rm = None

    def get_power(self) -> float:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            # Query standard read
            val = self.instrument.query("READ?")
            return float(val)
        except Exception as e:
            # Fallback to MEASure:POWer? if direct READ? fails
            try:
                val = self.instrument.query("MEAS:POW?")
                return float(val)
            except Exception as e2:
                raise RuntimeError(f"Failed to query power from Thorlabs device: {e2}")

    def get_info(self) -> str:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            return self.instrument.query("*IDN?").strip()
        except Exception as e:
            return f"Thorlabs Power Meter ({self.address}) - Info error: {e}"

    def set_wavelength(self, wavelength: float) -> None:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            self.instrument.write(f"SENS:CORR:WAV {wavelength}")
        except Exception as e:
            raise RuntimeError(f"Failed to set wavelength: {e}")

    def get_wavelength(self) -> float:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            val = self.instrument.query("SENS:CORR:WAV?")
            return float(val)
        except Exception as e:
            raise RuntimeError(f"Failed to get wavelength: {e}")

    def set_range(self, range_val: float) -> None:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            # If set to auto range (e.g. range_val is <= 0 or None)
            if range_val is None or range_val <= 0:
                self.auto_range = True
                self.instrument.write("SENS:POW:DC:RANG:AUTO ON")
            else:
                self.auto_range = False
                self.instrument.write("SENS:POW:DC:RANG:AUTO OFF")
                self.instrument.write(f"SENS:POW:DC:RANG {range_val}")
        except Exception as e:
            raise RuntimeError(f"Failed to set range: {e}")

    def get_range(self) -> float:
        if not self.instrument:
            raise RuntimeError("Device is not connected. Call connect() first.")
        try:
            val = self.instrument.query("SENS:POW:DC:RANG?")
            return float(val)
        except Exception as e:
            raise RuntimeError(f"Failed to get range: {e}")

    @staticmethod
    def list_devices() -> list:
        """Helper to scan and list VISA resources."""
        if not pyvisa_available:
            return []
        try:
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            rm.close()
            return list(resources)
        except Exception:
            return []
