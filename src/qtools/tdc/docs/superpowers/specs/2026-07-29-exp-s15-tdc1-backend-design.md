# Experimental S15 TDC1 Backend Design

## Goal

Add an experimental `ExpS15TDC1Backend` beside the existing
`S15TDC1Backend`. The experimental backend directly implements the serial
protocol documented by S15lib's `TimestampTDC1` class. It does not import,
instantiate, or wrap `TimestampTDC1`, and it does not depend on `tdc1_utils`.

The experimental implementation is registered independently as
`exp_s15_tdc1`, so callers can switch implementations without replacing or
modifying the stable `s15_tdc1` registration.

## Scope

- Add `src/tdc/backends/s15_tdc1/exp_backend.py`.
- Export `ExpS15TDC1Backend` from the `s15_tdc1` package.
- Register it under `exp_s15_tdc1`.
- Implement S15lib-compatible commands, timeout transitions, timestamp stream
  handling, binary decoding, and the extra-terminator firmware workaround
  directly inside `ExpS15TDC1Backend`.
- Use `tdc.analysis.g2.compute_g2` for correlation analysis.
- Add hardware-independent tests using fake device and serial objects.

## Non-Goals

- Do not replace or rename `S15TDC1Backend`.
- Do not change the `s15_tdc1` registry key.
- Do not redesign the general backend API or result dataclasses.
- Do not require a physical TDC1 for automated tests.
- Do not redesign, simplify, or optimize S15lib's TDC1 serial protocol flow.
- Do not move serial commands or binary decoding into the backend.
- Do not depend on a copied or installed `TimestampTDC1` class.
- Do not depend on `tdc1_utils` from the experimental backend.

## Architecture

### Backend Registration

`ExpS15TDC1Backend` follows the structure and public behavior of
`S15TDC1Backend`, but uses the name `exp_s15_tdc1`. Both implementations are
imported from `tdc.backends.s15_tdc1`, allowing the normal registry loading
path to discover them.

The backend owns the TDC1 serial connection and protocol. Public backend
methods call private raw acquisition helpers that mirror S15lib behavior,
then convert raw values into the project's result dataclasses.

### TimestampTDC1 Fidelity

The direct backend follows the installed S15lib source as a behavioral
reference. Fidelity includes:

- constructor defaults and initialization order;
- direct `serial.Serial(device_path, timeout=0.01)` construction;
- exact command strings and line terminators;
- timeout changes made by count and timestamp acquisition;
- mode, level, threshold, clock, and integration-time property behavior;
- timestamp stream start, abort, flush, sleep, and trailing-buffer drain;
- `read_timestamps_bin`, `read_timestamps_bin2`, and
  `read_timestamps_bin3` rollover/corruption handling;
- count, pair-count, timestamp, and binary decoding behavior.

Where the installed source contains a malformed or empty `count_g2()` stub,
the backend instead implements its required `compute_g2()` method through
`tdc.analysis.g2.compute_g2`.

### Connection Flow

1. Prefer an explicit `connect(device_path=...)` argument.
2. Otherwise use the path supplied to the constructor.
3. Otherwise use the existing cross-platform TDC1 discovery function and
   select its first result.
4. Open `serial.Serial(device_path, timeout=0.01)` directly.
5. Run the S15lib-compatible mode, level, integration-time, threshold,
   abort/drain, and extra-line-termination initialization sequence.
6. Clear stale serial input only after initialization succeeds.

Device discovery remains in the existing backend discovery module so device
selection is explicit and testable.

### Acquisition

- `get_singles()` calls the local driver's count command and returns
  `SinglesResult` with unsigned counts and floating-point rates.
- `get_timestamps()` reads the binary timestamp stream, converts nanoseconds
  to picoseconds, expands multi-channel bit patterns through
  `decode_pattern_channels`, and returns `TimestampResult`.
- Acquisition does not duplicate or replace the driver's serial protocol.
  Any startup abort/drain and firmware-specific extra terminator behavior is
  applied by `tdc1_utils`, while acquisition sequencing remains inside
  `TimestampTDC1`.
- `disconnect()` closes the serial object defensively and always resets the
  backend state.

### G2 Analysis

The backend acquires timestamps through `TimestampTDC1`, adapts them to a
`TimestampResult`, and calls `tdc.analysis.g2.compute_g2`; it never calls
`S15lib.g2lib`.

The copied driver's compatibility `count_g2()` method is also adapted to the
same analysis function. Its legacy dictionary return shape is preserved,
while timestamp patterns are decoded into the channel-index representation
expected by `tdc.analysis.g2.compute_g2`.

Time conversions follow the existing backend contract:

- raw TDC1 timestamps: nanoseconds;
- backend timestamps: picoseconds;
- analysis resolution: `RESOLUTION_PS`;
- `ch_stop_delay`: converted from the selected unit to integer analysis bins.

### Error Handling

- Missing devices produce `ConnectionError`.
- Driver or serial initialization failures are wrapped in `ConnectionError`
  with the selected device path.
- Acquisition and threshold methods raise `RuntimeError` while disconnected.
- Invalid G2 units raise `ValueError`.
- Failed disconnect cleanup is logged without leaving the backend marked as
  connected.

## Testing Strategy

Tests are written before implementation and use dependency replacement rather
than a physical serial port. They cover:

- independent registry entry and package export;
- explicit and discovered connection paths;
- connection failure cleanup;
- singles count/rate conversion;
- timestamp unit conversion and multi-bit channel expansion;
- G2 delegation and delay-unit conversion;
- global threshold behavior;
- serial cleanup and idempotent disconnect;
- importability of the local driver without legacy `g2lib` or
  external `serial_connection` modules;
- parity of the local driver's command bytes, timeout transitions, stream
  abort/flush/drain order, and decoding outputs against S15lib-compatible
  fake serial traces.

## Compatibility

Existing callers using `s15_tdc1` retain current behavior. Experimental users
switch only the backend identifier to `exp_s15_tdc1`. The new class implements
the same abstract interface and result types, so higher-level measurement code
does not need an experimental code path.
