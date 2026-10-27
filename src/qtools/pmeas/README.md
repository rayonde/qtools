# Polarization Measurement Library

Python library and CLI for automated polarization measurement using Thorlabs K10CR1 rotation stages and photon-counting TDCs or power meters.

---

## Physical Principle

A half-wave plate (HWP) on a rotation stage is followed by a polarizing beam splitter (PBS) that transmits H-polarized light to a detector. The transmitted intensity follows Malus's law:

$$I(\theta) = A + B \cos\bigl(4(\theta - \theta_0)\bigr)$$

Fitting this curve yields the calibration parameters needed to set the HWP to any desired polarization basis (H, V, D, A).

For entanglement, two such setups (Alice & Bob) are used. The CHSH Bell parameter S is computed from four correlation coefficients between the two sides.

---

## Installation

```bash
pip install -e /path/to/qtools.motor
pip install -e .
```

---

## Configuration

Motors and detectors are auto-detected and managed through the `ConfigManager`. Registered devices are stored in `polmeas_config.yaml` and synced to the motor drivers.

```bash
# View config summary and registered devices
pmeas config show
```

Device registration happens automatically during calibration or can be initialized manually.

---

## CLI

```bash
pmeas --help
```

### `calibrate` — Waveplate Calibration

Scans the HWP/QWP, fits the Malus-law curve, verifies H↔V extinction, and saves parameters.

| Option            | Default     | Description                        |
|-------------------|-------------|------------------------------------|
| `--hwp`           | —           | Calibrate HWP (default)            |
| `--qwp`           | —           | Calibrate QWP                      |
| `--achromatic`    | —           | Multi-wavelength calibration       |
| `--duration`      | 1.0         | Integration time per point (s)     |
| `--sample`        | 10          | Measurements per angle             |
| `--mock`          | —           | Simulation mode (no hardware)      |
| `--raw`           | —           | Save raw measurement data to file  |

```bash
# Run a mock HWP calibration (no hardware needed)
pmeas calibrate --mock --sample 2

# Real calibration on an auto-detected/configured motor
pmeas calibrate
```

### `scan coincidence` — Polarization Correlation Scan

Fixes Alice at each basis (H, V, D, A), sweeps Bob's HWP, and records coincidences.

```bash
# Sweep Bob's angle in mock mode
pmeas scan coincidence --mock --start 0 --end 180 --step 10
```

### `scan chsh` — CHSH Bell Offset Scan

Scans Bob's basis offset β and computes the CHSH S parameter.

```bash
# Sweep CHSH offset angle in mock mode
pmeas scan chsh --mock --start 0 --end 90 --step 5
```

### `chsh` — Full Characterization, Optimization & Drift Monitoring

Runs the full characterization workflow, optimizes basis alignments, or tracks drift over time.

| Option       | Description                                           |
|--------------|-------------------------------------------------------|
| (none)       | Run full characterization (Coincidence + Bell scans)  |
| `--optimize` | Run 2-D coordinate descent to maximize |S|            |
| `--live`     | Monitor |S| and re-optimize when it drifts below a threshold |

```bash
# Run full characterization in mock mode
pmeas chsh --mock

# Optimize Alice/Bob basis alignments
pmeas chsh --optimize --mock

# Monitor drift and dynamically correct zero offsets
pmeas chsh --live --mock
```

---

## Python API

The recommended way to interact programmatically with the system is through the orchestrator `PolarizationMeasurementController` context manager, which handles device lifecycles and configuration files cleanly.

```python
from qtools.pmeas.api import PolarizationMeasurementController

# Run a waveplate calibration scan under mock simulation
with PolarizationMeasurementController(mock=True) as ctrl:
    result = ctrl.calibrate(
        role="hwp",
        channel=0,
        start_angle=0.0,
        end_angle=180.0,
        step_angle=5.0,
        repetitions=2,
    )
    print(f"Fitted HWP offset θ₀ = {result['theta_0']:.4f}°")
    print(f"Fitted visibility = {result['visibility']:.4f}")
    
    # Target angles for H/V/D/A bases
    for basis, angle in result["target_angles"].items():
        print(f"  {basis}: {angle:.4f}°")
```

---

## Project Structure

```
qtools.pmeas/
├── pyproject.toml
├── polmeas_config.yaml         # Config registry (devices, calibrations, setups)
├── src/qtools.pmeas/
│   ├── __init__.py
│   ├── _path.py                # Path resolver helper
│   ├── cli.py                  # CLI subcommand parser and handlers
│   ├── config.py               # ConfigManager class
│   ├── meas_manager.py         # MeasManager & MockMeasManager classes
│   ├── motor_manager.py        # MotorManager class (caches Alice/Bob stage connections)
│   ├── calibration.py          # Waveplate calibration logic and verification
│   ├── entanglement.py         # Coincidence sweeps and Bell scans
│   ├── optimize.py             # Basis coordinate descent & drift correction loop
│   ├── achromatic.py           # Achromatic dispersion calibration
│   ├── api.py                  # PolarizationMeasurementController high-level orchestrator
│   ├── backends/
│   │   ├── __init__.py         # Exports MotorBackend facade
│   │   ├── motor.py            # MotorBackend facade wrapping real/mock stages
│   │   └── mockmotor.py        # MockMotor simulation stage
│   └── analysis/
│       ├── fit.py              # Least-squares fit and correlation analytics
│       └── jones.py            # Jones calculus math and angle computation
└── output/                     # Generated plots (.png) and raw data (.npz)
```
