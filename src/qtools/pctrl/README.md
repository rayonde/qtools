# Polarization Controller (`pctrl`)

A Python-based laboratory instrumentation and control package for a three-waveplate polarization controller system (Quarter Waveplate - Half Waveplate - Quarter Waveplate, or QWP - HWP - QWP). This system utilizes Feetech serial command bus servos (SCServo), integrates with optical power meters and Time-to-Digital Converters (TDCs), and offers a graphical user interface (GUI) alongside a rich interactive CLI.

---

## Codebase Structure

A high-level overview of the Python package structure is shown below:

```text
src/qtools/pctrl/
├── __init__.py                 # Public Python API
├── __main__.py                 # python -m qtools.pctrl
├── README.md
├── backends/                   # Servo drivers and bundled SDKs
├── analysis/                   # Polarization modeling, fitting, and plotting
├── api.py                      # PolarizationController
├── calibration.py
├── cli.py                      # pctrl command
├── config.py                   # YAML configuration management
├── joint_optimize.py           # Thin two-channel wrapper around optimize.py
├── loops.py
├── meas_manager.py             # qtools.powermeter / qtools.tdc integration
├── optimize.py
├── repl.py
├── servo_manager.py
└── utils.py

tests/pctrl/                   # Tests, run from the qtools repository root
```

---

## Installation & Setup

### Requirements
- **Python**: version `3.10` or higher is required.
- **Hardware Interface**: A USB-to-RS485 adapter (to communicate with SCServo bus) and Feetech serial servos (e.g., SMS/STS series).

### Install Dependencies
Install qtools from the repository root; dependencies and the `pctrl` command are managed by the root `pyproject.toml`:

```bash
pip install -e .
```

Or use `uv sync`. You can also invoke the CLI as `python -m qtools.pctrl`.
Hardware integration uses `qtools.tdc` and `qtools.powermeter` from the same installation.

---

## Initial Configuration

To configure the communication parameters (serial port, baud rate) and discover the connected servos, run the interactive channel configuration setup:

```bash
pctrl init
```

The setup will:
1. Scan for available serial ports.
2. Scan the bus IDs using the default baud rate (`1,000,000` bps, or custom baud rate if specified via options) (can perform a `--full-scan` of all 253 possible IDs).
3. Prompt you for each discovered servo's details (waveplate type, slot index, path name, wavelength) and auto-generate standard servo identifiers (e.g. `alice1550_qwp_1`, `alice1550_hwp_2`, `alice1550_qwp_3`).
4. Save the configuration to `polarization_config.yaml`.

---

## Command Line Interface (CLI)

The command-line launcher `pctrl` provides unified positional subcommands to query status, initialize channels, scan online devices, and control servos.

### Global Options

* `-h, --help`: Show help menu and exit.
* `-c PATH, --config PATH`: Config file path (default: `polarization_config.yaml`).
* `-p PORT, --port PORT`: Specify serial port (e.g. `COM3` or `/dev/ttyUSB0`).
* `-b RATE, --baud RATE`: Baud rate (default: `1000000`).
* `-t TYPE, --type TYPE`: Specify servo type: `scs` or `sts` (default: read from config or `sts`).
* `-m, --mock`: Run in mock/simulation mode without physical hardware connected (can be placed anywhere on the command line, e.g. `pctrl status --mock` or `pctrl --mock status`).

### Subcommands

The available subcommands are grouped below by functional category:

#### 1. Setup & Diagnostics

##### `init`
Run the interactive setup to scan and configure channels. Auto-loads config if it already exists, otherwise queries user for setup and creates it.
```bash
pctrl init [--full-scan]
```

##### `list`
Scan for online servos and list their IDs.
```bash
pctrl list [--full-scan]
```

##### `status`
Display communication settings and print a detailed servo status table.
```bash
pctrl status [target]
```
* `target` (optional): Can be a servo name, ID, or a port (e.g. `COM3` or `/dev/ttyUSB0`) to override the connection port.

##### `device`
Connect/scan Powermeters or TDCs and auto-save settings to config.
```bash
pctrl device <powermeter|tdc> [device_args ...]
```

#### 2. Interactive & Utilities

##### `repl`
Force start the interactive REPL console.
```bash
pctrl repl
```

##### `loops`
Calculate required fiber loops for QWP and HWP retardations given the wavelength and fiber details.
```bash
pctrl loops --wavelength 1550 --diameter 18 --cladding 900
```

#### 3. Manual & Hardware Control

##### `get`
Query physical and waveplate angles of target.
```bash
pctrl get [target]
```

##### `set`
Set physical or waveplate angle for target.
```bash
pctrl set <target> [angle] [-s SPEED]
```
* Supports setting multiple targets (e.g. `pctrl set 1,2,3 45` to set all to 45°, or `pctrl set 1,2,3 45,90,135` for different angles).
* `-s SPEED, --speed SPEED`: Optional speed limit in degrees/second.
* `-o, --overshoot`: For a nonzero move smaller than 3°, first move a large
  angle, then return to the target. Uses the existing 150-encoder-count
  offset (about 44° on SCS or 13° on STS), within the configured limits.
  Each leg waits for encoder arrival before continuing.

If 1–2° commands update the target but the encoder does not move, first read
the firmware deadband with `pctrl threshold <servo_name>`. One encoder count
is approximately 0.293° on SCS and 0.088° on STS. A large deadband or static
friction can prevent small commands from producing motion. Changing the
threshold, for example `pctrl threshold <servo_name> 2`, writes both CW/CCW
values to EEPROM; choose a value supported by the servo and check for jitter
or heating. Extra sleep alone does not remove deadband.

Overshoot is explicitly enabled with the existing CLI option or a Python
API parameter; it defaults to off:

```bash
pctrl set -o alice1550_qwp_1 2
pctrl optimize alice --overshoot
```

```python
controller.set_angles("alice1550_qwp_1", 2, overshoot=True)
controller.optimize("alice", overshoot=True)
```

The trigger uses the current encoder position converted to degrees using
the servo's `deg_per_step`. The first leg prefers moving away from the
target, falling back to the other direction near a limit. If neither
direction has room for 150 counts, it sends the target directly, matching
the existing CLI behavior. No extra movement is added for zero displacement
or moves of 3° or more.

Optimization and calibration verify the final encoder position before
measurement. A stopped status with an encoder error over two counts now
times out with actual and target values. Overshoot manual commands also
wait for final arrival. Two counts are about 0.59° on SCS or 0.18° on STS.
Encoder feedback does not detect slip or backlash downstream of the servo
sensor.

##### `reset` (alias: `zero`, `middle`)
Reset target servos (default: `all`) to their configured middle positions.
```bash
pctrl reset [target]
```

##### `set-zero` (alias: `set-middle`)
Force specify current position as zero/middle for target.
```bash
pctrl set-zero [target]
```

##### `limit`
Set angle limits for target and persist them to the servo EEPROM.
```bash
pctrl limit [target] [min max]
```

##### `torque`
Control motor torque locks.
```bash
pctrl torque <on|off|enable|disable|lock|release> [target]
```

##### `set-id`
Change servo ID on the bus (works only if a single servo is connected or both old and new IDs are specified).
```bash
pctrl set-id <new_id>
pctrl set-id <old_id> <new_id>
```

#### 4. Calibration & Optimization

##### `calibrate` (alias: `cal`)
Run waveplate calibration sweep for target.
*   `--basis <h/v/d/a>` (Required): Specify the measurement polarization basis.
*   `--plot` (Optional): Plot and save calibration fit, verification, and Bloch sphere figures.
*   `--fast` (Optional): Run high-speed calibration (larger step size, lower integration time).
```bash
pctrl calibrate [target] --basis <h/v/d/a> [--plot] [--fast]
```

##### `optimize` (alias: `opt`)
Optimize waveplate angles to maximize or minimize TDC singles on a selected channel using noise-aware Nelder-Mead hill climbing (no full parameter scan).
*   `--measure singles` (Optional): Measurement type to optimize (default: `singles`).
*   `--channel <n>` (Optional): 1-based TDC channel to read (default: channel 1).
*   `--time <seconds>` (Optional): TDC integration time per singles sample (default: `0.2`).
*   `--samples <n>` (Optional): Number of singles readings averaged per evaluation (default: `1`; increase only if needed).
*   `--tol <degrees>` (Optional): Nelder-Mead angle convergence tolerance (default: `1.0`).
*   `--maxiter <iterations>` (Optional): Maximum optimization steps (default: `30`).
*   `--minimize` (Optional): Minimize the metric instead of maximizing it.
*   `--maximize` (Optional): Maximize the metric (default behavior).
*   `--save-config` (Optional, alias: `--save`): Save the optimized physical angles back to the config file.
*   `--save-process [filepath]` (Optional): Save step-by-step optimization process history (angles, metric value, loss) to a CSV, JSON, or YAML file (default: `optimize_process_<YYYYMMDD_HHMMSS>.csv`).
*   `--plot` (Optional): Plot and save the convergence history — metric value and servo angles vs evaluation number.
*   `--step-size <degrees>` (Optional): Actual initial simplex edge length in degrees (default: `15.0`).
*   `--initial-angles current|saved|A,B,C` (Optional): Warm start from current angles, the last saved optimum, or an explicit angle list.
*   `--search-radius <degrees>` (Optional): Search half-width around the warm start, clamped to each servo's mechanical limits. Default: full range.
*   `--settle-time <seconds>` (Optional): Settle time in seconds after servos stop moving (default: `0.1`).
```bash
# One call is one optimization stage. Save the coarse result first.
pctrl optimize alice --maximize --step-size 60 --tol 2 --maxiter 40 --save-config
# Refine around the saved coarse optimum.
pctrl optimize alice --maximize --initial-angles saved --search-radius 20 --step-size 10 --tol 0.8 --maxiter 40
# Final polish uses the current angle after the previous call as its warm start.
pctrl optimize alice --maximize --search-radius 6 --step-size 3 --tol 0.3 --maxiter 25 --time 0.5 --samples 3
```


---

## Interactive REPL CLI

Run `pctrl repl` to enter the interactive shell mode. It maintains a persistent serial connection to all background hardware and provides a command prompt:

```text
pctrl> status
```

### Supported Commands in REPL
* `status`: Show connection statuses for Servos, TDC, and Powermeters, and prints the detailed status table.
* `reset` (aliases: `zero`, `middle`): Reset all servos to middle.
* `set_zero <target>` (aliases: `set-zero`, `set-middle`): Set target servo current position as middle/zero.
* `limit <target> [min max]`: Set angle limits for target and persist them to the servo EEPROM.
* `torque <on|off|enable|disable>` / `release` / `lock`: Manage motor torque lock.
* `loops <wavelength> [diameter] [cladding]`: Run retardation calculation.
* `set <target>`: Move servos (e.g., `set alice_1550_qwp_1:45`, `set alice_1550_hwp_2:hwp:10`).
* `get <target>`: Get positions.
* `calibration <target>` / `cal <target>`: Trigger polarization calibration.
* `exit` / `quit`: Cleanly disconnect from all devices and exit REPL.

---

## Mock Mode & Automated Testing

The system supports a mock mode for offline testing. When running in mock mode, serial communication is simulated, local servos are mocked, and the mock Powermeter / TDC values are mathematically coupled with physical waveplate angles to enable closed-loop test runs of calibration routines.

To run the automated tests, run the migrated suite from the qtools repository root:

```bash
pytest tests/pctrl/
```

---

## Programmatic API & Custom Optimization

You can integrate `qtools.pctrl` programmatically in external Python frameworks, scripts, or GUI applications. It exposes a high-level API class `PolarizationController` to control waveplates, query sensors, and optimize alignment.

### Architecture Overview: How `optimize` Works

The optimization engine drives the three servos of a channel and reads TDC singles from the selected channel at each evaluation. Below is the data flow from CLI invocation to hardware convergence:

```
CLI / REPL / Python API
        │
        ▼
┌──────────────────────────────────────────────────┐
│  run_calibration() / optimize_channel()           │   Orchestration layer
│  - Resolves target servos & channels              │
│  - Manages hardware lifecycle (torque, settle)    │
└────────────────────┬─────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌───────────┐ ┌───────────┐ ┌──────────────┐
│ServoMgr   │ │MeasMgr    │ │ metric_fn()  │      Abstraction layer
│move_to()  │ │measure()  │ │ user-supplied│
│get_angle()│ │→ (C,2)    │ │ → float      │
└─────┬─────┘ └─────┬─────┘ └──────────────┘
      │              │
      ▼              ▼
┌──────────┐  ┌─────────────────┐
│SCServo/  │  │Powermeter / TDC │                   Hardware drivers
│STServo   │  │(Thorlabs, IDQ,  │
│(RS-485)  │  │ CIQTek, ...)    │
└──────────┘  └─────────────────┘
```

**Key design decisions:**

| Layer | Responsibility | Extension point |
|---|---|---|
| `optimize_channel()` | One simplex/Nelder-Mead stage with warm start and optional local bounds | `method`, `tol`, `step_size_deg`, `initial_angles`, `search_radius_deg` |
| `hardware_loss(x)` | Move servos → wait settle → measure → return scalar | Closure captures `metric_fn`, `servo_mgr`, `meas_mgr` |
| `read_measurement(meas_mgr)` | Read TDC singles and return channel means | Selected `--channel` |
| `callback(iter, angles, val, raw_data)` | Observe each evaluation in real time | Logging, live plots, abort logic |
| Python API `metric_fn(meas_mgr) → float` | Optional custom scalar for programmatic use | Advanced Python scripts |

### The `metric_fn` Signature

The optimizer calls `metric_fn` **once per hardware evaluation**. It receives the connected `MeasManager` instance and must return a single `float`. The optimizer then feeds this float to `scipy.optimize.minimize` (Nelder-Mead simplex), maximizing or minimizing it.

```
metric_fn(meas_mgr: MeasManager) -> float
```

`MeasManager` provides:
- `.measure(duration, samples, channels) → list[tuple[float, float]]` — raw `(mean, std)` per channel
- Direct access to underlying device objects for advanced queries

### Example 1: CLI with a Custom Metric Module

Create a Python file `my_metrics.py` in your working directory:

```python
# my_metrics.py
from qtools.pctrl.meas_manager import MeasManager

def visibility(meas_mgr: MeasManager) -> float:
    """Compute H/V visibility from two TDC channels.
    Higher visibility = better polarization contrast."""
    data = meas_mgr.measure(duration=0.5, samples=5, channels=[1, 2])
    h_counts = data[0][0]  # channel 1 mean
    v_counts = data[1][0]  # channel 2 mean
    total = h_counts + v_counts
    if total == 0:
        return 0.0
    return abs(h_counts - v_counts) / total
```

The CLI always optimizes TDC singles:

```bash
pctrl optimize alice --measure singles --maximize --channel 1 --time 2
```

The Python API can still pass a custom `metric_fn(meas_mgr) -> float` for advanced programmatic use.

### Example 2: Python API with Progress Callback

```python
from qtools.pctrl import PolarizationController

def print_progress(iteration: int, angles: list[float],
                   metric_val: float, raw_meas):
    print(f"Step {iteration:03d} | angles={angles} | value={metric_val:.4f}")

`optimize()` intentionally performs **one stage only**. Run it multiple times,
using the previous result as the next warm start and shrinking the search radius:

```python
with PolarizationController(config_path="polarization_config.yaml") as ctrl:
    # Coarse search over the full mechanical range.
    coarse = ctrl.optimize(
        target="alice",
        metric_fn=my_metrics.visibility,
        minimize=False,
        maxiter=40,
        tol=2.0,
        step_size_deg=60.0,
        settle_time=0.2,
    )

    # Refine around the coarse optimum.
    fine = ctrl.optimize(
        target="alice",
        metric_fn=my_metrics.visibility,
        minimize=False,
        initial_angles=coarse,          # OptimizeResult is accepted directly
        search_radius_deg=20.0,
        maxiter=40,
        tol=0.8,
        step_size_deg=10.0,
        settle_time=0.2,
    )

    # Final polish; longer integration reduces noise before a tight tolerance.
    final = ctrl.optimize(
        target="alice",
        metric_fn=my_metrics.visibility,
        minimize=False,
        initial_angles=fine.optimal_angles,
        search_radius_deg=6.0,
        maxiter=25,
        tol=0.3,
        step_size_deg=3.0,
        duration=0.5,
        samples=3,
        settle_time=0.2,
    )
    print(f"Optimal angles: {final.optimal_angles}")
    print(f"Best value:     {final.optimal_value}")
```

### Recommended staged parameters

The values below are starting points, not a hard-coded pipeline. Use repeated
measurements to establish the objective noise floor before tightening the final
stage.

| Stage | `initial_angles` | `search_radius_deg` | `step_size_deg` | `maxiter` | `tol` | `duration` | `samples` |
|---|---|---|---:|---:|---:|---:|---:|
| Coarse | current or saved optimum | full range (`None`) | 45-90 | 30-50 | 1.5-2.5 | 0.2-0.5 | 1 |
| Fine | previous result | 20-30 | 10-15 | 30-50 | 0.5-1.0 | 0.5 | 2 |
| Final | previous result | 5-10 | 2-5 | 20-30 | at least one encoder step | 0.5-1.0 | 3-5 |

For SCS servos one encoder step is about `0.2933 deg`; for STS it is about
`0.0879 deg`. A `tol` much smaller than one encoder step only causes extra
measurements without improving the achievable physical angle.

### Example 3: Complex Metric with Stateful Pre-processing

For metrics that need calibration data, reference measurements, or external state, use a factory function pattern or instantiate via the Python API:

```python
# advanced_metrics.py
import numpy as np
from qtools.pctrl.meas_manager import MeasManager

_cal_data = None

def init_concurrence(calibration_path: str):
    """Call once to load calibration data before optimization."""
    global _cal_data
    _cal_data = np.load(calibration_path)

def concurrence(meas_mgr: MeasManager) -> float:
    """Metric function -- called by the optimizer at each simplex vertex."""
    data = meas_mgr.measure(duration=0.3, samples=10, channels=[1, 2, 3, 4])
    counts = np.array([ch[0] for ch in data])
    corrected = counts @ _cal_data
    return float(np.sum(corrected))
```

Programmatic API usage with a stateful callable object:

```python
class ConcurrenceOptimizer:
    def __init__(self, cal_path: str):
        self.cal_data = np.load(cal_path)

    def __call__(self, meas_mgr: MeasManager) -> float:
        data = meas_mgr.measure(duration=0.3, samples=10, channels=[1, 2, 3, 4])
        corrected = np.array([ch[0] for ch in data]) @ self.cal_data
        return float(np.sum(corrected))

with PolarizationController("polarization_config.yaml") as ctrl:
    metric = ConcurrenceOptimizer("calibration.npz")  # instantiate with state
    result = ctrl.optimize(target="alice", metric_fn=metric, maxiter=50)
```

### Optimization Result Object

`optimize_channel()` returns an `OptimizeResult` ([optimize.py:22-43](optimize.py#L22-L43)) which subclasses `list` for backwards compatibility:

| Attribute | Type | Description |
|---|---|---|
| `optimal_angles` | `list[float]` | Best-found waveplate-relative angles |
| `optimal_value` | `float` | Metric value at optimum |
| `success` | `bool` | Whether the optimizer converged |
| `n_iterations` | `int` | Number of simplex iterations |
| `n_evaluations` | `int` | Total hardware evaluations |
| `message` | `str` | Solver termination reason |
| `history` | `list[dict]` | Full history of `{angles, value, evaluation}` |
| `initial_angles` | `list[float]` | Warm start used by this stage |
| `search_bounds` | `list[tuple]` | Bounds used after applying the search radius |
| `step_size_deg` | `float` | Actual simplex step used by this stage |
| `result[i]` | `float` | Indexable as a plain list of angles |

---

## Polarization Calibration Methodology

Calibrating a sequence of waveplates (QWP - HWP - QWP) with an **unknown input state** and **non-ideal waveplates** poses several challenges:
1. **Global Degeneracy**: A global rotation of all waveplates is equivalent to a rotation of the input state, making individual parameter offsets indistinguishable.
2. **Coupling**: Sweeping a single servo in isolation does not provide enough projection information on the Poincaré sphere to uniquely decouple the input state from individual waveplate parameters (scale, offset, retardance).

### Unified Calibration Strategy

To resolve these challenges, the package utilizes a **Coordinated Multi-Configuration Sweep** combined with a **Joint Maximum Likelihood Estimation (MLE)** parameter fitter:

#### 1. Coordinated Sweeps
Instead of simple independent sweeps, the controller performs 5 distinct sweeps where each waveplate is swept under varying offset configurations of the others (e.g., sweeping HWP while QWP1 is held at $0^\circ$ or $45^\circ$). This shifts the projection planes on the Poincaré sphere, ensuring all parameters are fully decoupled.

```python
# Coordinated Sweeps & Multi-Stage Optimization Pipeline

def calibrate_polarization_system():
    # 1. Multi-configuration coordinated sweeps
    sweeps = [
        sweep(hwp,  hold_qwp1=0,  hold_qwp2=0),
        sweep(hwp,  hold_qwp1=45, hold_qwp2=0),
        sweep(hwp,  hold_qwp1=0,  hold_qwp2=45),
        sweep(qwp1, hold_hwp=0,   hold_qwp2=0),
        sweep(qwp2, hold_qwp1=0,  hold_hwp=0)
    ]
    dataset = consolidate(sweeps)

    # 2. Joint Maximum Likelihood Estimation (MLE) Fit
    # Loss = sum((measured_intensity - jones_intensity(params)) ** 2)
    # Params = [alpha, beta (input state), offsets, scales, retardances, wobbles]
    
    # Break global rotational degeneracy by fixing first QWP offset to 0
    params = init_parameters(fix_first_offset=True)

    # Stage 1: Fit linear gains, offsets, scales, and retardances
    params = minimize(loss_fn, params, fit_wobble=False)

    # Stage 2: Introduce wobble terms (mechanical misalignment correction)
    params = minimize(loss_fn, params, fit_wobble=True)

    # Stage 3: Joint refinement of all parameters to find global minimum
    final_params = joint_refine(loss_fn, params)

    # 3. Output results
    save_calibration_csv(final_params)
    update_config_yaml(final_params)
```

#### 2. Joint Solver & Gauge Fixing
All sweep data is fed into a single optimization loop:
* **Unknown Input State Fitting**: The input polarization state (\(E_{\text{in}} = [\cos\alpha, \sin\alpha e^{i\beta}]^T\)) is treated as free variables (\(\alpha, \beta\)) and fitted jointly.
* **Gauge/Degeneracy Breaking**: The offset of the first waveplate is fixed to \(0^\circ\) (`fix_first_offset=True`). This establishes a global reference coordinate frame, resolving the rotational degeneracy.
* **Non-Ideal Waveplates**: The retardance of each waveplate is fitted as a free parameter (`retardance` column in CSV, saved back to config as a ratio to \(\pi\), e.g., `0.245` instead of `0.25`).



## Joint Optimization

`PolarizationController.optimize(target="alice")` optimizes one channel. Pass a target sequence such as `target=["alice", "bob"]` to merge both servo groups into one optimization. `qtools.pctrl.joint_optimize.joint_optimize()` is the explicit two-channel wrapper; `optimize_joint` is its direct alias. Basis-dependent measurements use `BasisMeasurement` from `qtools.pctrl.optimize`.
