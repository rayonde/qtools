# Errors

---

## [ERR-20261007-007] slm-lint-included-preserved-reference-scripts

**Logged**: 2026-10-07T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The first SLM Ruff command recursively linted immutable historical scripts in `slm/refs/`.

### Error
```text
Ruff reported legacy Python 2 syntax and style violations in slm/refs/lgphase and slm/refs/slmutils.
```

### Context
- The rewrite explicitly preserves `slm/refs/` without modification.
- `python3 -m ruff check slm --exclude slm/refs ../../tests/slm` passed afterwards.

### Suggested Fix
Always exclude `slm/refs/` from checks that apply to the rewritten package.

### Metadata
- Reproducible: yes
- Related Files: `src/qtools/slm/refs/`

---

## [ERR-20261007-002] safety-rejected-temp-cleanup

**Logged**: 2026-10-07
**Priority**: low
**Status**: pending
**Area**: infra

### Summary
A verification command was rejected because it included recursive deletion of a temporary directory.

### Error
```text
Rejected: rm -f style commands are not permitted. Use a safer approach
```

### Context
- The command attempted to remove an explicitly named `/tmp/qtools-tec-channel` directory before recreating it.
- No deletion occurred and no project files were affected.
- Verification was rerun with `mktemp -d` and completed successfully.

### Suggested Fix
Use a fresh temporary directory for validation instead of cleanup commands.

### Metadata
- Reproducible: yes
- Related Files: none

---

## [ERR-20261007-001] tec-test-existing-channel-attribute

**Logged**: 2026-10-07
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
Running the TEC test suite exposed an existing mismatch in the channel-selection test.

### Error
```text
AttributeError: 'TEC' object has no attribute 'ch_prefix'
tests/tec/test_tec.py::test_tec_channel_selection
```

### Context
- Command: `python3 -m pytest tests/tec -q`
- The failure is in the pre-existing controller test and is unrelated to the new CLI files.
- `TECChannel` owns `ch_prefix`; `TEC` exposes `tc1`/`tc2` channel views but no `ch_prefix` attribute.

### Suggested Fix
Review whether the stale test should assert `tec2.tc2.ch_prefix` or whether a compatibility property belongs on `TEC`.

### Metadata
- Reproducible: yes
- Related Files: `tests/tec/test_tec.py`, `src/qtools/tec/controller.py`

---

## [ERR-20261006-002] commit-included-prestaged-changes

**Logged**: 2026-10-06
**Priority**: high
**Status**: pending
**Area**: infra

### Summary
A commit created for a new design document also included unrelated changes already staged in the repository index.

### Error
Commit `52480a9` contains 19 paths and 2,392 insertions / 331 deletions, including pre-existing staged edits to the tomography interface, app, UI, and example-file migration.

### Context
- `git status` before commit showed `MM` and `A`/`D` statuses, indicating staged work was already present.
- A path-scoped `git add` added the design document but did not isolate the subsequent commit from other staged paths.
- No reset, revert, or amend has been run.

### Suggested Fix
Before committing, inspect `git diff --cached --stat` and commit only when the staged index is known to contain exclusively task-owned paths; use a separate worktree/index if isolation is required.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/specs/2026-10-06-tomography-readme-cn-design.md`

---

## [ERR-20261006-001] git-index-write-denied

**Logged**: 2026-10-06
**Priority**: low
**Status**: pending
**Area**: infra

### Summary
Git could not stage the new design document because the sandbox denied writing `.git/index`.

### Error
```
fatal: Unable to create '.../.git/index.lock': Operation not permitted
```

### Context
- Command: `git add docs/superpowers/specs/2026-10-06-tomography-readme-cn-design.md`
- Repository source files are writable, but Git metadata is read-only in this sandbox.

### Suggested Fix
Request approved escalation for the narrowly scoped `git add` and `git commit` operations, or leave the design document uncommitted if approval is unavailable.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/specs/2026-10-06-tomography-readme-cn-design.md`

---
