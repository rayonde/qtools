from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "k10cr1"
_BACKEND_REGISTRY: dict[str, type] = {}


def list_devices(backend: str | type = DEFAULT_BACKEND) -> list[tuple[str, str]]:
    """Scan and return [(port, label), ...] for devices supported by *backend*."""
    backend_cls = backend if isinstance(backend, type) else get_backend_class(str(backend))
    if hasattr(backend_cls, "list_devices"):
        return backend_cls.list_devices()
    return []



def register_backend(name: str):
    """Decorator to register a hardware backend class under a backend identifier."""
    def decorator(cls: type):
        _BACKEND_REGISTRY[name.lower()] = cls
        return cls
    return decorator


def get_backend_class(name: str = DEFAULT_BACKEND) -> type:
    """Retrieve registered backend class by name."""
    if name.lower() not in _BACKEND_REGISTRY:
        _ensure_builtin_backends()
    key = name.lower()
    if key not in _BACKEND_REGISTRY:
        raise ValueError(
            f"Unknown motor backend '{name}'. Available backends: {list(_BACKEND_REGISTRY.keys())}"
        )
    return _BACKEND_REGISTRY[key]


def _ensure_builtin_backends() -> None:
    try:
        import qtools.motor.backends.k10cr1.stage  # noqa: F401
    except ImportError:
        pass


class MotorBackend:
    """Universal Facade class for stepper motor backends.

    Wraps a concrete hardware backend (e.g. K10CR1Backend) and delegates all
    motor control operations to it.

    Parameters
    ----------
    port : str, optional
        Serial port path (e.g. '/dev/ttyUSB0', 'COM3').
    blocking : bool, default True
        Whether move/home commands block until complete.
    name : str, optional
        Human-readable label for this device (e.g. 'alice', 'bob').
    serial_no : str, optional
        Hardware serial number used as a stable device key.
    backend : str or type, default 'k10cr1'
        Backend identifier string (e.g. 'k10cr1') or concrete backend class.
    stage_impl : Any, optional
        Pre-existing concrete backend instance.
    """

    def __init__(
        self,
        port: str = "",
        blocking: bool = True,
        name: str = "",
        serial_no: str = "",
        backend: str | type = DEFAULT_BACKEND,
        config_mgr: Any = None,
        stage_impl: Any = None,
        **kwargs: Any,
    ) -> None:
        self._port = port
        self._blocking = blocking
        self.name = name or ""
        self._serial_hint = str(serial_no or "")
        self._config_mgr = config_mgr
        if stage_impl is not None:
            self._impl = stage_impl
        else:
            if isinstance(backend, type):
                backend_cls = backend
            else:
                backend_cls = get_backend_class(str(backend))
            self._impl = backend_cls(port=port, blocking=blocking, config_mgr=config_mgr, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if "_impl" in self.__dict__ and self._impl is not None:
            return getattr(self._impl, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @property
    def impl(self) -> Any:
        """Underlying concrete backend instance."""
        return self._impl

    @property
    def serial(self) -> str:
        """Hardware serial number; reads from impl first, falls back to constructor hint."""
        if self._impl is not None:
            val = getattr(self._impl, "_serial_no", None) or getattr(self._impl, "serial", None)
            if val not in (None, "", 0):
                return str(val)
        return self._serial_hint

    @serial.setter
    def serial(self, value: str) -> None:
        self._serial_hint = str(value or "")

    @property
    def is_connected(self) -> bool:
        """Return whether physical connection is currently active."""
        if self._impl is not None:
            if hasattr(self._impl, "is_connected"):
                return bool(self._impl.is_connected)
            motor_attr = getattr(self._impl, "_motor", None)
            if motor_attr is not None and getattr(motor_attr, "_com", None) is not None:
                return bool(motor_attr._com.is_open)
        return False

    def check_connection(self) -> bool:
        """Check whether physical connection is active."""
        return self.is_connected

    def connect(self) -> bool:
        """Establish connection to physical device."""
        if self._impl is not None:
            return bool(self._impl.connect())
        return False

    def disconnect(self) -> None:
        """Disconnect from physical device."""
        if self._impl is not None:
            self._impl.disconnect()

    def __enter__(self) -> MotorBackend:
        if not self.connect():
            logger.error(
                "Failed to connect to motor '%s' on port '%s'. Check USB cable and power.",
                self.name or self.serial or "unknown",
                self._port or "auto",
            )
            raise ConnectionError(f"Failed to connect motor on port '{self._port or 'auto'}'")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect()

    def get_position(self) -> float:
        """Return current position/angle in degrees."""
        if self._impl is not None:
            return float(self._impl.get_position())
        return 0.0

    def move_to(self, position: float) -> None:
        """Move to absolute target position in degrees."""
        if self._impl is not None:
            self._impl.move_to(position)

    def move_by(self, displacement: float) -> None:
        """Move by a relative displacement in degrees."""
        if self._impl is not None:
            self._impl.move_by(displacement)

    def home(self) -> None:
        """Move motor to home position."""
        logger.info("Homing motor '%s'...", self.name or self.serial or "unknown")
        if self._impl is not None:
            self._impl.home()

    def zero(self) -> None:
        """Move to software zero (0.0°)."""
        if self._impl is not None:
            self._impl.zero()

    def wait_move(self) -> None:
        """Block until current movement completes."""
        if self._impl is not None:
            self._impl.wait_move()

    def stop(self) -> None:
        """Stop motor movement."""
        if self._impl is not None:
            self._impl.stop()

    def set_zero_offset(self, offset_deg: float | None = None) -> None:
        """Set software zero offset in degrees."""
        if self._impl is not None:
            self._impl.set_zero_offset(offset_deg)

    def get_velocity(self) -> float:
        """Return velocity setting in deg/s."""
        if self._impl is not None:
            return float(self._impl.get_velocity())
        return 0.0

    def set_velocity(self, speed_deg_s: float) -> None:
        """Set velocity in deg/s."""
        if self._impl is not None:
            self._impl.set_velocity(speed_deg_s)

    def get_stage_name(self) -> str:
        """Return descriptive name of the stage/backend."""
        if self._impl is not None:
            return str(self._impl.get_stage_name())
        if self.name:
            return self.name
        return "MotorBackend (uninitialized)"
