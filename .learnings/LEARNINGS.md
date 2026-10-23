# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20261008-001] correction

**Logged**: 2026-10-08
**Priority**: medium
**Status**: pending
**Area**: docs

### Summary
The repository contains two `simulated_slm.ipynb` files, and the package-local copy remained stale after the root example was updated.

### Details
The root `examples/simulated_slm.ipynb` contained the LG radial-envelope demonstration, while `src/qtools/slm/examples/simulated_slm.ipynb` still used constant coefficients. The user was viewing the stale package-local copy.

### Suggested Action
Keep duplicate example locations synchronized when both are present, or consolidate them in a future cleanup after confirming the intended project layout.

### Metadata
- Source: user_feedback
- Related Files: `examples/simulated_slm.ipynb`, `src/qtools/slm/examples/simulated_slm.ipynb`
- Tags: slm, examples, laguerre-gaussian

---

## [LRN-20261007-003] correction

**Logged**: 2026-10-07
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
Superposition amplitudes represent relative weights and the complete complex field must be normalized before converting it into a phase mask.

### Details
The implementation should form the weighted complex field from the existing `PhaseMask` arrays, normalize its global L2 norm, and then take `np.angle()`. The normalization is not visible in a phase-only mask for nonzero fields, but it preserves the intended normalized superposition semantics and should reject a zero-norm field.

### Suggested Action
Normalize inside `superposition()` before constructing the returned `PhaseMask`; do not add amplitude storage to `PhaseMask`.

### Metadata
- Source: user_feedback
- Related Files: `src/qtools/slm/phase/superposition.py`, `docs/superpowers/specs/2026-10-07-phase-superposition-design.md`
- Tags: slm, phase, superposition, normalization

---

## [LRN-20261007-002] correction

**Logged**: 2026-10-07
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
Phase superposition must accept existing `PhaseMask` objects and return a `PhaseMask`; the intermediate complex field is NumPy data only.

### Details
The public form is `superposition(spiral_1, spiral_2, coefficients=(amplitude_0, amplitude_1 * exp(1j * delta)))`. The implementation should read `mask.array`, compute the complex field and `np.angle(field)`, then wrap the result back into the shared geometry as a `PhaseMask`.

### Suggested Action
Keep amplitudes and relative phase inside the required `coefficients` sequence; do not add separate amplitude, sign, or relative-phase arguments.

### Metadata
- Source: user_feedback
- Related Files: `src/qtools/slm/phase/superposition.py`, `docs/superpowers/specs/2026-10-07-phase-superposition-design.md`
- Tags: slm, phase, superposition, phasemask

---

## [LRN-20261007-001] correction

**Logged**: 2026-10-07
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
TEC CSV 日志需要同时记录设定温度和实际温度。

### Details
用户澄清了 CSV 数据格式为 `timestamp,tec.settemp,tec.temp`；第二列读取目标设定值，第三列读取实际测量值。

### Suggested Action
实现 TEC CLI 时，CSV 每行应按 `timestamp,tec.settemp,tec.temp` 写入；不要丢失设定温度或实际温度中的任一列。

### Metadata
- Source: user_feedback
- Related Files: src/qtools/tec/cli.py
- Tags: tec, csv, setpoint

---

## [LRN-20261006-001] correction

**Logged**: 2026-10-06
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
多维 OAM tomography 必须与原有 qubit tomography 实现隔离。

### Details
用户明确要求不要修改原来的 `tomography/TomoClass.py`、`TomoFunctions.py` 等文件；新功能应只放在 `qtools.tomo.oam` 子包中。

### Suggested Action
恢复原 tomography 文件，使用独立的 OAM tomography 类和内部 MLE 实现。

### Metadata
- Source: user_feedback
- Related Files: src/qtools/tomo/oam
- Tags: oam, tomography, isolation

---
