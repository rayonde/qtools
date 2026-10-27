# DMP40 modal control

User-confirmed scope: implement `qtools.dm` around the local Thorlabs
`Light_Control_and_Manipulation_Examples` ctypes example, primarily for DMP40.
Do not use dmlib or introduce an independently fitted voltage mapping. The user
is currently on macOS; obtaining the Windows SDK binaries and hardware testing
are deferred. Reserve `backends/Thorlabs/DMP40/libs/` for the two vendor DLLs.

## Interface and mapping

- `DM(backend="dmp40", serial=...)` exposes a lazy, context-managed DMP40 backend.
- `set_orientation(pitch=..., yaw=...)` maps yaw to normalized X and pitch to Y;
  `set_tip_tilt(x=..., y=...)` converts these coordinates to amplitude and azimuth
  for `TLDFM_set_tilt_amplitude_angle`. These are normalized commands, not a
  calibrated physical mirror angle or reflected beam angle.
- `set_zernike(mode, amplitude)` follows the reference single-pattern function.
  `set_zernikes(mapping)` uses the SDK's combined-pattern function, with a full
  12-element coefficient array. `update_zernikes(mapping)` edits a known command.
- Names/enums are the default mode selectors. Explicit conversion helpers accept
  Thorlabs indices, Noll indices or `(n,m)`, avoiding silent index confusion.
  The SDK supports radial orders 2–4 (12 modes); piston and arbitrary higher
  orders are not supported by this factory-pattern interface.
- Zernike amplitudes use the native device normalization and queried bounds.
  Zero coefficients mean the SDK reference shape, not measured optical flatness.
- `dm.info` is a printable connected-device snapshot. It retains discovery
  identity fields and adds `parameters`, keyed by supported control name, with
  minimum, maximum, current command value, unit and setter. Zernike bounds come
  from the queried SDK capabilities. Unsupported tilt controls are omitted.
  Current values are the object's last successful setpoints; unknown state is
  `None` and prints as `unknown`, including after affected relaxation or uncertain
  writes. Reading info causes no SDK calls. It displays coupled pointing and
  combined-pattern constraints, and labels all values as commands rather than
  measured optical readback. Each read produces a fresh snapshot.

## Backend and SDK

Retain vendor ctypes discovery, `TLDFMX_init`, relaxation patterns, pattern
calculation, `TLDFM_set_segment_voltages`, and `TLDFMX_close`. Use writable
string buffers, explicit Windows VISA ABI widths, error/status checks, and SDK
pattern range checking. Load DLLs only when discovering/connecting, defaulting
to the package's `libs` directory. Preserve DLL search-directory handles while
loaded. The official Windows software's VISA/USB/runtime prerequisites still
apply. Do not execute hardware operations during development on macOS.

Opening and closing do not implicitly relax, reset, or alter the mirror.
Track only commands issued by this object, never label them measured wavefront
state. On uncertain writes, invalidate affected command state. Relaxation is
explicit, bounded, and sleeps between successive applied patterns as in the
MATLAB reference. Unsupported tilt hardware raises a clear capability error.

## Deliverables and validation

Provide a Chinese README, mode table, DLL placement instructions, provenance,
a Windows hardware example, and a portable dry-run example that prints commands
without inventing actuator voltages or simulating optical accuracy.

Test modal indexing, tilt conversion, ABI signatures, discovery/selection,
connection cleanup, SDK errors, pattern bounds, state updates, relaxation, lazy
imports and package resource placement using isolated fake DLLs. These tests
validate software behavior only. Verify examples and ensure reference repositories
are excluded from the wheel while future DLLs in `libs` remain included.
