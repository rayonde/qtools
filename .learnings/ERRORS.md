# Errors

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
