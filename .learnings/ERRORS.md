# Errors

---

## [ERR-20261027-005] parser_export_order_lint

**Logged**: 2026-10-27T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
Ruff rejected the newly added parser export order in `__all__`.

### Context
- `parse_blocks` was listed after `parse_bytes`; the configured alphabetical rule required the reverse order.

### Resolution
- **Resolved**: 2026-10-27T00:00:00+08:00
- **Notes**: Reordered exports; targeted ruff and tests now pass.

---

## [ERR-20261027-004] siminics_test_fixture_overflow_value

**Logged**: 2026-10-27T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The new T3 parser test initially expected a raw overflow value rather than the expanded sync index.

### Context
The fixture `FE0002D4` encodes overflow value `0x2D4`; after the vendor 10-bit counter epoch expansion, the following event's sync index is `(0x2D4 + 1) * 1024 + 1`.

### Resolution
- **Resolved**: 2026-10-27T00:00:00+08:00
- **Notes**: Corrected the expected value in `tests/tdc/test_siminics_backend.py`.

---

## [ERR-20261027-003] full_tdc_regression_suite

**Logged**: 2026-10-27T00:00:00+08:00
**Priority**: low
**Status**: pending
**Area**: tests

### Summary
The full existing TDC test suite has three unrelated failures outside the Siminics backend.

### Error
```text
ExpS15TDC1Backend.get_singles: SinglesResult.__init__() missing channels
IDQ ID1000 tests: NameError: name 'np' is not defined
```

### Context
- Command: `pytest -q tests/tdc`
- Siminics-specific smoke checks, compileall, ruff, registry, and backend ABC tests passed.
- Failures occurred in pre-existing S15/IDQ code and were left untouched.

### Suggested Fix
Add the missing `channels` field to the experimental S15 singles result and import NumPy in the IDQ1000 backend, in a separate maintenance change.

### Metadata
- Reproducible: yes
- Related Files: `src/qtools/tdc/backends/s15_tdc1/exp_backend.py`, `src/qtools/tdc/backends/idq/backend_id1000.py`

---

## [ERR-20261007-003] notebook-ast-check-jupyter-magic

**Logged**: 2026-10-07
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The generic Python AST checker rejected the Jupyter magic `%matplotlib inline` in the notebook import cell.

### Error
```text
SyntaxError: invalid syntax
```

### Context
- Operation: parse every notebook code cell with `ast.parse()`.
- The notebook intentionally uses `%matplotlib inline`, which is valid in a Jupyter kernel but not in Python source syntax.
- `nbformat` validation and full `nbclient` execution both passed after this check.

### Suggested Fix
Use nbclient execution for notebook validation, or strip recognized IPython magics before applying a Python-only AST check.

### Metadata
- Reproducible: yes
- Related Files: `examples/simulated_slm.ipynb`

---

## [ERR-20261007-002] spec-self-review-string-mismatch

**Logged**: 2026-10-07
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
A design self-review assertion searched for an English phrase that was written in Chinese in the specification.

### Error
```text
AssertionError
```

### Context
- Operation: self-review of `docs/superpowers/specs/2026-10-07-phase-superposition-design.md`.
- The specification contains `全局 L2`, while the check expected `global L2`.
- No specification content was lost or invalidated.

### Suggested Fix
Use semantic or language-independent checks for multilingual design documents.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/specs/2026-10-07-phase-superposition-design.md`

---

## [ERR-20261007-001] notebook-plot-output-check

**Logged**: 2026-10-07
**Priority**: low
**Status**: pending
**Area**: tests

### Summary
Headless notebook execution completed successfully, but a plot-output assertion did not find display data because the notebook had not explicitly enabled the inline Matplotlib backend.

### Error
```text
AssertionError: 9
```

### Context
- Operation: execute `examples/simulated_slm.ipynb` with `nbclient` and `MPLBACKEND=Agg`, then assert that plot cells emitted `display_data`.
- The SLM phase generation and simulated backend loading cells succeeded.
- In the Agg backend, `plt.show()` emitted a non-interactive canvas warning without a captured notebook image output.

### Suggested Fix
Enable `%matplotlib inline` in notebook examples that are expected to produce captured plot outputs during headless execution.

### Metadata
- Reproducible: yes
- Related Files: `examples/simulated_slm.ipynb`

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

## [ERR-20261024-001] shell_command

**Logged**: 2026-10-24
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
文档检查命令调用了不存在的 `python` 可执行文件。

### Error
```
zsh: command not found: python
```

### Context
- Command attempted a short Markdown fence count using `python`.
- The environment provides `python3` instead.

### Suggested Fix
使用 `python3` 运行临时文档检查脚本。

### Metadata
- Reproducible: yes
- Related Files: docs/superpowers/specs/2026-10-06-tdc-data-structures-unification.md

---


## [ERR-20261027-001] compileall_reference_scripts

**Logged**: 2026-10-27T00:00:00+08:00
**Priority**: low
**Status**: pending
**Area**: config

### Summary
`python3 -m compileall -q src/qtools/slm` reaches legacy Python 2 scripts under `src/qtools/slm/refs/` and reports syntax errors.

### Error
```
SyntaxError: Missing parentheses in call to 'print'
```

### Context
The active SLM implementation was changed, then compileall was run over the whole SLM tree. The reference directory intentionally contains historical Python 2 examples and was not modified.

### Suggested Fix
Compile only active SLM modules or exclude `refs/` when validating this package.

### Metadata
- Reproducible: yes
- Related Files: src/qtools/slm/refs/lgphase/generate_Laguerre_Gauss_SLM.py

---

## [ERR-20261027-002] git_commit_spec

**Logged**: 2026-10-27T00:00:00+08:00
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
The approved Siminics backend design spec could not be committed because the workspace denied creation of `.git/index.lock`.

### Error
```
fatal: Unable to create '/Users/rayonde/Documents/Code/qtools/.git/index.lock': Operation not permitted
```

### Context
- The design file was written under `docs/superpowers/specs/2026-10-27-siminics-backend-design.md` and passed `git diff --check`.
- The failure occurred while running `git add`/`git commit`; no repository index mutation was completed.

### Suggested Fix
Retry the commit when the workspace grants write access to `.git`, or leave the design file uncommitted and report the environment restriction.

### Metadata
- Reproducible: unknown
- Related Files: docs/superpowers/specs/2026-10-27-siminics-backend-design.md

---


## [ERR-20261027-DM1] optional regression environment

**Logged**: 2026-10-27
**Priority**: low
**Status**: pending
**Area**: tests

### Summary
The DMP40 change's broader SLM regression could not collect because the active project venv lacks imageio.

### Error
`ModuleNotFoundError: No module named imageio` from `qtools.slm.display.displaymask`.

### Context
`pytest tests/dm src/qtools/camera/tests tests/slm/test_architecture.py tests/tdc/test_registry.py` stopped during SLM collection. Running the DM, camera and registry tests separately passed all 40 tests. DM tests alone passed all 30 tests. No dependency changes were needed for DM.

### Suggested Fix
Install the project's declared imageio dependency when working on SLM; do not report this collection failure as a DM regression or claim the SLM tests passed.

### Metadata
- Reproducible: yes
- Related Files: tests/slm/test_architecture.py, tests/dm/test_dmp40.py, pyproject.toml

---

## [ERR-20261027-PKG] Copied-package migration preflight

**Logged**: 2026-10-27T09:39:49.742144+00:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
Initial migration stopped before writes due to nested JavaScript/Python escaping and duplicate Finder metadata.

### Error
SyntaxError in nested command text; destination already exists for .DS_Store.

### Resolution
Use raw template strings only for scripts without backticks; use apply_patch for Markdown. Preflight source entries and remove generated egg-info with the redundant source directory.

### Metadata
- Reproducible: yes
- Related Files: src/qtools/motor, src/qtools/powermeter

---
