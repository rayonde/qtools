# Experimental S15 TDC1 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately registered `ExpS15TDC1Backend` in `src/tdc/backends/s15_tdc1/` that delegates hardware behavior to a local S15lib-compatible `TimestampTDC1` implementation and uses `tdc.analysis.g2` instead of `S15lib.g2lib`.

**Architecture:** Keep S15lib's `TimestampTDC1` serial protocol and decoding behavior as the source of truth. Add only local import compatibility, the existing TDC1 firmware loader workaround, and a thin `TDCBackend` adapter that converts S15lib-style return values into project dataclasses.

**Tech Stack:** Python 3.9+, NumPy, pyserial, pytest, `tdc.analysis.g2`.

## Global Constraints

- Register the new backend as `exp_s15_tdc1`; do not replace `s15_tdc1`.
- Preserve S15lib `TimestampTDC1` commands, line endings, timeouts, sleeps, flush/drain order, and binary decoding.
- Allowed driver deviations are local import paths, syntactic repair, and replacing legacy `g2lib` computation with `tdc.analysis.g2.compute_g2`.
- Keep existing user changes in `usb_counter_fpga.py`, `tdc1_utils.py`, and `uv.lock` unless a focused change is required.
- Do not create a git commit because the user did not request one.

---

### Task 1: Make the local TimestampTDC1 driver importable and protocol-compatible

**Files:**
- Create: `src/tdc/backends/s15_tdc1/serial_connection.py`
- Modify: `src/tdc/backends/s15_tdc1/usb_counter_fpga.py`
- Test: `tests/test_exp_tdc1_driver.py`

**Interfaces:**
- Produces: `search_for_serial_devices(device: str) -> list[str]`.
- Produces: importable `TimestampTDC1` and `TimeStampTDC1` classes.

- [ ] **Step 1: Write the failing import test**

```python
def test_local_timestamp_driver_imports_without_legacy_modules():
    from tdc.backends.s15_tdc1.usb_counter_fpga import TimestampTDC1
    assert TimestampTDC1.DEVICE_IDENTIFIER == "TDC1"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py::test_local_timestamp_driver_imports_without_legacy_modules -q`

Expected: FAIL with `ModuleNotFoundError` for the copied legacy `g2lib` or `serial_connection` import.

- [ ] **Step 3: Add local serial discovery and replace imports**

Implement S15lib-compatible OS port enumeration and `*IDN?` probing in `serial_connection.py`. In `usb_counter_fpga.py`, import that local module and alias project analysis as `compute_g2_analysis`; do not change class commands.

- [ ] **Step 4: Run the import test and verify GREEN**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py::test_local_timestamp_driver_imports_without_legacy_modules -q`

Expected: PASS.

- [ ] **Step 5: Write a failing stream-order parity test**

Use a fake serial object and deterministic `time.time()` values. Assert `_stream_response_into_buffer()` sends the start command, writes `abort\r\n`, calls `flush()`, sleeps `0.2`, drains trailing bytes, and returns chunk sizes in S15lib order.

- [ ] **Step 6: Run the parity test and verify RED**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py::test_stream_response_matches_s15lib_abort_flush_and_drain_order -q`

Expected: FAIL because the current local copy omits S15lib's flush/sleep sequence.

- [ ] **Step 7: Restore S15lib stream behavior exactly**

Replace only `_stream_response_into_buffer()` with the installed S15lib sequence: collect timed chunks, send abort, flush, join chunks, sleep `0.2`, then drain all `in_waiting` bytes.

- [ ] **Step 8: Run all driver tests**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py -q`

Expected: PASS.

---

### Task 2: Add the experimental firmware-aware loader

**Files:**
- Modify: `src/tdc/backends/s15_tdc1/tdc1_utils.py`
- Test: `tests/test_exp_tdc1_utils.py`

**Interfaces:**
- Produces: `load_experimental(args) -> TimestampTDC1`.
- Preserves: `load(args)` for the stable S15lib-backed backend.

- [ ] **Step 1: Write failing loader tests**

Test that `load_experimental()` constructs the local class with the explicit path, assigns threshold and filename, sends `abort\r\n`, drains replies, and applies the existing extra-terminator patch when reading `mode` raises `ValueError`.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_exp_tdc1_utils.py -q`

Expected: FAIL because `load_experimental` does not exist.

- [ ] **Step 3: Extract a shared loader helper**

Implement `_load_timestamp(args, timestamp_cls, auto_find_linux)` containing the current threshold, filename, abort/drain, mode probe, and method-patching behavior. Keep `load()` lazy-importing S15lib and using Linux auto-find as before. Add `load_experimental()` using the local class and preserving an explicit path.

- [ ] **Step 4: Run loader tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_exp_tdc1_utils.py -q`

Expected: PASS.

---

### Task 3: Add and register ExpS15TDC1Backend

**Files:**
- Create: `src/tdc/backends/s15_tdc1/exp_backend.py`
- Modify: `src/tdc/backends/s15_tdc1/__init__.py`
- Test: `tests/test_exp_s15_tdc1_backend.py`

**Interfaces:**
- Produces: `ExpS15TDC1Backend(TDCBackend)`.
- Registers: `@register_backend("exp_s15_tdc1")`.
- Implements: `connect`, `disconnect`, `is_connected`, `get_singles`, `get_timestamps`, `compute_g2`, `set_threshold`, and `discover_devices`.

- [ ] **Step 1: Write failing registration and metadata tests**

Assert package export, registry lookup, name, vendor, four channels, global threshold, and singles/timestamps/threshold capabilities.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_exp_s15_tdc1_backend.py -q`

Expected: FAIL because `ExpS15TDC1Backend` does not exist.

- [ ] **Step 3: Implement minimal backend registration and connection state**

Create the class, resolve explicit/stored/discovered paths, call `load_experimental`, wrap initialization failures in `ConnectionError`, and close/reset the serial connection defensively on disconnect.

- [ ] **Step 4: Add failing acquisition tests**

Using a fake `TimestampTDC1`, assert counts become `uint64`, rates use the requested integration time, nanoseconds become picoseconds, and multi-bit patterns expand into 1-based channels.

- [ ] **Step 5: Implement acquisition adapters**

Delegate commands to `get_counts()` and `get_timestamps(..., highcount=False)` without recreating serial protocol in the backend. Convert only units, patterns, and result dataclasses.

- [ ] **Step 6: Add failing G2 and threshold tests**

Monkeypatch `compute_g2_analysis` and assert `ps`, `ns`, and `ms` delays convert to integer hardware-resolution bins, while threshold writes the local driver's global `threshold` property.

- [ ] **Step 7: Implement analysis delegation and discovery identity**

Call `tdc.analysis.g2.compute_g2` with timestamp arrays and rewrite discovered `DeviceInfo.backend_name` values to `exp_s15_tdc1`.

- [ ] **Step 8: Run backend tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_exp_s15_tdc1_backend.py -q`

Expected: PASS.

---

### Task 4: Replace all copied TDC1 g2lib usage with project analysis

**Files:**
- Modify: `src/tdc/backends/s15_tdc1/usb_counter_fpga.py`
- Modify: `src/tdc/backends/s15_tdc1/tdc1_utils.py`
- Test: `tests/test_exp_tdc1_driver.py`
- Test: `tests/test_exp_tdc1_utils.py`

**Interfaces:**
- Preserves: `TimestampTDC1.count_g2(t_acq, bin_width=2, bins=500, ch_start=1, ch_stop=2, ch_stop_delay=0) -> dict`.
- Preserves: `g2_extr(timestamp, duration, channel_start, channel_stop, min_range, bins, bin_width) -> tuple`.

- [ ] **Step 1: Write failing G2 compatibility tests**

Assert both helpers preserve their legacy output shapes while delegating histogram generation to project analysis with picosecond timestamps, 1-based expanded channels, and delay/window values converted to bin units.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py tests/test_exp_tdc1_utils.py -q`

Expected: FAIL because the copied functions still reference S15lib `g2lib` or do not delegate to analysis.

- [ ] **Step 3: Implement the analysis adapters**

Convert TDC1 nanoseconds to integer picoseconds, decode pattern masks with `decode_pattern_channels`, call `compute_g2_analysis`, and reconstruct the original dictionary/tuple return shapes.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_exp_tdc1_driver.py tests/test_exp_tdc1_utils.py tests/test_exp_s15_tdc1_backend.py -q`

Expected: PASS.

- [ ] **Step 5: Run repository regression tests and static checks**

Run: `.venv/bin/pytest -q`

Run: `.venv/bin/ruff check src/tdc/backends/s15_tdc1 tests/test_exp_tdc1_driver.py tests/test_exp_tdc1_utils.py tests/test_exp_s15_tdc1_backend.py`

Expected: all tests pass and Ruff reports no errors in changed files.
