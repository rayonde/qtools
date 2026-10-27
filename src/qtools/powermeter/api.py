"""Convenience API for the powermeter package."""

from qtools.powermeter.connection import get_device
from qtools.powermeter.measurement import measure_power


def measure(
    address: str = "",
    backend: str = "",
    wavelength: float = 1550.0,
    range_val: float = None,
    duration: float = 0.5,
    samples: int = 10,
) -> tuple:
    """Auto-detect, connect, configure, and return ``(mean, std_dev)``.

    Args:
        address: Device address.  If empty, auto-detects connected hardware.
        backend: Power meter backend (``'s15'``, ``'thorlabs'``,
            ``'lbtek'``, ``'mock'``).  If empty, auto-detects.
        wavelength: Operating wavelength in nm (default: 1550.0).
        range_val: Manual range setting.  ``None`` = auto-ranging.
        duration: Measurement duration in seconds (default: 0.5).
        samples: Number of sample points (default: 10).

    Returns:
        A tuple of ``(mean_power_watts, std_deviation_watts)``.
    """
    port = address or None                  # "" / None both mean auto-discover
    backend = backend or None

    device = get_device(backend, port)
    with device:
        if wavelength is not None:
            device.set_wavelength(wavelength)
        try:
            device.set_range(range_val)
        except NotImplementedError:
            pass
        return measure_power(
            device=device,
            duration=duration,
            samples=samples,
        )
