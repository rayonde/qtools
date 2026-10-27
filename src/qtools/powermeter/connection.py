from typing import List, Optional
from qtools.powermeter.backends.powermeter import PowerMeter, get_backend_class, list_available_backends as _list_backends


def auto_detect_connected_device() -> tuple:
    """Scan and find the first connected S15, Thorlabs, or LBTEK device."""
    from qtools.powermeter.backends.thorlabs import ThorlabsPowerMeter
    from qtools.powermeter.backends.lbtek import LBTekPowerMeter
    from qtools.powermeter.backends.s15 import S15PowerMeter

    # 1. Search S15 devices
    s15_ports = S15PowerMeter.list_devices()
    if s15_ports:
        return s15_ports[0], "s15"

    # 2. Search Thorlabs VISA devices
    thor_devices = ThorlabsPowerMeter.list_devices()
    if thor_devices:
        return thor_devices[0], "thorlabs"

    # 3. Search LBTEK devices (filtering by description/manufacturer keywords)
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            desc = (p.description or "").lower()
            mfg = (p.manufacturer or "").lower()
            if "lbtek" in desc or "lbtek" in mfg:
                return p.device, "lbtek"
    except Exception:
        pass

    return None, None


def get_device(backend: Optional[str] = None, port: Optional[str] = None, **kwargs) -> PowerMeter:
    """
    Connection helper function to get a power meter facade instance.

    Args:
        backend: Name of the backend ('thorlabs', 'lbtek', 's15', 'mock').
            If empty/None, auto-detects the first connected device.
        port: Device address (e.g. COM port, VISA resource, etc.). If None,
            the backend handles auto-discovery internally.
        **kwargs: Extra parameters passed to the backend constructor.

    Returns:
        PowerMeter: A PowerMeter facade instance for the requested backend.
    """
    if not backend:
        detected_port, detected_backend = auto_detect_connected_device()
        if detected_backend:
            backend = detected_backend
            port = port or detected_port
        else:
            backend = "mock"
            port = port or "MOCK0"

    backend_cls = get_backend_class(backend)
    return PowerMeter(port=port or "", backend=backend_cls, **kwargs)


def list_available_backends() -> List[str]:
    """
    Get a list of all registered backend names.

    Returns:
        List[str]: Available backend names.
    """
    return _list_backends()
