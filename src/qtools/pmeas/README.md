# Polarization Measurement (`qtools.pmeas`)

Python API and CLI for waveplate calibration, polarization correlation scans,
and CHSH measurements. Motor stages, TDCs, and power meters use the corresponding
`qtools.motor`, `qtools.tdc`, and `qtools.powermeter` modules.

## Installation

Install from the **qtools repository root**:

```bash
pip install -e .
# Or:
uv sync
```

Dependencies, including `lmfit` for calibration fitting, are managed in the root
`pyproject.toml`. There is no separate package installation for this module.

## CLI

```bash
pmeas --help
python -m qtools.pmeas --help
```

The previous `polmeas` command remains an alias for `pmeas`. Existing configuration
files retain the name `polmeas_config.yaml`; use `--config PATH` to select a file.
Run commands from the experiment directory so configuration and output files are
stored outside the installed package.

```bash
# Inspect configuration and available commands
pmeas config show
pmeas motor --help
pmeas calibrate --help
pmeas scan --help

# Calibrate a waveplate with configured hardware
pmeas calibrate hwp
pmeas calibrate qwp
pmeas calibrate achromatic --role hwp

# Polarization scans with configured motor stages and detectors
pmeas scan singles --start 0 --end 180 --step 10
pmeas scan pairs --start 0 --end 180 --step 10
pmeas scan chsh --start 0 --end 90 --step 5

# Characterization, alignment optimization, and drift monitoring
pmeas chsh
pmeas chsh --optimize
pmeas chsh --live
```

Measurement commands require configured, connected hardware. Unit tests use
fake devices and do not require laboratory instruments.

## Configuration and multi-stage control

`pmeas config` runs the full polarization-measurement wizard. It prompts for the
experiment name and author, scans TDC and power-meter connections, then configures
every discovered motor independently. Multiple stages may share one optical path
(for example an Alice HWP and Alice QWP); each physical serial number receives a
unique id and a distinct name.

```bash
pmeas config                 # Configure experiment, detectors, and motors
pmeas config show            # Show ids, names, optical paths, and detectors
pmeas list                   # Show connected/offline configured motors
pmeas status                 # Show every motor with bases and live angle
pmeas motor status           # Same full multi-motor status view
```

When an optical path contains multiple stages, use a qualified selector such as
`alice:hwp`, `alice:qwp`, or the full configured name:

```bash
pmeas motor move to alice:hwp 22.5
pmeas motor move to alice:qwp 45
pmeas motor move to alice_547_basis_qwp 45 --backend k10cr1
pmeas motor move 2 to 30     # numeric target is the config id, backend is selected automatically
pmeas motor home            # Home every connected motor
pmeas motor home 2          # Home only config id 2

KDC101 and K10CR1 stage defaults use 40 deg/s; `--speed` overrides it per command.
```

Bare group names such as `alice` are rejected when more than one device uses that
path, preventing accidental control of the first matching stage.
Device basis maps always contain `H`, `V`, `D`, `A`, `R`, and `L`.
New configurations initialize all six basis angles to `0`. Afterwards, basis
angles are read from `polmeas_config.yaml` and are never recomputed from
`theta_0` or the waveplate type during config loading or saving. A missing basis
key is initialized to `0`; explicitly configured values are preserved.

This models the QWP-then-HWP basis structure while allowing each stage to be
calibrated independently.
## Python API

`TaskController` manages configuration, motor connections, and measurement tasks.
`MeasController` is an alias for the same class.

```python
from qtools.pmeas import TaskController

# Uses motors and detectors registered in the selected configuration file.
with TaskController(config_path="polmeas_config.yaml") as ctrl:
    result = ctrl.calibrate(
        waveplate="hwp",
        channel=0,
        start_angle=0.0,
        end_angle=180.0,
        step_angle=5.0,
        repetitions=2,
    )
    print(result)
```

Lower-level managers and functions are available from `qtools.pmeas`, including
`ConfigManager`, `MotorManager`, `MeasManager`, `run_calibration`,
`run_achromatic_calibration`, `run_singles_scan`, `run_coincidence_scan`,
`run_bell_scan`, `optimize_basis`, and `run_live_correction`.

## Structure

```text
src/qtools/pmeas/
├── __init__.py             # Public API exports
├── __main__.py             # python -m qtools.pmeas
├── api.py                  # TaskController and MeasController exports
├── cli.py                  # pmeas command and motor CLI delegation
├── commands/               # Calibration, scan, configuration, CHSH handlers
├── config.py               # Configuration and archive management
├── meas_manager.py         # Detector readout and task controller
├── motor_manager.py        # Motor connection management
├── calibration.py          # Waveplate calibration
├── entanglement.py         # Polarization and Bell scans
├── optimization.py         # Basis optimization and drift correction
├── backends/motor.py       # qtools.motor integration
└── analysis/               # Jones calculus, curve fitting, correlations

tests/pmeas/                # Tests run from the qtools repository root
```

## Tests

```bash
pytest tests/pmeas/
```
