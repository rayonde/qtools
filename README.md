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
    ├── powermeter/             # Power meter and measurement tests
    └── slm/                    # 🧪 Independent SLM test suite
        ├── __init__.py
        └── test_slm.py
```

`qtools.camera` loads the FLIR/PySpin binding lazily, so the package can be
imported and tested without the proprietary SDK. The native PySpin wheel must
match the target Python ABI, operating system, architecture, and Spinnaker SDK;
see [`src/qtools/camera/README.md`](src/qtools/camera/README.md).

`qtools.motor` and `qtools.powermeter` are standard subpackages installed with
qtools. Install from this repository root with `pip install -e .` or `uv sync`;
this also installs the `motor` and `powermeter` commands.

```python
from qtools.motor import get_motor, list_devices
from qtools.powermeter import get_device, measure_power
```

See the [motor guide](src/qtools/motor/README.md) and
[power meter guide](src/qtools/powermeter/README.md) for usage and backend details.

## Quick Start

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
