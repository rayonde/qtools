# Learnings

Corrections, insights, and knowledge gaps captured during development.

---

## [LRN-20261004-001] correction

**Logged**: 2026-10-04
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
The Wikipedia Bell-test angles require the CHSH sign convention with a positive 45-degree Bob offset.

### Details
For the polarization convention used here, `a=0`, `a'=45`, `b=22.5`, `b'=67.5` reaches `2*sqrt(2)` only when `S=E(a,b)-E(a,b')+E(a',b)+E(a',b')`. Mixing this with the older `b'=-22.5` geometry produces an incorrect result.

### Suggested Action
Keep backend scans, current settings, charts, and tests on one explicit convention and expose the Bob offset used by the curve.

### Metadata
- Source: user_feedback
- Related Files: bell.py, index.html, test_bell.py
- Tags: chsh, bell-angles, sign-convention

---

## [LRN-20261004-002] correction

**Logged**: 2026-10-04
**Priority**: high
**Status**: pending
**Area**: frontend

### Summary
Keep entered amplitudes distinct from the backend's physical H/V state and the right-side display representation.

### Details
The left H/V or R/L selector defines the basis in which the four entered amplitudes construct a state. An R/L ket must be converted to H/V for measurements, so Alice H/V/D/A Bob-scan predictions can differ from those of an H/V-defined ket. The right Input State selector only chooses which basis expansion of that same ket is displayed. Left-basis switching reinterprets the current coefficient controls in the newly selected basis; it must not conflate those controls with the output representation.

### Suggested Action
Keep a dedicated input-amplitude vector, send it with the selected input basis to the backend, and use the backend's two equivalent basis expansions for the display-only control. Cover R/L measurement predictions with a regression test.

### Metadata
- Source: user_feedback
- Related Files: index.html, bell.py, test_bell.py
- Tags: quantum-state, basis-conversion, input-state

---
