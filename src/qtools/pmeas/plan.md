> Historical audit from the standalone package, retained for reference. Package names, paths, and status below predate the migration to `qtools.pmeas`; see [README.md](README.md) for current usage.

# polarization_meas — Bug Audit & Fix Plan

**Date:** 2026-07-27  
**Scope:** Logic bugs, API/usage mismatches, config safety, CLI/docs drift, test failures  
**Method:** Static code review + import checks + targeted runtime probes + `pytest` (5 failed / 2 passed)

---

## Executive Summary

The package is mid-refactor: high-level modules (`TaskController`, list-based `devices`, `MeasurementResult`) no longer match callers, tests, or README. Several paths are **hard-broken at runtime** (config wipe, non-subscriptable config, missing fit model, wrong kwargs). Hardware optional deps are required at import. Mock / offline mode advertised in README no longer exists.

**Severity legend**

| Tag | Meaning |
|-----|---------|
| P0 | Data loss or always-crash on primary paths |
| P1 | Wrong physics / wrong results if it runs |
| P2 | Broken secondary path / CLI / docs / tests |
| P3 | Dead code, inconsistency, maintainability |

---

## 1. Problem Inventory

### 1.1 Critical — Configuration & data integrity

#### P0-1. `ConfigManager` wipes existing config on every construct/resolve

**Where:** `config.py` — `ConfigManager.__init__` → `scan_detectors(save=True)` before any load.

**What happens:**

1. `__init__` sets `_cfg = DEFAULT`
2. `scan_detectors(save=True)` **writes defaults to disk**
3. `resolve()` then `load_or_create()` loads the just-wiped file

**Evidence (runtime):** pre-existing file with `exp`, custom `devices`, `calibrations` became empty exp, default alice/bob, empty calibrations after `ConfigManager.resolve(path)`.

**Impact:** Any `polmeas config show`, calibrate, scan, or API use can **destroy calibrations and device registry**.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed in source. `__init__` calls `self.scan_detectors(save=True)` while
   `_cfg` is still the default template. `resolve()` then calls `load_or_create()`, but
   the file on disk has already been overwritten with defaults.

⚠️ Fix can be simpler than the 5-step reorder in Phase 0. Just delete the single line
   `self.scan_detectors(save=True)` from `__init__`. `scan_detectors` is already
   called explicitly where needed (config init wizard, MeasManager fallback).

   Also check `MeasManager._init_configed_detectors` — it calls `scan_detectors(save=True)`
   as a fallback when ports are missing. After fixing __init__, this second call site
   should use `save=False` or be removed since it triggers a save on every MeasManager
   construction, and the detectors data is only useful in-memory for connection attempts.
-->

---

#### P0-2. `ConfigManager` is not subscriptable but `MeasManager.measure` uses `self.cfg[task]`

**Where:** `meas_manager.py` lines ~216–282  
**Calls:** `self.cfg[task].get("wavelength", ...)`, `thresvolt`, pair windows, etc.

**Error:** `TypeError: 'ConfigManager' object is not subscriptable`

**Impact:** Power and TDC measurement paths crash immediately. Calibration / coincidence / CHSH cannot measure.

**Related:** Config keys are inconsistent:

| Code looks for | Config actually has |
|----------------|---------------------|
| `wavelength` | `wavelength_nm` (calibration section) |
| default `thresvolt=0.6` in measure | task defaults `0.05` |

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. ~5 calls in `MeasManager.measure()` use `self.cfg[task].get(...)`.
   `ConfigManager` has `get(dotted_key)` but no `__getitem__`.

⚠️ Fix recommendation: replace `self.cfg[task]` with `self.cfg.get(task, {})` at all
   5 call sites. Do NOT add `__getitem__` — it increases API surface and creates
   confusion with the existing `get(dotted_key)` method.

   The "Related" key inconsistencies (wavelength vs wavelength_nm, thresvolt=0.6 vs
   0.05) should be fixed together: use `wavelength_nm` everywhere, default thresvolt
   from config, not hardcoded 0.6.
-->

---

#### P0-3. Entanglement treats `cfg.devices` as a **dict keyed by serial**; it is a **list**

**Where:** `entanglement.py`

```python
config = cfg.devices   # list[{id, name, serial, ...}, ...]
entry = config.get(serial_str, {})          # AttributeError
theta_0_a = float(config.get(serial_a, {}).get("theta_0", 15.0))
```

**Impact:** Coincidence and Bell scans crash as soon as basis angles are resolved.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Three call sites: `_get_basis_angle`, `run_coincidence_scan`,
   `run_bell_scan` all do `config = cfg.devices` (list) then call `.get()` on it.

⚠️ Simplest fix: don't pass `cfg.devices` (the raw list) to these functions. Pass the
   `cfg` (ConfigManager instance) instead. Then use `cfg.get_device(serial_str)` to get
   a device dict and read `bases` / `zero_offset` from it. No new helper needed.
   `_get_basis_angle` should accept ConfigManager, not a bare dict.

   Avoid creating `cfg.device_index_by_serial()` as suggested in Phase 2 — the existing
   `get_device()` method already does serial/name/id lookup.
-->

---

#### P0-4. Calibration fit result missing `model_func`

**Where:** `analysis/fit.py` returns `theta_0, phi, visibility, r_squared, coefficients` only.  
**Callers:** `calibration.py` uses `fit_result["model_func"](...)` for fine curve, plot, and CSV export.

**Error:** `KeyError: 'model_func'` after a successful angle scan.

**Impact:** Every calibration fails after data collection, so θ₀ is never saved.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `fit.py:fit_calibration_curve` returns dict without `model_func` key.
   `calibration.py:122` calls `fit_result["model_func"](fitangles)` → KeyError.
   Also used in `_plot_calibration` and `export_calibration_csv`.

✅ Fix in plan.md is correct: add a `model_func` closure to the return dict in fit.py.
   The proposed formula is clean and readable:
     def model_func(angles_deg):
         th = np.radians(angles_deg)
         return A + Bc*np.cos(4*th) + Bs*np.sin(4*th) + C*th
   This matches the design matrix model exactly.
-->

---

#### P0-5. CLI entrypoint import failure

**Where:** `cli.py`  
`from stepper_motor.cli import main as stepper_motor_main`

**Reality:** `stepper_motor.cli` has `build_parser` / `cmd_*` but **no** `main`.

**Impact:** `polmeas` console script cannot start (`ImportError`). Motor subcommand delegation is dead.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `stepper_motor.cli` has `build_parser` / `cmd_*` but no `main`.
   `commands/config.py` already imports `cmd_config` from `stepper_motor.cli` directly,
   confirming the available API.

⚠️ Simplest fix: write a ~5-line local wrapper using `build_parser().parse_args()`
   + dispatch, as plan.md suggests. Or use the cmd_* functions directly like config
   command already does.
-->

---

#### P0-6. Hard dependency on optional hardware packages

**Where:** `meas_manager.py`
d
- Top-level: `from powermeter import measure_power` (unconditional)
- `from matplotlib.backends import registry` (unused, wrong import)
- `try: import tdc, powermeter ... except ImportError: raise` (pointless)

**pyproject:** `tdc` / `powermeter` are **optional** extras (`hardware`), not core deps.

**Impact:** Importing the package without lab hardware libs fails; contradicts install docs.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Three issues in `meas_manager.py`:
   1. `from powermeter import measure_power` — unconditional top-level import
   2. `from matplotlib.backends import registry` — dead code, never used anywhere
   3. `try: import powermeter; import tdc ... except ImportError: raise` — empty `raise`
      (no exception arg) causes RuntimeError, and the entire block is pointless

⚠️ Fix: move `powermeter`/`tdc` imports inside methods (they're already used inside
   try/except in `_init_configed_detectors`). Delete `matplotlib.backends.registry`
   and the empty try/except/raise block entirely — dead code removal.
-->

---

### 1.2 Critical — Call-site / API mismatches (usage bugs)

#### P0-7. Wrong `measure()` keyword arguments at call sites

Actual signature:

```text
measure(duration, samples, channels, task, detector, meas_type, save_raw)
```

| Caller | Bad kwargs | Effect |
|--------|------------|--------|
| `commands/scan.py` (singles) | `channel=`, `detector_type=` | `TypeError` |
| `optimization.py` | `detector_type="tdc"`, `channel=` | `TypeError` |

Also: when `meas_mgr is None`, scans silently record zeros — easy to misread as “no coincidence.”

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `commands/scan.py` uses `detector_type=` (should be `detector=`) and
   `channel=` (should be `channels=`). `optimization.py:_measure_chsh_at_offsets` uses
   `detector_type=”tdc”` and `channel=channel` — same errors.

✅ Fix is a straightforward rename at each call site. No architectural change needed.
-->

---

#### P0-8. `cmd_chsh` passes `controller=` to functions that do not accept it

**Where:** `commands/chsh.py`  
**Functions:** `run_coincidence_scan(...)`, `run_bell_scan(...)` expect `motor_mgr`, `meas_mgr`, `cfg`.

**Error:** `TypeError: unexpected keyword argument 'controller'`  
Default `polmeas chsh` characterization path is broken.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `commands/chsh.py` calls `run_coincidence_scan(controller=ctrl, ...)`
   and `run_bell_scan(controller=ctrl, ...)`, but these functions accept `motor_mgr`,
   `meas_mgr`, `cfg` — not `controller`.

⚠️ Better fix than passing 3 separate args: use `TaskController`'s own methods
   `ctrl.scan_coincidence(...)` and `ctrl.scan_bell(...)` instead of calling the
   low-level module functions directly. These methods already handle parameter forwarding
   correctly. This eliminates redundant argument-passing logic.
-->

---

#### P0-9. `TaskController.calibrate` / CLI kwargs vs `run_calibration`

| Caller passes | Calibrate / API accepts |
|---------------|-------------------------|
| CLI `save_plot=` | `plot=` |
| (none for export from flag consistently) | `export=` |

`commands/calibrate.py` calls `ctrl.calibrate(..., save_plot=...)` → **TypeError**.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Caller passes `save_plot=` but the method signature uses `plot=`.
   Simple rename at the call site. No architectural change needed.
-->

---

#### P0-10. Missing `ConfigManager.get_devices()`

**Where:** `TaskController.optimize_basis` / `live_correction`  
`self.cfg.get_devices()` — method does not exist (`get_all_devices` does).

**Impact:** Optimize / live correction crash when serials not provided.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Two call sites in `meas_manager.py` (optimize_basis and
   live_correction) call `self.cfg.get_devices()` which does not exist. The correct
   method is `get_all_devices()`.

⚠️ Simplest fix: replace `self.cfg.get_devices()` with `self.cfg.get_all_devices()` at
   both call sites. Do NOT add a `get_devices` alias — that's redundant API surface.
   The fallback path (`if not serial_a or not serial_b`) is commonly triggered since
   callers often pass empty strings, so this is a real P0 crash.
-->

---

#### P0-11. README / public API names are stale

| Documented | Actual |
|------------|--------|
| `PolarizationMeasurementController` | `TaskController` / alias `MeasController` |
| `mock=True`, `MockMeasManager`, `mockmotor.py` | **Removed** |
| `optimize.py`, `achromatic.py` | Logic in `optimization.py`, `calibration.py` |
| `polmeas calibrate --mock` | No `--mock` flag |
| `polmeas scan coincidence` | CLI is `scan pairs` |

Users following README will fail immediately.

<!-- REVIEW (2026-07-27):
✅ Confirmed. Multiple README/actual mismatches. Documentation sync should be part of
   Phase 5 but these entries should not block P0 fixes.
-->

---

### 1.3 Logic / physics / correctness

#### P1-1. Calibrated angles never feed entanglement / optimization

**Storage after calibration** (`add_calibration`):

- Device fields: `zero_offset`, `bases`
- Cal record: `zero_offset`, `bases`, …

**Readers look for:**

- `entanglement._get_basis_angle`: `target_angles`, then `theta_0` (not `bases` / `zero_offset`)
- `optimization.optimize_basis`: `theta_0` (not `zero_offset`)
- `commands/config.py` latest print: `theta_0`, `target_angles`

**Impact:** After a “successful” calibration, Alice/Bob still use defaults (0° or 15°). CHSH / correlation scans use wrong bases → garbage S.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed — this is the most impactful logic bug. The schema split is systematic:
   - Writers (add_calibration, calibration.py output) → `zero_offset`, `bases`
   - Readers (_get_basis_angle, run_bell_scan, optimize_basis, run_live_correction,
     _print_calibration) → `theta_0`, `target_angles`

⚠️ Fix simplification over plan.md Phase 2:
   1. Do NOT create “compatibility readers” — rename all readers to use `zero_offset` /
      `bases` in one pass. The whole codebase is in one repo, no migration needed.
   2. Do NOT add `cfg.device_index_by_serial()` helper — existing `cfg.get_device()`,
      `cfg.latest_zero_offset()`, `cfg.latest_bases()` already cover all lookups.
   3. Also fix `optimization.py:optimize_basis` which saves results as `theta_0` /
      `target_angles` → change to `zero_offset` / `bases`.
   4. Also fix `_print_calibration` which reads `theta_0` / `target_angles`.
-->

---

#### P1-2. Power mean/std unit conversion is inconsistent

**Where:** `meas_manager._power_unit` used as:

```python
converted_mean, unit = _power_unit(mean)       # auto unit from |mean|
converted_std, _ = _power_unit(std)            # auto unit from |std| independently
```

**Example:** mean `1e-3 W` → `1.0 mW`; std `1e-6 W` → `1.0 uW` reported under the same result “unit” string (`mW`). Error bars are wrong by 1000×.

**Fix:** convert std with **the same** unit chosen for the mean.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. One-line fix: `converted_std, _ = _power_unit(std, unit=unit)`.
   Also note: `_POWER_UNITS` dict has a duplicate `"uW"` key (also `"μW"`) — both map
   to 1e6, so it's harmless but worth cleaning up for tidiness. (NEW finding)
-->

---

#### P1-3. `verify` and `save_raw` are no-ops in calibration

Accepted by `run_calibration` / CLI / TaskController but never used in the body.

README claims H↔V extinction verification — not implemented.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `verify` and `save_raw` parameters are accepted but never referenced
   in `run_calibration()` body.

⚠️ Fix simplification: delete these no-op parameters from `run_calibration()`,
   `TaskController.calibrate()`, and CLI argparse rather than implementing new
   verification logic. `verify` can be added back as a separate PR with actual
   implementation. This is the "minimal change" approach.
-->

---

#### P1-4. CHSH / coincidence channel and threshold defaults inconsistent

- Config `scan.channels = [1, 2]` but `ch_start=0`, `ch_stop=1` (0-based vs 1-based ambiguity)
- `measure()` ignores `channels` for pair start/stop and always reads task config
- Pass-through `channel` from CLI does not override `ch_start` / `ch_stop`

**Impact:** Wrong TDC channels or thresholds → empty coincidence histograms.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed — reasonable concern about 0-based vs 1-based ambiguity and the
   `channels` parameter being ignored in the pairs measurement path. Fix as plan.md
   suggests: make `channels` override `ch_start`/`ch_stop` when provided.
-->

---

#### P1-5. Optimization / live correction hardcodes simulation-like truth offsets

`theta_0_a_true = 15.0`, `theta_0_b_true = 15.0` are accepted but **never used** in `_measure_chsh_at_offsets`. Dead parameters suggest leftover mock physics.

Coordinate descent also saves `theta_0` / `target_angles` instead of the canonical `zero_offset` / `bases` schema.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `theta_0_a_true`/`theta_0_b_true` are received but never read inside
   `_measure_chsh_at_offsets`. This is dead parameter plumbing from a removed mock-physics
   feature. Also `run_live_correction` hardcodes `theta_0_a_true = 15.0` locally.

✅ Fix: delete the dead parameters from `_measure_chsh_at_offsets`, `optimize_basis`,
   `run_live_correction`, and `TaskController.optimize_basis`. Also fix the save schema
   in `optimize_basis` to use `zero_offset`/`bases` (see P1-1).
-->

---

#### P1-6. Fit model limitations (known physics caveats)

- Linear drift term `C·θ` with θ in radians mixed into intensity fit can bias θ₀ on long scans with power drift.
- `θ_min = 0.25 * atan2(-Bs, -Bc)` is unique mod 90°; `% 180` can pick the wrong fringe branch relative to lab convention.
- Retardance from visibility assumes a specific imperfect-waveplate model; document assumptions or gate for HWP-only Malus fits.

(Lower priority than missing `model_func`, but should be validated against known θ₀ fixtures.)

<!-- REVIEW (2026-07-27):
✅ Agreed — this is a physics model accuracy concern, not a code bug. Correctly
   de-prioritized. Add docstring notes as suggested, no code change needed now.
-->

---

### 1.4 Motor / device management

#### P1-7. `MotorManager` keys and ID types are fragile

- Devices default to integer `id` (1, 2)
- `config init` can set `id=optical_path` (string `"alice"`)
- Tests use `id="alice"`
- `_connected[dev_id]` mixes int/str keys
- `get_motor("alice")` relies on `get_device` then id lookup — fails if motor was never successfully constructed (no port → `sm_get_motor` may still create handle, but connection checks fail later)

**`register_existing_motor("alice", stage)`** uses config id if present; if name is `"alice"` but id is `1`, registration key may not match later `get_motor("alice")` resolution depending on order.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Mixed int/str keys in `_connected` dict.

⚠️ Fix simplification: just convert all keys to `str(dev_id)` in `_init_configured_devices`
   and `get_motor`. No need for "secondary indexes" as plan.md suggests — that adds
   complexity. A single `str()` cast is sufficient.
-->

---

#### P1-8. MotorManager eagerly constructs motors for **all** devices at init

Even disconnected devices call `sm_get_motor(...)`. Side effects: USB scans, exceptions, slow startup, pollution of stepper_motor global state. Config wipe (P0-1) plus this makes every CLI invocation expensive and risky.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. Combined with P0-1, every CLI invocation triggers USB scans + config
   save. After P0-1 fix (removing auto-save), the pain is reduced but the eager init
   still causes slow startup.

⚠️ Fix simplification: as a quick first step, wrap the loop body in
   `_init_configured_devices` with try/except so one bad device doesn't crash the whole
   init. Full lazy connect on `get_motor` is a larger refactor for a later phase.
-->

---

#### P2-1. `commands/utils.MotorBackend(port=, name=)` / wrap path vs `get_motor`

Multiple resolution stacks:

1. `MotorManager` + `sm_get_motor(dev_id)`
2. CLI `_resolve_motor` → raw `sm_get_motor` + wrap `MotorBackend(stage_impl=...)`
3. REPL separate path

Inconsistent serial/port attribute names (`serial` vs `_serial`, `port` vs `_port`) cause empty serial registration and failed pair resolution.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed — 3 separate resolution stacks exist. But this is correctly rated P2:
   while redundant, it's not causing crashes on primary paths. Unification is a
   larger refactor; should come after P0/P1 fixes.
-->

---

#### P2-2. `config init` writes `_serial` but schema uses `serial`

Lookup sometimes checks both; registration/calibration keys often use one only → “device not found” after init.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `_do_config_init` writes `_serial=sn` (with underscore) but the device
   template schema field is `serial` (no underscore). `list_devices()` already has a
   fallback `dev.get(“serial”) or dev.get(“_serial”)`, so readers tolerate both. But
   `get_device(serial=...)` won't match `_serial`.

✅ Simplest fix: change `_serial=sn` → `serial=sn` in `_do_config_init`. One-line fix.
-->

---

### 1.5 CLI / UX usage problems

#### P2-3. No offline / mock mode despite docs and lab need

Cannot develop or CI-test without hardware. Old `MockMeasManager` / `--mock` removed; tests still expect simulators (`allow_simulator=True`, `measure_pairs_full`).

<!-- REVIEW (2026-07-27):
✅ Confirmed — mock mode removed but docs/tests still reference it. Phase 4 correctly
   addresses this. No immediate action needed for P0/P1 fixes.
-->

---

#### P2-4. CLI surface ≠ README

| README | CLI reality |
|--------|-------------|
| `scan coincidence` | `scan pairs` |
| `calibrate --mock` | missing |
| `calibrate --sample` | `--samples` |
| default export/plot on | plot only with `--plot`; export separate `-e` |
| `chsh` full char | broken (P0-8) |

<!-- REVIEW (2026-07-27):
✅ Confirmed — CLI surface ≠ README on several points. Doc sync in Phase 5.
-->

---

#### P2-5. `calibrate` device resolution creates **second** `ConfigManager.resolve()` 

Ignores `args.config` path in `_resolve_device_identifier` → wrong file / double wipe risk.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `_resolve_device_identifier` internally calls `ConfigManager.resolve()`
   without passing `args.config`. After P0-1 fix, the double-wipe risk is gone, but
   this still reads the wrong config file when `--config` is specified.

⚠️ Simplest fix: pass the already-resolved `cfg` instance from `cmd_calibrate` into
   `_resolve_device_identifier` instead of creating a new one internally.
-->

---

#### P2-6. `MeasController()` in commands ignores `args.config`

```python
cfg = ConfigManager.resolve(args.config)  # loaded then discarded
with MeasController() as ctrl:            # default polmeas_config.yaml again
```

User `--config other.yaml` does not apply to the controller session.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed. `MeasController()` default-constructs with "polmeas_config.yaml".
   `TaskController.__init__` already accepts `config_path`, so the fix is just:
   `with MeasController(config_path=args.config) as ctrl:` in all command handlers.
-->

---

#### P2-7. `scan singles` has no real implementation path for role/motor from manager

Falls back to `_resolve_motor`; measure kwargs wrong (P0-7). Essentially non-functional.

---

#### P2-8. `cmd_calibrate_achromatic` references missing argparse fields

`args.port`, `args.name`, `args.id`, `args.type`, `args.detector_type`, `args.repetitions` — not defined on current calibrate parsers. Dead/orphan handler.

<!-- REVIEW (2026-07-27):
✅ Bug confirmed — `cmd_calibrate_achromatic` is an orphan function. The achromatic
   calibration path already works correctly through `cmd_calibrate` (the `cal_mode ==
   "achromatic"` branch).

⚠️ Fix simplification: delete `cmd_calibrate_achromatic` entirely rather than trying to
   repair it. The existing `cmd_calibrate` achromatic branch already calls
   `run_achromatic_calibration()` correctly.
-->

---

#### P2-9. REPL not wired into CLI

`repl.py` exists; `cli.py` does not expose `polmeas repl`. Orphan feature.

---

### 1.6 Packaging / imports / dead code

#### P2-10. `pyproject.toml` hatch packages

```toml
packages = ["src/polarization_meas"]
```

Prefer standard:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/polarization_meas"]
```

with

```toml
[tool.hatch.build]
[tool.hatch.build.targets.wheel]
only-include = ... 
```

or `tool.hatch.build.targets.wheel.packages` + proper src layout (`[tool.hatch.build.targets.wheel] packages` may install under wrong top-level name depending on hatch version). Verify wheel contents after fix.

Core deps should list what is always imported, or make hardware truly lazy.

<!-- REVIEW (2026-07-27):
⚠️ Current `[tool.hatch.build.targets.wheel] packages = ["src/polarization_meas"]` is
   actually correct for hatchling src-layout. The plan.md's suggested alternative is
   equivalent. Recommend keeping existing config, just verify wheel contents with
   `python -m build && unzip -l dist/*.whl` to confirm the package name is correct.
-->

---

#### P3-1. Dead / suspicious imports

- `matplotlib.backends.registry` in `meas_manager.py`
- unused `time` import in places
- `json` import in scan/chsh commands unused
- bare `except ImportError: raise`

<!-- REVIEW (2026-07-27):
✅ All confirmed as dead code. The empty `except ImportError: raise` in `meas_manager.py`
   is actively harmful — it causes `RuntimeError: No active exception to reraise` if hit.
   These should be cleaned in Phase 0 alongside the lazy import fix.
-->

---

#### P3-2. `MeasurementResult` vs historical tuple/dict API

Tests and optimization still partially assume:

- `val, std = mgr.measure(...)`
- multi-channel `dict` keyed by channel
- `measure_pairs_full(...)`

Current API returns a single `MeasurementResult`. Migration incomplete.

---

#### P3-3. Duplicate wavelength defaults (1550 vs 1560)

CLI hardcodes 1550; config default 1560; device template 1550. Confusing for lab records.

---

### 1.7 Test suite status (current)

| Test | Result | Root cause |
|------|--------|------------|
| `test_calc_stats` | PASS | — |
| `test_qwp_quadrant_fit` | PASS | — |
| `test_devices_schema_and_resolution` | FAIL | P0-1 wipe; id/serial schema |
| `test_task_detectors_and_defaults` | FAIL | P0-1 + motor resolve side effects |
| `test_device_keyed_calibrations_and_sync` | FAIL | P0-1 wipe loses calibration |
| `test_motor_manager_get_motor_delegation` | FAIL | no hardware / connection error |
| `test_meas_manager_simulator` | FAIL | no `allow_simulator`, no `measure_pairs_full`, API drift |

**Import:** `polarization_meas.cli` **FAIL** (P0-5).

---

### 1.8 Additional issues found during review (2026-07-27)

#### NEW-1. Duplicate key in `_POWER_UNITS` dict

**Where:** `meas_manager.py` — `_POWER_UNITS` dict has `"uW": 1e6` and `"μW": 1e6` (duplicate value). Harmless since both map to 1e6, but worth cleaning up — drop one.

#### NEW-2. `run_coincidence_scan` `subtract_accidentals` default mismatch

Function signature has `subtract_accidentals: bool = False`, but `TaskController.scan_coincidence` reads config default `True`. CLI argparse also defaults to `True`. Direct API callers get different behavior than CLI/controller users. Should unify to `True` (matching lab convention).

#### NEW-3. `optimization.py:optimize_basis` saves with wrong field names

Saves `entry["theta_0"]` and `entry["target_angles"]` — should be `zero_offset` and `bases` per canonical schema. Fixed as part of P1-1 remediation.

#### NEW-4. `_print_calibration` reads wrong field names

`commands/config.py:_print_calibration` reads `theta_0` and `target_angles` from cal dict — should read `zero_offset` and `bases`. Fixed as part of P1-1 remediation.

#### NEW-5. `MeasManager._init_configed_detectors` calls `scan_detectors(save=True)` as fallback

**Where:** `meas_manager.py` — when configured detectors are missing port info, the method calls `self.cfg.scan_detectors(save=True)` to discover hardware. Combined with P0-1, this triggers an additional config write every time `MeasManager` is constructed.

**Fix:** Change to `save=False` — detector scan results are only useful in-memory for connection attempts; writing them to disk on every construction is unnecessary and risks overwriting user edits.

#### NEW-6. All three command handlers discard `args.config` when constructing `MeasController`

**Where:** `commands/scan.py:23`, `commands/chsh.py:36`, `commands/calibrate.py:105`

Each file does:
```python
cfg = ConfigManager.resolve(args.config)   # loaded then discarded
with MeasController() as ctrl:             # defaults to "polmeas_config.yaml"
```

`TaskController.__init__` accepts `config_path=` (line 320) but none of the callers pass it. User `--config other.yaml` has no effect on the controller session.

**Fix:** `MeasController(config_path=args.config)` in all three files. Also fix `_resolve_device_identifier` in `calibrate.py` which creates yet another `ConfigManager.resolve()` without `args.config` (P2-5).

#### NEW-7. P1-1 schema split — detailed site inventory

All readers/writers affected by the `theta_0`/`target_angles` vs `zero_offset`/`bases` split:

| File | Function | Line | Reads/Writes | Current name |
|------|----------|------|-------------|--------------|
| `entanglement.py` | `_get_basis_angle` | 30 | reads | `target_angles` |
| `entanglement.py` | `_get_basis_angle` | 43 | reads | `theta_0` |
| `entanglement.py` | `run_bell_scan` | 236-237 | reads | `theta_0` |
| `optimization.py` | `optimize_basis` | 134-135 | writes | `theta_0`, `target_angles` |
| `optimization.py` | `run_live_correction` | — | reads | `theta_0` |
| `commands/config.py` | `_print_calibration` | — | reads | `theta_0`, `target_angles` |
| `calibration.py` | `run_calibration` | 196,201 | writes | `zero_offset`, `bases` ✅ |

All should use `zero_offset` / `bases`. Fix all 6 sites in one pass.

#### NEW-8. `stepper_motor.cli` API inventory

**Where:** `stepper_motor/src/stepper_motor/cli.py`

Available functions (no `main`): `cmd_config`, `cmd_list`, `cmd_status`, `cmd_identify`, `cmd_move_to`, `cmd_move_by`, `cmd_move`, `cmd_position`, `cmd_set_zero`, `cmd_home`, `cmd_zero`, `cmd_repl`, `build_parser`.

`polarization_meas/commands/config.py` already imports `cmd_config` directly — confirming the integration pattern. The CLI bridge (P0-5 fix) should use `build_parser().parse_args()` + dispatch to `cmd_*` functions.

---

## 2. Architecture Snapshot (intended vs actual)

```
Intended:
  CLI / API → TaskController → MotorManager + MeasManager → hardware backends
                ↓
           ConfigManager (polmeas_config.yaml)  ← single source of truth

Actual failure points:
  ConfigManager.__init__ overwrites YAML          (P0-1)
  MeasManager.measure uses cfg[task]              (P0-2)
  entanglement uses devices as dict               (P0-3)
  fit missing model_func                          (P0-4)
  CLI cannot import                               (P0-5)
  Call sites use old kwargs / controller=         (P0-7..P0-10)
  zero_offset/bases vs theta_0/target_angles      (P1-1)
```

---

## 3. Fix Plan (phased)

### Phase 0 — Stop the bleeding (P0 config + import)  **[~0.5 day]**

<!-- REVIEW (2026-07-27):
✅ Overall plan is correct. Suggested simplifications:
   1. Config lifecycle: just delete `self.scan_detectors(save=True)` from `__init__`.
      The 5-step reorder (construct→load→optional scan) is over-engineered; the existing
      `resolve()` already calls `load_or_create()` after `__init__`.
   2. Also fix in Phase 0: delete `matplotlib.backends.registry`, the empty
      `except ImportError: raise` block, and move `from powermeter import measure_power`
      inside the method.
   3. Also check `MeasManager._init_configed_detectors` — it calls `scan_detectors(save=True)`
      as a fallback. After fixing __init__, change this to `save=False` to avoid a save-on-
      every-MeasManager-construction. Detector scan results are only useful in-memory.
-->

1. **Fix config lifecycle**
   - Remove `scan_detectors(save=True)` from `__init__`.
   - Order: construct empty/default in memory → `load()` if file exists → optional scan only on `config init` or explicit `scan_detectors`.
   - Never `save()` until user/action requests it, except explicit `save()`.
   - Add regression test: pre-seeded YAML survives `ConfigManager.resolve`.

2. **Fix CLI import**
   - Implement local `stepper_motor` delegation via `build_parser().parse_args` + dispatch, or wrap:
     ```python
     def _sm_main(argv):
         p = build_parser()
         args = p.parse_args(argv)
         ...
     ```
   - Smoke: `polmeas --help`, `polmeas list` without crash.

3. **Lazy hardware imports**
   - Move `powermeter` / `tdc` / `measure_power` inside methods.
   - Delete `matplotlib.backends.registry`.
   - Package imports cleanly with only numpy/yaml/matplotlib/stepper_motor.

**Exit criteria:** resolve does not wipe files; `python -c "import polarization_meas"` works without tdc/powermeter; `polmeas --help` works.

---

### Phase 1 — Make measure + calibrate runnable  **[~1 day]**

<!-- REVIEW (2026-07-27):
✅ Overall plan is correct. Suggested simplifications:
   1. Config access: use `self.cfg.get(task, {})` only — do NOT add `__getitem__`.
      The `__getitem__` approach adds confusing API surface on top of the existing
      `get(dotted_key)` method.
   2. P1-3 (verify/save_raw): delete the no-op parameters rather than implementing
      verification logic now. Can be added as a separate PR with real implementation.
-->

1. **Config access**
   - Use `self.cfg.get(task, {})` or implement `__getitem__` delegating to `_cfg`.
   - Normalize keys: prefer `wavelength_nm`; accept alias `wavelength`.
   - Align threshold defaults with config.

2. **`fit_calibration_curve`**
   - Return `model_func` closure from coefficients:
     ```python
     def model_func(angles_deg):
         th = np.radians(angles_deg)
         return A + Bc*np.cos(4*th) + Bs*np.sin(4*th) + C*th
     ```
   - Unit test: model reproduces design matrix fit; calibration plot path does not KeyError.

3. **Power units**
   - `_power_unit(std, unit=unit_of_mean)`.

4. **Wire `verify` / `save_raw` or remove from API**
   - Minimum: implement simple H vs V extinction check using fitted bases, or document as TODO and stop advertising.

**Exit criteria:** synthetic power data → full `run_calibration` returns θ₀, writes cal entry, optional plot/CSV without crash (motors mocked).

---

### Phase 2 — Unify device angle schema  **[~0.5–1 day]**

<!-- REVIEW (2026-07-27):
⚠️ The canonical field choice is correct, but the implementation approach needs
   simplification:
   1. Drop "compatibility readers" — no need to support both old and new names in
      the same codebase. Rename all readers to `zero_offset` / `bases` in one pass.
   2. Drop item 5 (`cfg.device_index_by_serial()` helper) — existing `get_device()`,
      `latest_zero_offset()`, `latest_bases()` already cover all lookups.
   3. Also fix `optimize_basis` (writes `theta_0`/`target_angles`) and
      `_print_calibration` (reads `theta_0`/`target_angles`) — see NEW-3, NEW-4.
-->

**Canonical fields (recommended):**

| Field | Meaning |
|-------|---------|
| `zero_offset` / `calibration.fast_axis` | θ₀ (deg) |
| `bases` | `{H,V,D,A}` motor angles |
| `calibrations[key]` | history |

**Compatibility readers:** accept `theta_0` ≡ `zero_offset`, `target_angles` ≡ `bases`.

1. Fix `_get_basis_angle` to resolve device via `ConfigManager.get_device(serial_or_name)` not `devices` dict.
2. Fix `run_bell_scan` θ₀ load from device `zero_offset` / cal.
3. Fix optimization to read/write `zero_offset` + `bases`.
4. Fix `config latest` printer.
5. Helper: `cfg.device_index_by_serial()` if needed.

**Exit criteria:** calibrate → `scan pairs` uses calibrated Alice bases without manual YAML edit.

---

### Phase 3 — Align all call sites & controllers  **[~1 day]**

<!-- REVIEW (2026-07-27):
⚠️ Simplification suggestions:
   1. P0-8: use `ctrl.scan_coincidence()` / `ctrl.scan_bell()` instead of passing
      3 separate args — eliminates redundant parameter forwarding.
   2. `get_devices`: replace call sites, do NOT add alias.
   3. `cmd_calibrate_achromatic`: delete the orphan function.
   4. MotorManager: `str(dev_id)` for key hygiene; full lazy init is larger scope.
-->

1. **Single measure API**
   - Document `MeasurementResult`.
   - Fix all callers: `detector=`, `channels=`, `task=`.
   - Optional thin wrappers for old names with deprecation warnings.

2. **Fix commands**
   - `cmd_chsh` (P0-8): Use `ctrl.scan_coincidence(...)` / `ctrl.scan_bell(...)` instead of calling low-level module functions. TaskController methods already handle parameter forwarding correctly — eliminates redundant argument-passing.
   - `cmd_calibrate` (P0-9): `plot=` not `save_plot=`; honor `args.config` in `MeasController(config_path=...)`; pass cfg into `_resolve_device_identifier` instead of creating new one (P2-5).
   - `cmd_scan` (P0-7): fix `channel=`→`channels=`, `detector_type=`→`detector=`; pass `config_path=args.config` (P2-6).
   - `cmd_calibrate_achromatic` (P2-8): Delete the orphan function entirely. The achromatic path already works through `cmd_calibrate`'s `cal_mode == "achromatic"` branch.
   <!-- REVIEW (2026-07-27):
        Simplified from plan.md original: use TaskController methods for chsh instead
        of passing 3 separate args; delete orphan function instead of repairing.
   -->

3. **`get_devices`**
   - Replace `self.cfg.get_devices()` with `self.cfg.get_all_devices()` at both call sites (meas_manager.py lines 485, 516). Do NOT add a `get_devices` alias — redundant API surface.
   <!-- REVIEW (2026-07-27):
        Simplified from plan.md original: replace call sites instead of adding alias.
   -->

4. **MotorManager**
   - P1-7: Cast `str(dev_id)` for key hygiene in `_connected` dict (one call site + `register_existing_motor`). No secondary indexes needed.
   - P1-8: Wrap `_init_configured_devices` loop body in try/except so one bad device doesn't crash init. Full lazy connect on `get_motor` is larger scope — defer to later phase.
   <!-- REVIEW (2026-07-27):
        Simplified from plan.md original: just `str()` cast instead of secondary
        indexes; try/except wrap instead of full lazy connect.
   -->

**Exit criteria:** dry-run of calibrate / scan pairs / chsh with mocks does not TypeError.

---

### Phase 4 — Mock / test infrastructure  **[~1 day]**

<!-- REVIEW (2026-07-27):
✅ Plan is reasonable. Mock mode is needed for CI and development. No simplification
   suggested — this is the right scope for Phase 4.
-->

1. Restore **explicit** mock mode:
   - `MockPowerMeter` / `MockTDC` or inject callables into `MeasManager`.
   - `MotorBackend` mock (or stepper_motor mock) for move/wait.
   - CLI `--mock` and `TaskController(mock=True)`.

2. Rewrite tests to current API (or restore APIs tests need):
   - Config round-trip without wipe
   - Device resolution without USB
   - Measure returns `MeasurementResult`
   - Fit + calibration pipeline with synthetic Malus curve
   - Entanglement basis resolution from saved cal

3. CI job: `pytest` without hardware extras.

**Exit criteria:** `pytest` green offline; README mock examples work.

---

### Phase 5 — Docs, packaging, polish  **[~0.5 day]**

<!-- REVIEW (2026-07-27):
✅ Plan is reasonable. P2-10 (pyproject.toml) should be verified rather than rewritten —
   current hatchling config is likely correct. Just verify wheel contents.
-->

1. Rewrite README to match real API (`TaskController` / `MeasController`, real CLI verbs).
2. Document config schema and angle field names.
3. Fix hatch src layout; declare optional vs required deps correctly.
4. Wire or delete REPL.
5. Channel indexing doc (0-based vs hardware labels).
6. CHSH basis angle convention note (HWP 22.5° steps).

---

## 4. Suggested implementation order (tickets)

| # | Ticket | Phase | Priority |
|---|--------|-------|----------|
| T1 | Stop config wipe; load-before-save; tests | 0 | P0 |
| T2 | Lazy hardware imports; remove bad imports | 0 | P0 |
| T3 | Fix `polmeas` CLI / stepper_motor main bridge | 0 | P0 |
| T4 | `cfg.get(task)` + key aliases in `measure` | 1 | P0 |
| T5 | Add `model_func` to fit; fix power unit std | 1 | P0/P1 |
| T6 | Device angle schema + entanglement/optimize readers | 2 | P1 |
| T7 | Fix all measure/calibrate/chsh call sites + config path | 3 | P0 |
| T8 | Lazy MotorManager + id key hygiene | 3 | P1 |
| T9 | Mock backends + rewrite tests | 4 | P2 |
| T10 | README / CLI help / packaging | 5 | P2 |

---

## 5. Verification checklist (after fixes)

```bash
# Offline
python -c "import polarization_meas; print(polarization_meas.__version__)"
polmeas --help
polmeas config show
pytest -q

# With mocks (once restored)
polmeas calibrate --mock --samples 2 --end 90 --step 15
polmeas scan pairs --mock --start 0 --end 90 --step 30
polmeas chsh --mock

# Config safety
# 1) Write custom polmeas_config.yaml with unique device + calibration
# 2) Run polmeas config show
# 3) Assert file content unchanged except updated_at if explicitly saved
```

Manual lab checklist (hardware):

1. `polmeas config init` → detectors + motors registered once  
2. Calibrate HWP → θ₀ / bases stored under device serial **and** name  
3. `polmeas scan pairs` uses those bases  
4. `polmeas scan chsh` produces S(β) with non-zero rates  
5. Archive config before re-init  

---

## 6. Out of scope (this plan)

- Redesign of full Jones multi-element stacks  
- New GUI  
- Changes inside `tdc` / `powermeter` / `stepper_motor` packages except adapter fixes  
- Achromatic interactive UX redesign (repair only after single-λ path works)

---

## 7. Appendix — Quick reference of broken symbols

| Symbol / path | Issue |
|---------------|-------|
| `ConfigManager.__init__` + `scan_detectors(save=True)` | Wipes YAML |
| `ConfigManager.__getitem__` | Missing; measure uses it |
| `ConfigManager.get_devices` | Missing |
| `fit_calibration_curve` → `model_func` | Missing key |
| `run_coincidence_scan` / `run_bell_scan` devices dict | list has no `.get` |
| `measure(..., detector_type=, channel=)` | Invalid kwargs |
| `run_* (controller=...)` | Invalid kwargs |
| `calibrate(..., save_plot=...)` | Invalid kwargs |
| `stepper_motor.cli.main` | Does not exist |
| `PolarizationMeasurementController`, `--mock` | Docs only |
| `allow_simulator`, `measure_pairs_full` | Tests only |
| `verify`, `save_raw` in calibration | Dead parameters |
| `theta_0` / `target_angles` vs `zero_offset` / `bases` | Schema split brain |

---

## 8. Recommended first PR

**Title:** `fix(config): stop wipe-on-load; lazy hardware imports; cfg.get for measure`

**Contents only:**

1. Config load order + no auto-save in `__init__`  
2. Lazy imports in `meas_manager`  
3. Replace `self.cfg[task]` with `self.cfg.get(task, {})` + wavelength alias  
4. Add `model_func` to fit  
5. Regression tests for config persistence + fit model_func  

Do **not** mix full CLI rewrite in the same PR; land T1–T5 first so lab configs stop being destroyed.
