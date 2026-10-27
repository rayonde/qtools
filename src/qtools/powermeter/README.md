# qtools.powermeter — Power Meter Control

A unified Python library and Command Line Interface (CLI) to interface with and control several common optical power meters (including **Thorlabs**, **LBTEK**, and custom **S15** devices).

本项目是一个统一的 Python 库和命令行工具（CLI），用于连接和控制多种常见的光功率计（包括 **Thorlabs**、**LBTEK** 以及自定义的 **S15** 功率计）。

---

## Installation

Install in development mode from the **qtools repository root**. This is a
subpackage of qtools; dependencies and the CLI entry point are managed by
the root `pyproject.toml`.

```bash
pip install -e .
```

*Dependencies will be lazy-imported. You can still use `mock` or `lbtek` backends even if NI-VISA drivers or `pyvisa` are not installed.*

---

## Command Line Interface (CLI) Guide

The package installs a system-wide executable command named `powermeter`.

### 1. Subcommands Overview

Show the help menu:
```bash
powermeter --help
```
*Output:*
```
usage: powermeter [-h] [-a ADDRESS] [-b {thorlabs,lbtek,s15,mock}] [-w WAVELENGTH]
              [-r RANGE] [--sampling-rate SAMPLING_RATE]
              {read,measure,live,gui} ...

Unified Power Meter Command Line Interface. Supports S15, Thorlabs, LBTEK, and Mock backends.

positional arguments:
  {read,measure,live,gui}
                        Subcommands
    read                Get a single instantaneous power reading
    measure             Sample power over time and calculate error statistics
    live                Display real-time power tracking in terminal
    gui                 Launch the graphical user interface

options:
  -h, --help            show this help message and exit
```

---

### 2. Auto-detection & Backends
If `-a` / `--address` and `-b` / `--backend` are omitted, the library automatically searches for a connected physical device:
1. Searches for custom **S15** devices on serial ports (performs a handshake checking for `"OPM"`).
2. Searches for **Thorlabs** devices on active VISA instruments.
3. Searches for **LBTEK** virtual COM ports.
If no device is detected, the CLI prompts a `未找到设备` connection error. You can run in simulation mode by specifying `-b mock`.

---

### 3. `read` Subcommand
Query the current optical power reading from a device, or calculate average power and standard deviation over a specified duration. Output is printed directly to stdout.

#### Arguments & Options (`powermeter read --help`):
- `-a`, `--address`: Device address/port. (Auto-detects device if omitted).
- `-b`, `--backend`: Backend selector (`s15`, `mock`, `lbtek`, `thorlabs`).
- `-w`, `--wavelength`: Calibration wavelength in nm (default: 780.0).
- `-r`, `--range`: Manual power range. If omitted, defaults to auto-ranging.
- `-d`, `--duration`: Duration in seconds. If specified, samples power over this time and calculates average and standard deviation.
- `-n`, `--samples`: Number of sample points (default: 10).

#### Usage Examples:
```bash
# Read once from mock backend at 633 nm
powermeter read -b mock -w 633

# Read average power and standard deviation over 0.5s with 10 samples
powermeter read -b mock -d 0.5 -n 10
```

---

### 4. `measure` Subcommand
Acquires multiple samples over a duration and calculates statistics (Mean, SD, Variance, etc.).

#### Arguments & Options (`powermeter measure --help`):
- `-a`, `--address`: Device address/port.
- `-b`, `--backend`: Backend selector.
- `-w`, `--wavelength`: Calibration wavelength in nm (default: 780.0).
- `-r`, `--range`: Manual power range. If omitted, defaults to auto-ranging.
- `-d`, `--duration`: Measurement duration in seconds (default: 1.0).
- `-n`, `--samples`: Number of sample points (default: 10).
- `-f`, `--format`: Output format (`csv`, `npz`, `txt`, `json`).
- `-o`, `--output`: Output file path to save the formatted result.

#### Usage Examples:
```bash
# Measure for 2 seconds with 20 samples, print statistics table
powermeter measure -b mock -w 780 -d 2.0 -n 20

# Export measurement data to NumPy compressed binary format
powermeter measure -b mock -d 1.5 -n 10 -f npz -o data.npz
```

---

### 5. `live` Subcommand
Starts a real-time optical power tracker in the terminal.

#### Arguments & Options (`powermeter live --help`):
- `-w`, `--wavelength`: Calibration wavelength in nm (default: 780.0).
- `-r`, `--range`: Manual power range. If omitted, defaults to auto-ranging.
- `--sampling-rate`: Update/refresh rate in Hz (default: 2.0).

#### Usage Examples:
```bash
# Display real-time power in the terminal with in-place updates at 5 Hz
powermeter live -b mock -w 780 --sampling-rate 5
```

---

### 6. `gui` Subcommand
Launches the Tkinter graphical user interface.

#### Usage:
```bash
powermeter gui
```

---

## Python API Usage

### Basic API

Full device control — instantiate, configure, and measure:

```python
from qtools.powermeter import get_device, measure_power

# 1. Instantiate the device (supports 'with' statement for auto-connect/disconnect)
device = get_device("MOCK0", "mock")

with device:
    device.set_wavelength(532.0)
    device.set_range(None)        # None = auto-range; or pass a specific range value
    print(f"Device Info: {device.get_info()}")

    # 2. Single instantaneous power reading
    power_w = device.get_power()
    print(f"Power: {power_w:.6e} W")

    # 3. Statistical measurement over 0.5 seconds, 10 sample points
    mean_w, sd_w = measure_power(device, duration=0.5, samples=10)
    print(f"Mean Power: {mean_w:.6e} W")
    print(f"Std Dev:   {sd_w:.6e} W")
```

### Convenience: `measure`

For scripts that just need a quick (mean, sd) reading — one function call, no manual device management. Ideal for stepper motor alignment loops:

```python
from qtools.powermeter import measure

mean_w, sd_w = measure(
    address="",           # Auto-detects device if empty
    backend="",           # Auto-detects if empty; or 's15', 'thorlabs', 'lbtek', 'mock'
    wavelength=1550.0,    # Calibration wavelength in nm
    range_val=None,       # Defaults to auto-ranging
    duration=0.5,         # Time in seconds
    samples=10,           # Number of sample points
)

print(f"Mean Power: {mean_w:.8e} W")
print(f"Fluctuation SD: {sd_w:.8e} W")
```

### Other API Functions

The `measurement` module provides lower-level helpers for custom workflows:

```python
from qtools.powermeter import read, measure_power, compute_statistics, export, format_power

# read() — sample over duration, return raw (elapsed_time, power_w) pairs
trace = read(device, duration=0.5, samples=10)
# → [(0.05, 0.00152), (0.10, 0.00148), ...]

# compute_statistics() — descriptive stats from a raw trace
stats = compute_statistics(trace)
# → {"mean": 0.0015, "std_dev": 0.00002, "rel_std_dev_pct": 1.33, ...}

# measure_power() — convenience: sample then return (mean, std_dev)
mean_w, sd_w = measure_power(device, duration=0.5, samples=10)

# export() — write trace + stats to file or stdout
export(trace, stats, fmt="csv", output_file="data.csv")
export(trace, stats, fmt="table")       # prints to stdout
export(trace, stats, fmt="json", output_file="data.json")

# format_power() — human-readable power formatting
format_power(0.0015)  # → "1.5000 mW"
```

---

## Project Structure

```text
src/qtools/powermeter/
├── __init__.py
├── api.py
├── cli.py               # powermeter command
├── gui.py
├── connection.py
├── measurement.py
├── README.md
└── backends/
    ├── __init__.py
    ├── powermeter.py    # PowerMeter facade and registry
    ├── base.py          # Compatibility exports
    ├── lbtek/
    ├── mock/
    ├── thorlabs/
    └── s15/
        ├── __init__.py
        ├── s15.py
        ├── s5106_interpolated.cal
        └── fdg50_interpolated.cal

tests/powermeter/
└── test_powermeter.py
```

Run tests from the qtools repository root:

```bash
uv run pytest tests/powermeter
```

