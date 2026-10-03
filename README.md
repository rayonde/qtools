# qtools

A modular Python toolkit for laboratory instrument control and experimental tools.

## Architecture

`qtools` adopts a **self-contained subpackage architecture**. Each hardware instrument (e.g. `slm`) lives in its own autonomous subpackage containing its driver logic, proprietary vendor SDK wrappers, and instrument-specific utilities.

```text
qtools/
├── pyproject.toml              # Build & dependency metadata (Hatchling + uv)
├── uv.lock
├── README.md
├── src/
│   └── qtools/
│       ├── __init__.py         # Exposes instrument modules (e.g. qtools.slm)
│       └── slm/                # 🔬 Self-contained SLM subpackage
│           ├── __init__.py     # Exports SLMDriver
│           ├── driver.py       # Core SLM control logic
│           ├── sdk/            # Vendor SDK & DLL bindings
│           │   └── __init__.py
│           └── utils/          # SLM-specific phase/pattern utilities
│               └── __init__.py
└── tests/
    └── slm/                    # 🧪 Independent SLM test suite
        ├── __init__.py
        └── test_slm.py
```

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