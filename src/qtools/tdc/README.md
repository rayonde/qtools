# TDC Python Control Library

A unified Python library and Command Line Interface (CLI) to interface with and control several common Time-to-Digital Converter (TDC) devices (including **S-Fifteen TDC1**, **S-Fifteen TDC2**, **Simulated devices**, and custom backends like **IDQ** and **CIQTEK TDC1610**).

本项目是一个统一的 Python 库和命令行工具（CLI），用于连接和控制多种常见的时间数字转换器（TDC）设备（包括 **S-Fifteen TDC1**、**S-Fifteen TDC2**、**仿真设备**以及 **IDQ** 和 **CIQTEK TDC1610** 驱动）。

---

## Installation

Install the package in development mode (Editable) from the project root directory:

```bash
pip install -e .
```

The C extension modules (for high-performance coincidences calculations) can be compiled manually:

```bash
# From the project root:
mkdir -p build && cd build
cmake ../csrc
make
cp libcoincidences.* ../src/tdc/_native/
```

---

## Command Line Interface (CLI) Guide

The package installs a system-wide executable command named `tdc`.

### 1. REPL Commands Overview

```bash
tdc --help
```

```
repl:
  singles       - Monitor singles count rates continuously
  pairs         - Monitor coincidence pairs between two channels
  coincidences  - Measure coincidence rates inside a selected window
  service       - Run an IPC server service to allow querying measurement results
  list          - List available TDC devices

global options:
  -b, --backend   TDC hardware backend (default: 's15_tdc2')
  -U, --device    Device identifier or serial port (default: auto)
  -t, --time      Integration time in seconds (default: 1.0)
  --threshvolt    Pulse trigger level in Volts (default: 0.6)
  -f, --fast      Enable fast event readout mode

data export & raw options (available for all REPL commands):
  -e, --export    Export measurement data (.csv/.npz)
  -r, --raw       Export raw timestamps (.ts/.h5)
```

All timing parameters are in **bin units** (multiples of the backend's time resolution).

---

### 2. `list` Subcommand

Scans the local machine and subnet for connected TDC devices.

| Option | Description |
|--------|-------------|
| `--method {usb,ethernet,all}` | Scanning protocol filter (default: `all`) |
| `--timeout` | Timeout in seconds for Ethernet scan (default: 1.0) |

```bash
tdc list
tdc list --method ethernet
```

---

### 3. `singles` Subcommand

Continuously monitors and prints the count rate (counts per second) for each channel.
Without `--samples` it runs continuously; with `--samples NUM` it prints NUM measurements.

| Option | Description |
|--------|-------------|
| `-s, --samples NUM` | Sample NUM times then exit (default: continuous) |
| `-c, --channel CH [CH ...]` | Select channels to display (1-based, default: all) |
| `-e, --export [FILE]` | Export count data (.csv/.npz) |
| `-r, --raw [FILE]` | Export raw timestamps (.h5/.ts) |

```bash
# Monitor singles for 3 iterations, only channels 1 and 2
tdc singles --backend simulator -s 3 -c 1 2

# Export singles data to CSV
tdc singles --backend simulator -e --raw
```

---

### 4. `pairs` Subcommand

Measures one start/stop g² histogram.

| Option | Description |
|--------|-------------|
| `--ch_start` | Reference start channel (1-based, default: 1) |
| `--ch_stop` | Target stop channel (1-based, default: 4) |
| `--bins` | Number of coincidence time bins (default: 500) |
| `--ws, --window-start` | Window start boundary, in bins |
| `--we, --window-stop` | Window stop boundary, in bins |
| `--delay` | Time delay in bins for ch_stop (default: 0) |
| `-H, --histogram` | Enable histogram visualization (-HH for more detail) |
| `--plot` | Plot the histogram using matplotlib |
| `-e, --export` | Export histogram data (.csv/.npz) |
| `-r, --raw` | Export raw timestamps (.h5/.ts) |

```bash
# Measure coincidences between ch1 and ch4 with explicit window
tdc pairs --backend simulator --ch_start 1 --ch_stop 4 --ws 50 --we 200

# With histogram display and data export
tdc pairs --backend simulator -H --export data.csv
```

---

### 5. `coincidences` Subcommand

Measures coincidence statistics in a selected window. Without `--samples` it continuously prints one measurement at a time; with `--samples NUM` it prints NUM result rows.

| Option | Description |
|--------|-------------|
| `--ch_start, --start` | Reference start channel (1-based, default: 1) |
| `--ch_stop, --stop` | Target stop channel (1-based, default: 4) |
| `--ws, --window-start` | Window start boundary, in bins |
| `--we, --window-stop` | Window stop boundary, in bins |
| `--delay` | Time delay in bins (default: 0) |
| `-s, --samples NUM` | Sample NUM times then exit (default: continuous) |
| `-e, --export` | Export histogram data (.csv/.npz) |
| `-r, --raw` | Export raw timestamps (.h5/.ts) |

```bash
# Print one coincidence result
tdc coincidences --backend simulator --ch_start 1 --ch_stop 4 --ws 50 --we 200

# Print five coincidence results and export the result rows
tdc coincidences --backend simulator -s 5 --ws 50 --we 200 --export results.csv
```

---

### 6. `service` Subcommand

Launches an IPC (Inter-Process Communication) network service.

| Option | Description |
|--------|-------------|
| `--max` | Max integration time per request, in seconds |
| `--ip` | IP address (default: 0.0.0.0) |
| `--port` | Port number (default: 4440) |
| `--secret` | Symmetric secret for authentication |

```bash
tdc service --backend simulator --ip 0.0.0.0 --port 4440
```

---

## Python API Usage

All timing parameters are in **bin units** (the backend's native resolution, e.g. 2 ps for S15 TDC2).

```python
from tdc.connection import get_backend
from tdc import TDC

# 1. Retrieve the registered backend class
backend_cls = get_backend("simulator")
backend = backend_cls()

# 2. Connect to hardware (supports context-manager protocol)
with backend:
    backend.connect(device_path="")  # Path is empty for simulator

    # 3. Wrap in high-level TDC interface
    device = TDC(backend)

    # 4. Measure singles rates
    duration, counts = device.measure_singles(duration=1.0)
    print(f"Singles counts: {counts} counts/s over {duration}s")

    # 5. Measure dual-channel coincidences (bin-based parameters)
    res = device.measure_pairs(
        duration=1.0,
        ch_start=0,       # channel 1 (0-indexed)
        ch_stop=3,        # channel 4 (0-indexed)
        window_start=50,  # start in bins
        window_stop=200,  # stop in bins
        delay=10,         # 10 bins delay compensation
    )
    # Result is a dict; net rates and efficiencies are per second.
    print(f"Coincidences: {res['net_pair_rate']:.1f} cps, "
          f"Accidental: {res['acc_pair_rate']:.1f} cps")
    print(f"Heralding efficiency: {res['eff_avg']:.2%}")

    # 6. Measure 3-fold triplet coincidence
    triplet_res = device.measure_triplet(
        duration=1.0,
        ch_ref=0,      # reference channel
        ch_sig1=1,     # first signal channel
        ch_sig2=2,     # second signal channel
        bins=500,
    )
    print(f"Triplet: hist_21 peaks at {triplet_res.hist_21.argmax()}")

    # 7. Measure N-fold gate coincidence
    gate_res = device.measure_gate(
        duration=1.0,
        ch_ref=0,
        ch_signals=[1, 2, 3],  # N-1 signal channels
        bins=500,
    )
    print(f"Gate: {len(gate_res.channels)}-fold count = {gate_res.n_fold_count}")
```

---

## Project Structure

```
tdc/
├── pyproject.toml
├── CMakeLists.txt
├── README.md
├── requirements.txt
├── csrc/
│   ├── CMakeLists.txt
│   ├── readevents/
│   ├── coincidences/
│   │   ├── coincidences.c          # g2 sliding-window (int64 bin units)
│   │   ├── coincidences.h          # C API declarations
│   │   └── multi_coincidences.c    # triplet, quadruplet, gate (N-fold)
│   └── include/
├── src/
│   └── tdc/
│       ├── __init__.py              # Facade exposing backend, connection, data, and api
│       ├── api.py                   # TDC high-level user API class
│       ├── cli.py                   # CLI tool (singles, pairs, coincidences, service, list)
│       ├── connection.py            # Registry, auto_discover, discover_all, display_devices
│       ├── data.py                  # DeviceInfo, SinglesResult, TimestampResult, G2Result,
│       │                            #   TripletResult, GateResult, DataWriter, read_log, save_ts_binary, save_hdf5
│       ├── _native/
│       │   └── __init__.py          # ctypes loader for compiled C shared libraries
│       ├── backends/                # Concrete device backends
│       │   ├── __init__.py
│       │   ├── base.py              # TDCBackend (ABC), BackendCapability (Flag)
│       │   ├── simulator/
│       │   ├── s15_tdc1/
│       │   ├── s15_tdc2/
│       │   ├── ciqtek/
│       │   └── idq/
│       └── analysis/                # Data analysis and calculations
│           ├── __init__.py
│           ├── efficiency.py
│           └── g2.py
└── tests/
    ├── conftest.py
    └── test_*.py
```
