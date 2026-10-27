import logging
from qtools.powermeter.backends.powermeter import register_backend

logger = logging.getLogger(__name__)

# Lazy import support for serial
serial_available = False
try:
    import serial
    import serial.tools.list_ports
    serial_available = True
except ImportError:
    pass

@register_backend("lbtek")
class LBTekPowerMeter:
    """
    LBTEK Power Meter backend using PySerial.
    Handles communication with USB virtual serial port power meters.
    Since LBTEK command protocols are model-specific, this class supports
    configuring custom query commands.
    """

    def __init__(
        self,
        address: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
        read_termination: str = "\n",
        write_termination: str = "\n",
        read_command: str = "READ?",
        idn_command: str = "*IDN?",
        **kwargs
    ):
        """
        Initialize the LBTEK Serial Power Meter backend.

        Args:
            address: Device address (e.g. 'COM3', '/dev/ttyUSB0').
            baudrate: Communication baudrate.
            timeout: Read timeout in seconds.
            read_termination: Expected line ending for reads.
            write_termination: Expected line ending for writes.
            read_command: Command to trigger a single power reading.
            idn_command: Command to request device identity.
            **kwargs: Extra parameters passed to serial.Serial initializer.
        """
        if not serial_available:
            raise ImportError(
                "The 'pyserial' library is required to use the LBTEK backend. "
                "Please install it using 'pip install pyserial'."
            )
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self.read_termination = read_termination
        self.write_termination = write_termination
        self.read_command = read_command
        self.idn_command = idn_command
        self.kwargs = kwargs
        self.serial = None

    def connect(self) -> None:
        try:
            self.serial = serial.Serial(
                port=self.address,
                baudrate=self.baudrate,
                timeout=self.timeout,
                **self.kwargs
            )
            if not self.serial.is_open:
                self.serial.open()
        except Exception as e:
            self.disconnect()
            raise ConnectionError(f"Failed to open serial connection to LBTEK at '{self.address}': {e}")

    def disconnect(self) -> None:
        if self.serial:
            try:
                if self.serial.is_open:
                    self.serial.close()
            except Exception:
                pass
            self.serial = None

    def _query(self, command: str) -> str:
        """Helper to send a command and read a line back."""
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Device is not connected. Call connect() first.")
        
        try:
            full_cmd = f"{command}{self.write_termination}"
            self.serial.write(full_cmd.encode('ascii'))
            
            # Read until the termination string or timeout
            response_bytes = bytearray()
            term_bytes = self.read_termination.encode('ascii')
            
            while True:
                char = self.serial.read(1)
                if not char:
                    # Timeout reached
                    break
                response_bytes.extend(char)
                if response_bytes.endswith(term_bytes):
                    break
                    
            response = response_bytes.decode('ascii').strip()
            return response
        except Exception as e:
            raise RuntimeError(f"Serial communication error during query '{command}': {e}")

    def get_power(self) -> float:
        response = self._query(self.read_command)
        if not response:
            raise RuntimeError("No response received from LBTEK device.")
        try:
            # Attempt to parse float. Some devices return prefix/units,
            # so we handle typical numbers.
            # E.g., if response is "1.234e-3 W" or "1.234", we strip alpha characters.
            cleaned = "".join(c for c in response if c.isdigit() or c in ".eE+-")
            return float(cleaned)
        except ValueError as e:
            raise RuntimeError(f"Could not parse power reading '{response}' as float: {e}")

    def get_info(self) -> str:
        try:
            info = self._query(self.idn_command)
            if info:
                return info
        except Exception:
            pass
        return f"LBTEK Power Meter on {self.address}"

    def set_wavelength(self, wavelength: float) -> None:
        """
        Set wavelength. Standard command for serial meters is often 'WAV <nm>' or 'SENS:WAV <nm>'.
        We attempt to send 'WAV <wavelength>' by default.
        """
        cmd = f"WAV {wavelength}"
        try:
            self.serial.write(f"{cmd}{self.write_termination}".encode('ascii'))
        except Exception as e:
            raise RuntimeError(f"Failed to set wavelength over serial: {e}")

    def get_wavelength(self) -> float:
        """
        Get wavelength. Standard command is often 'WAV?' or 'SENS:WAV?'.
        """
        try:
            response = self._query("WAV?")
            cleaned = "".join(c for c in response if c.isdigit() or c in ".eE+-")
            return float(cleaned)
        except Exception as e:
            raise RuntimeError(f"Failed to query wavelength over serial: {e}")

    @staticmethod
    def list_devices() -> list:
        """Helper to scan and list available Serial COM ports."""
        if not serial_available:
            return []
        try:
            ports = serial.tools.list_ports.comports()
            return [p.device for p in ports]
        except Exception:
            return []
