"""Spatial light modulator control and phase-mask generation."""

from qtools.slm.backends import get_backend, list_backends
from qtools.slm.display import DisplayInterface, DisplayMask, HeadlessDisplay, QtDisplay
from qtools.slm.luts import generate_linear_lut, read_lut, validate_lut, write_lut
from qtools.slm.monitor import MonitorBinding, MonitorInfo, list_monitors, resolve_monitor
from qtools.slm.phase import PhaseMask, PhaseRegion
from qtools.slm.slm import SLM, SLMGeometry

__all__ = [
    "DisplayInterface",
    "DisplayMask",
    "HeadlessDisplay",
    "MonitorBinding",
    "MonitorInfo",
    "PhaseMask",
    "PhaseRegion",
    "QtDisplay",
    "SLM",
    "SLMGeometry",
    "generate_linear_lut",
    "get_backend",
    "list_backends",
    "list_monitors",
    "read_lut",
    "resolve_monitor",
    "validate_lut",
    "write_lut",
]
