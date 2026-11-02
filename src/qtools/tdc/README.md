# TDC Python Control Library

A unified Python library and Command Line Interface (CLI) to interface with and control several common Time-to-Digital Converter (TDC) devices (including **S-Fifteen TDC1**, **S-Fifteen TDC2**, custom backends like **IDQ** and **CIQTEK TDC1610**).

本项目是一个统一的 Python 库和命令行工具（CLI），用于连接和控制多种常见的时间数字转换器（TDC）设备（包括 **S-Fifteen TDC1**、**S-Fifteen TDC2**、**IDQ** 和 **CIQTEK TDC1610** 驱动）。

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
cmake ../src/qtools/tdc/csrc
make
cp libcoincidences.* ../src/qtools/tdc/_native/
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
  -b, --backend   TDC hardware backend (default: 'exp_s15_tdc1')
  -U, --device    Device identifier or serial port (default: auto)
  -t, --time      Integration time in seconds (default: 1.0)
  --threshvolt    Pulse trigger level in Volts (default: 0.6)
  -f, --fast      Enable fast event readout mode

data export & raw options (available for all REPL commands):
  -e, --export    Export measurement data (.csv/.npz)
  -r, --raw       Export raw timestamps (.ts/.h5)
```

CLI software windows and delays use **bin units** (multiples of the backend resolution). Python result objects use physical integer time values, in picoseconds by default.

---

### 2. `list` Subcommand

Scans registered backend transports for connected TDC devices. Ethernet
backends use their protocol-aware discovery routines.

| Option | Description |
|--------|-------------|
| `--method {usb,ethernet,all}` | Scanning protocol filter (default: `all`) |
| `--timeout` | Hard per-backend discovery deadline in seconds (default: 2.0) |

```bash
tdc list
tdc list --method ethernet
```

Each backend is scanned under the `--timeout` deadline, so a blocked serial
driver or vendor SDK cannot make `tdc list` hang indefinitely. Siminics USB
discovery is opt-in because some vendor SDK versions block in `InitDll()` when
no board is present; enable it with
`QTOOLS_TDC_SCAN_SIMINICS=1`.

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
tdc singles --backend exp_s15_tdc1 -s 3 -c 1 2

# Export singles data to CSV
tdc singles --backend exp_s15_tdc1 -e --raw
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
tdc pairs --backend exp_s15_tdc1 --ch_start 1 --ch_stop 4 --ws 50 --we 200

# With histogram display and data export
tdc pairs --backend exp_s15_tdc1 -H --export data.csv
```

---

### 5. `coincidences` Subcommand

Measures coincidence statistics in a selected window. Without `--samples` it continuously prints one measurement at a time; with `--samples NUM` it prints NUM result rows.
Finite runs also report the sample count, mean rate, and sample standard deviation (unavailable for a single sample). CSV exports include a `SAMPLE` column.

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
tdc coincidences --backend exp_s15_tdc1 --ch_start 1 --ch_stop 4 --ws 50 --we 200

# Print five coincidence results and export the result rows
tdc coincidences --backend exp_s15_tdc1 -s 5 --ws 50 --we 200 --export results.csv
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
tdc service --backend exp_s15_tdc1 --ip 0.0.0.0 --port 4440
```

---

## Python API

Discover attached hardware and configure an analysis bin width in integer ps:

```python
from qtools.tdc import TDC, get_tdc, list_tdc

devices = list_tdc()  # Scan attached hardware, print a table, return DeviceInfo records

tdc = TDC(backend="exp_s15_tdc1", bin_width=2_000)
# Equivalent factory form:
tdc = get_tdc(backend="exp_s15_tdc1", bin_width=2_000)

with tdc:  # Open the connection; disconnect when leaving the context
    result = tdc.measure_g2(duration=1.0, ch_start=1, ch_stop=2, bins=500)
    print(result.bin_width)  # 2000 ps = 2 ns
    finer = tdc.measure_g2(
        duration=1.0, ch_start=1, ch_stop=2, bins=500, bin_width=1_000,
    )

if devices:
    tdc = get_tdc(devices[0], bin_width=2_000)
```

`get_tdc` replaces `get_device`. Both `TDC` and `get_tdc` accept a backend name or a discovered `DeviceInfo`, plus backend constructor options. `TDC` also accepts an existing backend instance. Construction leaves the hardware disconnected; the context opens and closes it. Explicit backend selection supports both `s15_tdc1` and `exp_s15_tdc1` regardless of the configured default.

The width always uses ps, independently of `unit`. A per-measurement `bin_width` overrides the instance default for that call; when both are omitted, analysis uses the native timestamp resolution. It applies to g², coincidence, pair, triplet, gate, and heralding measurements, including repetitions and the one-shot functions. `bins` and `bin_offset` still count bins, so changing the width changes their physical span. Raw timestamps and their hardware `resolution_ps` are unaffected. For hardware scalar counters without a histogram, the width is analysis metadata; gate limits and timing still follow the device's hardware capabilities.

Import the library as `qtools.tdc`. Channel IDs follow the selected backend; the S15 TDC1 examples below use channels 1–4. Repeated measurements keep the same result class and channel configuration:

```python
from qtools.tdc import get_tdc

with get_tdc("exp_s15_tdc1") as device:
    singles = device.measure_singles(duration=1.0, num=1)
    duration, counts = singles[0]

    result = device.measure_coincidence(
        duration=1.0, ch_start=1, ch_stop=2,
        window_start=0, window_stop=10, unit="ns", samples=5,
    )
    print(result.samples)                  # 5
    print(result.raw_counts)               # One count per acquisition
    print(result.raw_pair_rate)            # One rate per acquisition
    print(result.raw_pair_rate_mean)       # Arithmetic mean in counts/s
    print(result.raw_pair_rate_std)        # Sample standard deviation
    print(result.net_pair_rate_mean)

    histogram = device.measure_g2(
        duration=1.0, ch_start=1, ch_stop=2, bins=500, samples=3,
    )
    print(histogram.histogram[0])          # First acquisition
    print(histogram.bin_edges[0])          # Integer ps, length n_bins + 1
    print(histogram.normalized[0])         # First normalized g² curve
```

`CoincidenceResult`, `MultiCoincidenceResult`, and `HeraldingGateResult` all use `samples=1` by default. Measurement values are lists even for one acquisition; `bin_width` is one shared integer. Rates divide each acquisition's counts by its actual live time in seconds. Means are arithmetic means of those rates, and standard deviations use `ddof=1`; a single sample has `std=None`. Net rates remain `None` when no accidental estimate is available.

Delay and window inputs to `measure_g2`/`measure_coincidence` use `unit` (`ps`, `ns`, `us`, or `ms`). `bins` and `bin_offset` use bins. Returned axes, offsets, windows, and delays use integer ps; `convert_time_unit(result, "ns")` converts all physical time fields together and rejects fractional integers. Windows are half open, `[start, stop)`. Software coincidence windows are expanded outward to bin edges. Automatic window selection is fixed after the first repetition.

For hardware counters, request `method="hardware"`. A device that supplies only singles rates reports `counts_start/counts_stop=None`. A fixed hardware gate with unavailable width reports both window boundaries as `None`. Counts are never reconstructed by rounding rates.

### Multiple channels and heralding

```python
with get_tdc("exp_s15_tdc1") as device:
    triplet = device.measure_triplet(
        duration=1.0, ch_ref=1, ch_sig1=2, ch_sig2=3, samples=3,
    )
    print(triplet.channels)                # (1, 2, 3)
    print(triplet.pair_hist(2, 3)[0])       # t_3 - t_2, first acquisition
    print(triplet.raw_coincidence_rate_mean)

    gate = device.measure_gate(
        duration=1.0, ch_ref=1, ch_signals=[2, 3, 4], samples=3,
    )
    print(gate.raw_counts)                 # References with every signal present

    heralded = device.measure_heralding_gate(
        duration=1.0, heralding_channel=1, gated_channels=[2, 4],
        bins=100, samples=3, store_events=True, detail_format="flat",
    )
    print(heralded.raw_counts[4])          # Channel 4 associations per acquisition
    print(heralded.raw_pair_rate_mean[4])
    print(heralded.n_gates)
    if heralded.n_gates[0]:
        print(heralded.gate_hits(0, 0))    # (relative delay in ps, actual channel ID)
```

`MultiCoincidenceResult` dictionaries use actual channel IDs or directed `(start, stop)` pairs. Triplets count signal combinations and retain four directed histograms; N-fold gates count successful reference events and retain reference-to-signal histograms. `HeraldingGateResult` opens a gate for every herald, including empty gates; it counts each gated channel independently. Overlapping gates can associate the same photon more than once.

Event and photon details are omitted by default. `store_events=True` enables them. Heralding details use either `flat` arrays or `per_gate` lists, and `store_histogram=False` provides a summary without histograms. `combine_samples([first, second])` joins compatible result objects; different channels, delays, windows, or axes require separate objects.

The convenience function `coincidence` opens and closes the device automatically and accepts `samples`. Other measurements use the context-managed `TDC` interface above. `measure_pairs` remains an independent efficiency analysis returning a dictionary with bin-based windows.

### Markers and raw acquisition storage

```python
from qtools.tdc import load_ts_binary, save_ts_binary

with get_tdc("siminics") as device:
    capture = device.backend.get_timestamps(1.0)
    if capture.markers is not None:
        for marker in capture.markers:
            print(marker.mask, marker.photon_index, marker.timestamp_ps)
    save_ts_binary("capture.ts", capture)

restored = load_ts_binary("capture.ts")
```

`TimestampResult.markers` is `None` when markers are unavailable and `[]` when acquisition provided a marker stream with no markers. Each `MarkerEvent` stores its bit mask, the number of photons preceding it (`photon_index`), and optional timestamp and original `stream_index`. Siminics markers have no independent timestamp, so `timestamp_ps=None`. Their masks preserve simultaneous M1–M4 inputs, and markers remain separate from photon channels. Marker boundaries can segment the photon arrays; marker count does not determine `samples`.

`save_ts_binary`/`load_ts_binary` use the TDC v2 format. `save_hdf5`/`load_hdf5` store equivalent metadata. Both save functions accept the entire `TimestampResult` and preserve live time, markers, and missing values.

## Project Structure

```text
src/qtools/tdc/
├── __init__.py              # Public models, connection helpers, and coincidence API
├── api.py                   # One-shot coincidence wrapper
├── measurement.py           # TDC acquisition and repeated measurements
├── data.py                  # Canonical results, validation, statistics, and storage
├── cli.py                   # singles, pairs, coincidences, service, list
├── connection.py            # Backend registry and device discovery
├── analysis/
│   ├── g2.py                # Correlation, multi-channel, and heralding algorithms
│   └── efficiency.py        # Independent pair efficiency analysis
├── backends/                # S15, IDQ, CIQTEK, Siminics
├── _native/                 # Shared-library loader
├── csrc/                    # Native correlation kernels
└── docs/superpowers/specs/  # Data model design
```

See [the data structure design](docs/superpowers/specs/2026-10-06-tdc-data-structures-unification.md) for field definitions and validation rules. Offline contract tests are in `tests/tdc/test_data_unification.py` at the repository root.
