# `polmeas` Bell Scan Notebook Example

## Goal

Add a Jupyter Notebook under `examples/` that demonstrates a real-hardware CHSH Bell scan through the public `qtools.pmeas.TaskController` API. The notebook is a runnable template for users who already have motors and a TDC configured in `polmeas_config.yaml`.

## Scope

- Add `examples/polmeas_bell_scan.ipynb`.
- Read the hardware configuration from `polmeas_config.yaml`.
- Call `TaskController.scan_bell` inside a context manager so configured motors and the TDC are closed cleanly.
- Plot the returned Bell parameter `S(β)` with uncertainty bars and classical bounds.
- Print the scan maximum and retain the full result dictionary for follow-up analysis.
- Keep the example hardware-only; no mock device, simulator, or device validation is added.

## Notebook flow

1. Markdown: explain required hardware/configuration and the purpose of a CHSH Bell scan.
2. Code: import `numpy`, `matplotlib.pyplot`, and `TaskController`; define `CONFIG_PATH` and scan parameters.
3. Code: run `ctrl.scan_bell` with explicit offsets, duration, repetitions, channel pair, accidental subtraction, raw-data saving, and optional plot saving.
4. Code: print `max_s`, `max_s_err`, and `max_offset` from the returned dictionary.
5. Code: plot `offsets`, `s_values`, and `s_errors`; draw `S=2`, `S=-2`, and a shaded `|S|≤2` region.
6. Markdown: explain that raw data are written by `save_raw=True` and that the notebook assumes a valid `polmeas_config.yaml` in the working directory.

## API and data flow

```text
polmeas_config.yaml
        │
        ▼
TaskController(config_path=...)
        │
        ▼
ctrl.scan_bell(...)
        │
        ▼
{"offsets", "s_values", "s_errors", "max_s", "max_s_err", "max_offset"}
        │
        ▼
matplotlib Bell curve
```

The example will use the high-level `TaskController` API rather than constructing `ConfigManager`, `MotorManager`, and `MeasManager` manually. This keeps the notebook aligned with the supported public interface and makes resource cleanup explicit.

## Parameters

The first code cell will expose conservative template defaults that users can adjust:

- `CONFIG_PATH = "polmeas_config.yaml"`
- `START_OFFSET = 0.0`
- `END_OFFSET = 90.0`
- `STEP_OFFSET = 5.0`
- `DURATION = 1.0`
- `REPETITIONS = 3`
- `CHANNELS = (0, 1)`
- `SUBTRACT_ACCIDENTALS = True`
- `SAVE_RAW = True`
- `SAVE_PLOT = False`

These values are passed explicitly to `scan_bell`, while motor zero points, detector setup, timing windows, and other hardware details remain in the selected configuration file.

## Error handling and validation

The notebook will not catch hardware exceptions or attempt to validate device connectivity. A missing configuration, unavailable motor, or disconnected TDC should raise the normal `qtools.pmeas` exception in the cell that starts the scan, making setup problems visible to the user.

Validation for this change is limited to checking that the Notebook is valid JSON, its code cells contain the intended public API calls, and its plotting cell uses the documented result keys. The scan itself is not run because no device is connected.
