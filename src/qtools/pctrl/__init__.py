"""qtools.pctrl — Polarization controller, calibration, and optimization."""

from qtools import __version__ as __version__

from qtools.pctrl.api import PolarizationController
from qtools.pctrl.optimize import OptimizeResult
from qtools.pctrl.config import (
    channel_key_string,
    parse_channel_key,
    resolve_target,
    TargetResolution,
)

__all__ = [
    "PolarizationController",
    "OptimizeResult",
    "channel_key_string",
    "parse_channel_key",
    "resolve_target",
    "TargetResolution",
]
