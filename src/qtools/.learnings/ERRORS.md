# Errors

Command failures and integration errors.

---

## [ERR-20261007-006] external-download-approval-policy

**Logged**: 2026-10-07T00:00:00+08:00
**Priority**: low
**Status**: pending
**Area**: tooling

### Summary
An external command requesting elevated network access was rejected because the session approval policy was set to never.

### Error
```
approval policy is Never; reject command — you cannot ask for escalated permissions if the approval policy is Never
```

### Context
- The command attempted to read the public SLMSuite license from GitHub.
- The same read-only request succeeded without escalation after the environment policy changed.

### Suggested Fix
Check the active permission policy before adding an escalation request; use a normal read-only command when network access is already enabled.

### Metadata
- Reproducible: no
- Related Files: docs/superpowers/specs/2026-10-07-flir-camera-design.md

---

## [ERR-20261007-005] unrelated-tec-full-suite-failure

**Logged**: 2026-10-07T04:33:00+08:00
**Priority**: low
**Status**: pending
**Area**: tests

### Summary
The full repository test suite has an existing TEC failure outside the SLM rewrite scope.

### Error
```
tests/tec/test_tec.py::test_tec_channel_selection
AttributeError: 'TEC' object has no attribute 'ch_prefix'
```

### Context
- The failure occurred after 134 passing tests and 42 skipped tests.
- The rewritten `tests/slm` suite passes independently.

### Suggested Fix
Restore or update the TEC channel-prefix API in a separate TEC-focused change.

### Metadata
- Reproducible: yes
- Related Files: tests/tec/test_tec.py, src/qtools/tec

### Resolution
- **Notes**: Not changed because it is unrelated to the requested SLM refactor.

---

## [ERR-20261007-004] slm-ruff-type-annotation-import

**Logged**: 2026-10-07T04:32:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
Removing unused imports also removed the NumPy symbol used in a return annotation.

### Error
```
F821 Undefined name `np` in DisplayInterface.get_data annotation
```

### Suggested Fix
Keep the NumPy import required by the public type annotation.

### Resolution
- **Resolved**: 2026-10-07T04:32:00+08:00
- **Notes**: Restored `import numpy as np` and reran Ruff.

---

## [ERR-20261007-003] slm-ruff-unused-imports

**Logged**: 2026-10-07T04:31:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The first Ruff pass on the rewritten SLM package reported three unused imports.

### Error
```
F401 unused imports in displaymask.py, interface.py, and phasemask.py
```

### Context
- The imports remained after splitting the old monolithic implementation into new modules.

### Suggested Fix
Remove unused imports and rerun Ruff with a writable cache directory.

### Metadata
- Reproducible: yes
- Related Files: slm/display/displaymask.py, slm/display/interface.py, slm/phase/phasemask.py

### Resolution
- **Resolved**: 2026-10-07T04:31:00+08:00
- **Notes**: Removed the imports before the final static check.

---

## [ERR-20261007-002] ruff-cache-permission

**Logged**: 2026-10-07T04:30:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
Ruff could not create its default cache under the repository root because that location is read-only in this workspace session.

### Error
```
ruff failed: Failed to create temporary file: Operation not permitted
```

### Context
- The source tree is writable, but the repository-root `.ruff_cache` directory is not.
- The command was checking the rewritten `src/qtools/slm` package.

### Suggested Fix
Run Ruff with `RUFF_CACHE_DIR` set to a writable temporary directory.

### Metadata
- Reproducible: yes
- Related Files: src/qtools/slm

### Resolution
- **Resolved**: 2026-10-07T04:30:00+08:00
- **Notes**: Re-ran the check with a writable cache directory.

---

## [ERR-20261007-001] incorrect-reference-path

**Logged**: 2026-10-07T03:50:00+08:00
**Priority**: low
**Status**: pending
**Area**: tooling

### Summary
An initial repository inspection used the wrong `refs` location and one skill lookup used an incorrect absolute path.

### Error
`refs: No such file or directory` and later `No such file or directory` while reading the self-improvement skill.

### Context
- The SLM reference is located at `src/qtools/slm/refs/slmutils`, not directly under the initial working directory.
- The skill root mapping needed to be resolved before reading the skill file.

### Suggested Fix
Resolve repository-relative reference paths and skill-root aliases before issuing follow-up inspection commands.

### Metadata
- Reproducible: yes
- Related Files: slm/refs/slmutils

---
