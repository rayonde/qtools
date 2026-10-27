from __future__ import annotations
import logging
import inspect
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "mock"
_BACKEND_REGISTRY: dict[str, type] = {}


def register_backend(name: str):
    """Decorator to register a power meter backend class under a backend identifier."""
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
        available = list(_BACKEND_REGISTRY.keys())
        raise ValueError(
            f"Unknown powermeter backend '{name}'. Available backends: {available}"
        )
    return _BACKEND_REGISTRY[key]


def list_available_backends() -> list[str]:
    """Return list of all registered backend names."""
    _ensure_builtin_backends()
    return list(_BACKEND_REGISTRY.keys())


def _ensure_builtin_backends() -> None:
    for mod in (
        "qtools.powermeter.backends.thorlabs.thorlabs",
        "qtools.powermeter.backends.lbtek.lbtek",
        "qtools.powermeter.backends.s15.s15",
        "qtools.powermeter.backends.mock.mock",
    ):
        try:
            __import__(mod)
        except ImportError:
            pass


class PowerMeter:
    """Universal Facade class for power meter backends.

    Wraps a concrete hardware backend (e.g. ThorlabsPowerMeter, S15PowerMeter, MockPowerMeter)
    and delegates power meter operations to it.

    Parameters
    ----------
    port : str, optional
        Resource address or port (e.g. 'COM3', 'USB0::0x1313::...', 'MOCK0').
    backend : str or type, default 'mock'
        Backend identifier string or concrete backend class.
    name : str, optional
        Human-readable label for this device.
    pm_impl : Any, optional
        Pre-existing concrete backend instance.
    """

    def __init__(
        self,
        port: str = "",
        backend: str | type = DEFAULT_BACKEND,
        name: str = "",
        pm_impl: Any = None,
        **kwargs: Any,
    ) -> None:
        self._port = port
        self.name = name or ""
        if pm_impl is not None:
            self._impl = pm_impl
        else:
            if isinstance(backend, type):
                backend_cls = backend
            else:
                backend_cls = get_backend_class(str(backend))
            
            sig = inspect.signature(backend_cls.__init__)
            params = sig.parameters
            if "address" in params and "port" not in params:
                self._impl = backend_cls(address=port, **kwargs)
            elif "port" in params and "address" not in params:
                self._impl = backend_cls(port=port, **kwargs)
            else:
                try:
                    self._impl = backend_cls(port, **kwargs)
                except TypeError:
                    self._impl = backend_cls(address=port, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if "_impl" in self.__dict__ and self._impl is not None:
            return getattr(self._impl, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @property
    def impl(self) -> Any:
        """Underlying concrete backend instance."""
        return self._impl

    @property
    def auto_range(self) -> bool:
        """Whether auto-ranging is active."""
        if self._impl is not None and hasattr(self._impl, "auto_range"):
            return bool(self._impl.auto_range)
        return True

    @auto_range.setter
    def auto_range(self, value: bool) -> None:
        if self._impl is not None and hasattr(self._impl, "auto_range"):
            self._impl.auto_range = bool(value)

    def connect(self) -> Any:
        """Establish connection to the power meter device."""
        if self._impl is not None:
            return self._impl.connect()
        return None

    def disconnect(self) -> None:
        """Close connection to the power meter device."""
        if self._impl is not None:
            self._impl.disconnect()

    def get_power(self) -> float:
        """Read the instantaneous power in Watts."""
        if self._impl is not None:
            return float(self._impl.get_power())
        return 0.0

    def get_info(self) -> str:
        """Return description or identifier of the device."""
        if self._impl is not None:
            return str(self._impl.get_info())
        return self.name or "PowerMeter (uninitialized)"

    def set_wavelength(self, wavelength: float) -> None:
        """Set calibration wavelength in nanometers."""
        if self._impl is not None:
            self._impl.set_wavelength(wavelength)

    def get_wavelength(self) -> float:
        """Get current calibration wavelength in nanometers."""
        if self._impl is not None:
            return float(self._impl.get_wavelength())
        return 0.0

    def set_range(self, range_val: float | None) -> None:
        """Set power range in Watts, or configure auto-ranging."""
        if range_val is None:
            return  # auto-range — backend handles None gracefully or no-op
        if self._impl is not None:
            self._impl.set_range(range_val)

    def get_range(self) -> float:
        """Get current power range in Watts or range index."""
        if self._impl is not None:
            return self._impl.get_range()
        return 0.0

    def __enter__(self) -> PowerMeter:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect()
