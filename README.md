# qtools

A modular Python toolkit for laboratory instrument control and experimental tools.

## Architecture

`qtools` adopts a **self-contained subpackage architecture**. Each hardware instrument (for example `camera`, `motor`, `powermeter`, `slm`, `tdc`, and `tec`) lives in its own autonomous subpackage containing its driver logic, optional vendor SDK wrappers, and instrument-specific utilities.

```text
qtools/
├── pyproject.toml              # Build & dependency metadata (Hatchling + uv)
├── uv.lock
├── README.md
├── src/
│   └── qtools/
│       ├── __init__.py         # Exposes instrument modules (e.g. qtools.slm)
│       ├── camera/             # 📷 Industrial cameras and vendor backends
│       ├── motor/              # Motor control and K10CR1 backend
│       ├── pctrl/              # Polarization control, servo calibration and optimization
│       ├── pmeas/              # Polarization measurement, waveplate calibration and scans
│       ├── powermeter/         # Power meters, measurement tools and calibration data
│       └── slm/                # 🔬 Self-contained SLM subpackage
│           ├── __init__.py     # Exports SLMDriver
│           ├── driver.py       # Core SLM control logic
│           ├── sdk/            # Vendor SDK & DLL bindings
│           │   └── __init__.py
│           └── utils/          # SLM-specific phase/pattern utilities
│               └── __init__.py
└── tests/
    ├── motor/                  # Motor CLI tests and manual hardware checks
    ├── pctrl/                  # Polarization controller tests
    ├── pmeas/                  # Polarization measurement tests
    ├── powermeter/             # Power meter and measurement tests
    └── slm/                    # 🧪 Independent SLM test suite
        ├── __init__.py
        └── test_slm.py
```

`qtools.camera` loads the FLIR/PySpin binding lazily, so the package can be
imported and tested without the proprietary SDK. The native PySpin wheel must
match the target Python ABI, operating system, architecture, and Spinnaker SDK;
see [`src/qtools/camera/README.md`](src/qtools/camera/README.md). When the main
application uses a newer Python than PySpin supports, `RemoteCamera` keeps the
vendor binding in a compatible worker interpreter.

`qtools.motor` and `qtools.powermeter` are standard subpackages installed with
qtools. Install from this repository root with `pip install -e .` or `uv sync`;
this also installs the `motor` and `powermeter` commands.

```python
from qtools.motor import get_motor, list_devices
from qtools.powermeter import get_device, measure_power
```

See the [motor guide](src/qtools/motor/README.md) and
[power meter guide](src/qtools/powermeter/README.md) for usage and backend details.

`qtools.pctrl` and `qtools.pmeas` provide polarization control and measurement.
Both are installed with qtools and use its motor, TDC, and power meter modules.

```python
from qtools.pctrl import PolarizationController
from qtools.pmeas import TaskController
```

The `pctrl` and `pmeas` commands are also available as `python -m qtools.pctrl`
and `python -m qtools.pmeas`. The previous `polmeas` command remains an alias
for `pmeas`; existing `pctrl_config.yaml` and `polmeas_config.yaml` files retain
their names. See the [controller guide](src/qtools/pctrl/README.md) and
[measurement guide](src/qtools/pmeas/README.md).

## Quick Start

### Gaussian Beam Analysis

```python
from qtools.calc import gaussian

result = gaussian.fit(frame, pixel_size=3.75, unit="um")
print(result.to_dict())
result.plot().savefig("beam-fit.png")
```

Supports grayscale arrays, image/RAW files, and multiple beams without OpenCV
or lmfit. See the [Gaussian guide](src/qtools/calc/gaussian/README.md).

### Basic Usage

```python
import qtools.slm as slm

# Connect to device (or mock for development)
driver = slm.SLMDriver(device_id=0, is_mock=True)
driver.connect()

# Upload phase pattern
driver.load_phase([[0, 1], [1, 0]])

driver.disconnect()
```

### Running Tests

Run only the SLM test suite:
```bash
uv run pytest tests/slm/
```

Run all project tests:
```bash
uv run pytest
```
