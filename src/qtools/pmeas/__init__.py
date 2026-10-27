"""qtools.pmeas — Polarization measurement and waveplate calibration.

Provides:
* MeasController: High-level programmatic controller
* ConfigManager, MotorManager, MeasManager: Core manager components
* Calibration, entanglement scan, and basis optimization functions
"""

from qtools import __version__ as __version__

from qtools.pmeas.api import MeasController, TaskController
from qtools.pmeas.config import ConfigManager
from qtools.pmeas.motor_manager import MotorManager
from qtools.pmeas.meas_manager import MeasManager
from qtools.pmeas.calibration import run_calibration, run_achromatic_calibration
from qtools.pmeas.entanglement import run_singles_scan, run_coincidence_scan, run_bell_scan, load_coincidence_csv
from qtools.pmeas.optimization import optimize_basis, run_live_correction
from qtools.pmeas.analysis.correlation import get_correlation

__all__ = [
    "TaskController",
    "MeasController",
    "ConfigManager",
    "MotorManager",
    "MeasManager",
    "run_calibration",
    "run_achromatic_calibration",
    "run_singles_scan",
    "run_coincidence_scan",
    "run_bell_scan",
    "load_coincidence_csv",
    "optimize_basis",
    "run_live_correction",
    "get_correlation",
]
